"""Shared-expense service: exact-cents expenses, ledgers, groups and settlements."""
from __future__ import annotations

from typing import Iterable, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from . import access, models
from .ledger import Edge, SplitError, build_splits, from_cents, net_balances, pairwise, simplify, to_cents

STANDALONE = "IOUs"
PAYMENTS = "Payments"


class MoneyError(ValueError):
    """Bad input; the API turns it into a 400."""


class Conflict(ValueError):
    """Refused because it would orphan money; the API turns it into a 409."""


# --- Expenses ---------------------------------------------------------------

def split_cents(expense: models.Expense) -> list[tuple[int, int]]:
    return [(s.user_id, s.amount_cents if s.amount_cents is not None else to_cents(s.amount_owed or 0))
            for s in expense.splits]


def expense_cents(expense: models.Expense) -> int:
    return expense.amount_cents if expense.amount_cents is not None else to_cents(expense.amount or 0)


def _apply_splits(db: Session, expense: models.Expense, total_cents: int, mode: str,
                  people: list[int], values: Optional[dict[int, float]], allowed: Optional[set[int]]):
    if values and not people:
        people = list(values.keys())
    if len(set(people)) != len(people):
        raise MoneyError("Each person can only appear once in a split")
    if allowed is not None:
        outsiders = sorted((set(people) | {expense.payer_id}) - allowed)
        if outsiders:
            raise MoneyError(f"Users {outsiders} aren't in this trip or group")
    try:
        parts = build_splits(total_cents, mode, people, values, payer_id=expense.payer_id)
    except SplitError as e:
        raise MoneyError(str(e)) from e
    expense.splits.clear()
    db.flush()
    for uid, cents, share in parts:
        expense.splits.append(models.ExpenseSplit(user_id=uid, amount_cents=cents, amount_owed=from_cents(cents),
                                                  share=share, is_settled=False))
    expense.amount_cents = total_cents
    expense.amount = from_cents(total_cents)
    expense.split_mode = mode


def create_expense(db: Session, *, amount: float, description: str, payer_id: int, split_among: list[int],
                   split_mode: str = "equal", values: Optional[dict[int, float]] = None,
                   trip_id: Optional[int] = None, group_id: Optional[int] = None,
                   allowed: Optional[set[int]] = None, currency: str = "USD", date=None) -> models.Expense:
    total = to_cents(amount)
    if total <= 0:
        raise MoneyError("Amount must be greater than zero")
    if not description.strip():
        raise MoneyError("Description is required")
    e = models.Expense(trip_id=trip_id, group_id=group_id, payer_id=payer_id, description=description.strip(),
                       currency=currency or "USD", date=date)
    db.add(e)
    _apply_splits(db, e, total, split_mode, list(split_among), values, allowed)
    db.commit()
    db.refresh(e)
    return e


def allowed_people(db: Session, expense: models.Expense) -> Optional[set[int]]:
    if expense.trip_id is not None:
        trip = expense.trip
        return {p.id for p in trip.participants} | {trip.owner_id}
    if expense.group_id is not None:
        return {m.id for m in expense.group.members}
    return None


def update_expense(db: Session, expense: models.Expense, *, amount=None, description=None, payer_id=None,
                   currency=None, date=None, split_mode=None, split_among=None,
                   values: Optional[dict[int, float]] = None) -> models.Expense:
    if description is not None:
        if not description.strip():
            raise MoneyError("Description is required")
        expense.description = description.strip()
    if currency is not None:
        expense.currency = currency
    if date is not None:
        expense.date = date
    resplit = any(v is not None for v in (amount, payer_id, split_mode, split_among, values))
    if payer_id is not None:
        expense.payer_id = payer_id
    if resplit:
        total = to_cents(amount) if amount is not None else expense_cents(expense)
        if total <= 0:
            raise MoneyError("Amount must be greater than zero")
        mode = split_mode or expense.split_mode or "equal"
        current = [uid for uid, _ in split_cents(expense)]
        if values is None and mode != "equal":
            if split_mode is None and amount is not None and mode == "exact":
                raise MoneyError("Changing the amount of an exact split needs new per-person amounts")
            values = {s.user_id: s.share for s in expense.splits if s.share is not None} or None
        people = split_among if split_among is not None else (list(values.keys()) if values else current)
        _apply_splits(db, expense, total, mode, people, values, allowed_people(db, expense))
    db.commit()
    db.refresh(expense)
    return expense


def delete_expense(db: Session, expense: models.Expense) -> None:
    db.delete(expense)  # splits cascade
    db.commit()


# --- Ledgers ----------------------------------------------------------------

def _edges(expenses: Iterable[models.Expense], settlements: Iterable[models.Settlement], label) -> list[Edge]:
    edges = []
    for e in expenses:
        src = label(e)
        for s in e.splits:
            if s.is_settled or s.user_id == e.payer_id:
                continue  # legacy flag from the old settle endpoint; self-shares owe nobody
            cents = s.amount_cents if s.amount_cents is not None else to_cents(s.amount_owed or 0)
            edges.append(Edge(s.user_id, e.payer_id, cents, src))
    for st in settlements:
        # from paid to: cancels what from owed to.
        edges.append(Edge(st.to_user_id, st.from_user_id, st.amount_cents, PAYMENTS))
    return edges


def _ledger(db: Session, edges: list[Edge], people: list[int], expenses, settlements) -> dict:
    net = net_balances(edges)
    ids = list(dict.fromkeys(list(people) + sorted(net.keys())))
    users = {u.id: u for u in db.query(models.User).filter(models.User.id.in_(ids)).all()} if ids else {}
    name = lambda uid: users[uid].username if uid in users else f"User {uid}"  # noqa: E731

    paid: dict[int, int] = {}
    share: dict[int, int] = {}
    for e in expenses:
        paid[e.payer_id] = paid.get(e.payer_id, 0) + expense_cents(e)
        for uid, c in split_cents(e):
            share[uid] = share.get(uid, 0) + c
    sent: dict[int, int] = {}
    received: dict[int, int] = {}
    for st in settlements:
        sent[st.from_user_id] = sent.get(st.from_user_id, 0) + st.amount_cents
        received[st.to_user_id] = received.get(st.to_user_id, 0) + st.amount_cents

    def named(rows):
        for r in rows:
            r["from_username"] = name(r["from_user_id"])
            r["to_username"] = name(r["to_user_id"])
            r["amount"] = from_cents(r["amount_cents"])
        return rows

    return {
        "total_cents": sum(expense_cents(e) for e in expenses),
        "people": [{
            "user_id": uid, "name": name(uid),
            "paid_cents": paid.get(uid, 0), "share_cents": share.get(uid, 0),
            "sent_cents": sent.get(uid, 0), "received_cents": received.get(uid, 0),
            "net_cents": net.get(uid, 0), "net": from_cents(net.get(uid, 0)),
        } for uid in ids],
        "pairwise": named(pairwise(edges)),
        "simplified": named(simplify(net)),
        "settlements": [{
            "id": st.id, "from_user_id": st.from_user_id, "from_username": name(st.from_user_id),
            "to_user_id": st.to_user_id, "to_username": name(st.to_user_id),
            "amount_cents": st.amount_cents, "amount": from_cents(st.amount_cents),
            "trip_id": st.trip_id, "group_id": st.group_id, "note": st.note,
            "created_at": st.created_at.isoformat() if st.created_at else None,
        } for st in sorted(settlements, key=lambda s: s.id, reverse=True)],
    }


def _trip_parts(db: Session, trip: models.Trip):
    expenses = db.query(models.Expense).filter(models.Expense.trip_id == trip.id).all()
    settlements = db.query(models.Settlement).filter(models.Settlement.trip_id == trip.id).all()
    return expenses, settlements


def trip_ledger(db: Session, trip: models.Trip) -> dict:
    expenses, settlements = _trip_parts(db, trip)
    edges = _edges(expenses, settlements, lambda e: trip.title)
    people = [trip.owner_id] + [p.id for p in trip.participants]
    led = _ledger(db, edges, people, expenses, settlements)
    led.update({"trip_id": trip.id, "group_id": trip.group_id})
    return led


def _group_parts(db: Session, group: models.Group):
    trip_ids = [t.id for t in group.trips if t.deleted_at is None]
    expenses = db.query(models.Expense).filter(or_(
        models.Expense.group_id == group.id,
        models.Expense.trip_id.in_(trip_ids) if trip_ids else False,
    )).filter(access.live(models.Expense)).all()
    settlements = db.query(models.Settlement).filter(or_(
        models.Settlement.group_id == group.id,
        models.Settlement.trip_id.in_(trip_ids) if trip_ids else False,
    )).filter(access.live(models.Settlement)).all()
    return expenses, settlements


def group_ledger(db: Session, group: models.Group) -> dict:
    expenses, settlements = _group_parts(db, group)
    titles = {t.id: t.title for t in group.trips if t.deleted_at is None}
    edges = _edges(expenses, settlements, lambda e: titles.get(e.trip_id, STANDALONE))
    led = _ledger(db, edges, [m.id for m in group.members], expenses, settlements)
    standalone = [e for e in expenses if e.trip_id is None]
    led.update({
        "group_id": group.id, "name": group.name,
        "trips": [{"id": t.id, "title": t.title} for t in group.trips if t.deleted_at is None],
        "standalone": [{
            "id": e.id, "description": e.description, "payer_id": e.payer_id,
            "amount_cents": expense_cents(e), "amount": from_cents(expense_cents(e)),
            "split_mode": e.split_mode,
            "splits": [{"user_id": u, "amount_cents": c} for u, c in split_cents(e)],
        } for e in sorted(standalone, key=lambda e: e.id, reverse=True)],
    })
    return led


def person_net(ledger: dict, user_id: int) -> int:
    return next((p["net_cents"] for p in ledger["people"] if p["user_id"] == user_id), 0)


# --- Settling ---------------------------------------------------------------

def _owed(ledger: dict, debtor: int, creditor: int, mode: str) -> int:
    """What debtor owes creditor in the view the user is looking at (simplified or pairwise)."""
    if mode not in ("simplified", "pairwise"):
        raise MoneyError("mode must be simplified or pairwise")
    return next((r["amount_cents"] for r in ledger[mode]
                 if r["from_user_id"] == debtor and r["to_user_id"] == creditor), 0)


def record_settlement(db: Session, ledger: dict, from_user_id: int, to_user_id: int, amount=None, note=None,
                      trip_id=None, group_id=None, mode: str = "simplified") -> models.Settlement:
    if from_user_id == to_user_id:
        raise MoneyError("Pick two different people")
    if amount is None:
        cents = _owed(ledger, from_user_id, to_user_id, mode)
        if cents == 0:
            raise MoneyError("Nothing is owed between these two people")
    else:
        cents = to_cents(amount)
        if cents <= 0:
            raise MoneyError("Amount must be greater than zero")
    st = models.Settlement(from_user_id=from_user_id, to_user_id=to_user_id, amount_cents=cents,
                           trip_id=trip_id, group_id=group_id, note=note)
    db.add(st)
    db.commit()
    db.refresh(st)
    return st


def settle_all(db: Session, ledger: dict, trip_id=None, group_id=None, note="Settle all") -> list[models.Settlement]:
    rows = []
    for p in ledger["simplified"]:
        st = models.Settlement(from_user_id=p["from_user_id"], to_user_id=p["to_user_id"],
                               amount_cents=p["amount_cents"], trip_id=trip_id, group_id=group_id, note=note)
        db.add(st)
        rows.append(st)
    db.commit()
    for st in rows:
        db.refresh(st)
    return rows


# --- Groups -----------------------------------------------------------------

def create_group(db: Session, name: str, member_ids: list[int], trip_ids: list[int]) -> models.Group:
    if not name.strip():
        raise MoneyError("Group name is required")
    g = models.Group(name=name.strip())
    db.add(g)
    ids = list(dict.fromkeys(member_ids))
    users = db.query(models.User).filter(models.User.id.in_(ids)).all() if ids else []
    if len(users) != len(ids):
        raise MoneyError("Unknown user in member_ids")
    g.members.extend(users)
    for tid in trip_ids:
        trip = db.get(models.Trip, tid)
        if trip is None:
            raise MoneyError(f"Trip {tid} not found")
        attach_trip(g, trip)
    db.commit()
    db.refresh(g)
    return g


def attach_trip(group: models.Group, trip: models.Trip) -> None:
    """Link a trip to a group and make sure all its travelers are members."""
    trip.group = group
    have = {m.id for m in group.members}
    for u in [trip.owner] + list(trip.participants):
        if u is not None and u.id not in have:
            group.members.append(u)
            have.add(u.id)


def group_from_trip(db: Session, trip: models.Trip, name: Optional[str]) -> models.Group:
    g = models.Group(name=(name or "").strip() or f"{trip.title} crew")
    db.add(g)
    attach_trip(g, trip)
    db.commit()
    db.refresh(g)
    return g


def remove_member(db: Session, group: models.Group, user: models.User, force: bool) -> None:
    if not force and person_net(group_ledger(db, group), user.id) != 0:
        raise Conflict(f"{user.username} still has an open balance in this group. Settle up first, or pass force=true.")
    if any(user.id == t.owner_id or user in t.participants for t in group.trips) and not force:
        raise Conflict(f"{user.username} is a traveler on one of this group's trips")
    if user in group.members:
        group.members.remove(user)
    db.commit()


def delete_group(db: Session, group: models.Group, force: bool) -> None:
    standalone = db.query(models.Expense).filter(models.Expense.group_id == group.id).all()
    settlements = db.query(models.Settlement).filter(models.Settlement.group_id == group.id).all()
    if (standalone or settlements) and not force:
        raise Conflict("Group has standalone debts or payments; pass force=true to delete them too")
    for e in standalone:
        db.delete(e)
    for s in settlements:
        db.delete(s)
    for t in list(group.trips):
        t.group_id = None
    group.members.clear()
    db.delete(group)
    db.commit()
