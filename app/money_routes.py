"""Shared-expense endpoints: split expenses, ledgers, settle-ups and groups."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from . import access, crud, models, money, schemas
from .auth import get_current_user
from .database import get_db

router = APIRouter()
Me = Depends(get_current_user)


def _values(splits: Optional[list[schemas.SplitValue]]) -> Optional[dict[int, float]]:
    if splits is None:
        return None
    out: dict[int, float] = {}
    for s in splits:
        if s.user_id in out:
            raise HTTPException(status_code=400, detail="Each person can only appear once in a split")
        out[s.user_id] = s.value
    return out


def _guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except money.Conflict as e:
        raise HTTPException(status_code=409, detail=str(e))
    except money.MoneyError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _trip(db: Session, trip_id: int, me: models.User) -> models.Trip:
    return access.trip_or_404(db, trip_id, me)


def _group(db: Session, group_id: int, me: models.User) -> models.Group:
    return access.group_or_404(db, group_id, me)


def _expense(db: Session, expense_id: int, me: models.User) -> models.Expense:
    return access.expense_or_404(db, expense_id, me)


# --- Expenses ---------------------------------------------------------------

@router.post("/trips/{trip_id}/expenses/split", response_model=schemas.Expense)
def create_split_expense(trip_id: int, body: schemas.ExpenseSplitCreateRequest, me: models.User = Me, db: Session = Depends(get_db)):
    """Create an expense split equally, by exact amounts, by percentages, or by shares."""
    trip = _trip(db, trip_id, me)
    allowed = {p.id for p in trip.participants} | {trip.owner_id}
    return _guard(money.create_expense, db, amount=body.amount, description=body.description,
                  payer_id=body.payer_id, split_among=body.split_among, split_mode=body.split_mode,
                  values=_values(body.splits), trip_id=trip.id, allowed=allowed,
                  currency=body.currency, date=body.date)


@router.put("/expenses/{expense_id}", response_model=schemas.Expense)
def update_expense(expense_id: int, body: schemas.ExpenseUpdate, me: models.User = Me, db: Session = Depends(get_db)):
    """Edit an expense. Changing amount, payer, mode, people or values re-splits it in exact cents."""
    e = _expense(db, expense_id, me)
    return _guard(money.update_expense, db, e, amount=body.amount, description=body.description,
                  payer_id=body.payer_id, currency=body.currency, date=body.date, split_mode=body.split_mode,
                  split_among=body.split_among, values=_values(body.splits))


@router.delete("/expenses/{expense_id}", status_code=204)
def delete_expense(expense_id: int, me: models.User = Me, db: Session = Depends(get_db)):
    money.delete_expense(db, _expense(db, expense_id, me))
    return Response(status_code=204)


# --- Trip balances ----------------------------------------------------------

@router.get("/trips/{trip_id}/ledger")
def trip_ledger(trip_id: int, me: models.User = Me, db: Session = Depends(get_db)):
    """Per-person nets, raw pairwise debts, a simplified payment plan, and payment history."""
    return money.trip_ledger(db, _trip(db, trip_id, me))


@router.get("/trips/{trip_id}/balances")
def trip_balances(trip_id: int, me: models.User = Me, db: Session = Depends(get_db)):
    """Simplified who-pays-whom (kept for older clients; see /ledger for everything)."""
    return money.trip_ledger(db, _trip(db, trip_id, me))["simplified"]


@router.post("/trips/{trip_id}/settle", response_model=schemas.Settlement)
def settle_trip_pair(trip_id: int, body: schemas.SettleRequest, me: models.User = Me, db: Session = Depends(get_db)):
    """Record that from_user paid to_user (defaults to the full amount owed). History is kept."""
    trip = _trip(db, trip_id, me)
    return _guard(money.record_settlement, db, money.trip_ledger(db, trip), body.from_user_id, body.to_user_id,
                  body.amount, body.note, trip_id=trip.id, mode=body.mode)


@router.post("/trips/{trip_id}/settle-all", response_model=list[schemas.Settlement])
def settle_trip_all(trip_id: int, me: models.User = Me, db: Session = Depends(get_db)):
    trip = _trip(db, trip_id, me)
    return money.settle_all(db, money.trip_ledger(db, trip), trip_id=trip.id)


@router.delete("/settlements/{settlement_id}", status_code=204)
def undo_settlement(settlement_id: int, me: models.User = Me, db: Session = Depends(get_db)):
    st = db.get(models.Settlement, settlement_id)
    visible = st is not None and (
        me.id in (st.from_user_id, st.to_user_id)
        or (st.trip_id is not None and access.trips(db, me).filter(models.Trip.id == st.trip_id).first())
        or (st.group_id is not None and access.groups(db, me).filter(models.Group.id == st.group_id).first()))
    if not visible:
        raise HTTPException(status_code=404, detail="Settlement not found")
    db.delete(st)
    db.commit()
    return Response(status_code=204)


@router.put("/trips/{trip_id}/group", response_model=schemas.Trip)
def set_trip_group(trip_id: int, body: schemas.TripGroupLink, me: models.User = Me, db: Session = Depends(get_db)):
    """Put a trip in a group (its travelers join the group) or take it out with group_id=null."""
    trip = _trip(db, trip_id, me)
    if body.group_id is None:
        trip.group_id = None
    else:
        money.attach_trip(_group(db, body.group_id, me), trip)
    db.commit()
    db.refresh(trip)
    return trip


@router.post("/trips/{trip_id}/group", response_model=schemas.Group)
def group_from_trip(trip_id: int, body: schemas.GroupFromTrip, me: models.User = Me, db: Session = Depends(get_db)):
    """Create a group from this trip's travelers and link the trip to it."""
    g = money.group_from_trip(db, _trip(db, trip_id, me), body.name)
    g.owner_id = me.id
    if me not in g.members:
        g.members.append(me)
    db.commit()
    db.refresh(g)
    return g


# --- Groups -----------------------------------------------------------------

@router.get("/groups", response_model=list[schemas.Group])
def list_groups(me: models.User = Me, db: Session = Depends(get_db)):
    return access.groups(db, me).order_by(models.Group.id).all()


@router.post("/groups", response_model=schemas.Group)
def create_group(body: schemas.GroupCreate, me: models.User = Me, db: Session = Depends(get_db)):
    known = access.known_user_ids(db, me)
    if any(uid not in known for uid in body.member_ids):
        raise HTTPException(status_code=400, detail="Unknown user in member_ids")
    for tid in body.trip_ids:
        access.trip_or_404(db, tid, me)
    g = _guard(money.create_group, db, body.name, [me.id, *body.member_ids], body.trip_ids)
    g.owner_id = me.id
    db.commit()
    db.refresh(g)
    return g


@router.get("/groups/{group_id}", response_model=schemas.Group)
def read_group(group_id: int, me: models.User = Me, db: Session = Depends(get_db)):
    return _group(db, group_id, me)


@router.patch("/groups/{group_id}", response_model=schemas.Group)
def rename_group(group_id: int, body: schemas.GroupUpdate, me: models.User = Me, db: Session = Depends(get_db)):
    g = _group(db, group_id, me)
    if body.name is not None:
        if not body.name.strip():
            raise HTTPException(status_code=400, detail="Group name is required")
        g.name = body.name.strip()
    db.commit()
    db.refresh(g)
    return g


@router.delete("/groups/{group_id}", status_code=204)
def delete_group(group_id: int, force: bool = False, me: models.User = Me, db: Session = Depends(get_db)):
    _guard(money.delete_group, db, _group(db, group_id, me), force)
    return Response(status_code=204)


@router.post("/groups/{group_id}/members", response_model=schemas.Group)
def add_group_member(group_id: int, body: schemas.GroupMemberAdd, me: models.User = Me, db: Session = Depends(get_db)):
    g = _group(db, group_id, me)
    if body.user_id is not None:
        user = access.user_or_404(db, body.user_id, me)
    elif body.name and body.name.strip():
        user = crud.find_or_create_traveler(db, body.name, body.email, known_ids=access.known_user_ids(db, me))
    else:
        raise HTTPException(status_code=400, detail="Pass user_id or name")
    if user not in g.members:
        g.members.append(user)
    db.commit()
    db.refresh(g)
    return g


@router.delete("/groups/{group_id}/members/{user_id}", response_model=schemas.Group)
def remove_group_member(group_id: int, user_id: int, force: bool = False, me: models.User = Me, db: Session = Depends(get_db)):
    g = _group(db, group_id, me)
    user = db.get(models.User, user_id)
    if user is None or user not in g.members:
        raise HTTPException(status_code=404, detail="User not found")
    _guard(money.remove_member, db, g, user, force)
    db.refresh(g)
    return g


@router.post("/groups/{group_id}/expenses", response_model=schemas.Expense)
def create_group_expense(group_id: int, body: schemas.ExpenseSplitCreateRequest, me: models.User = Me, db: Session = Depends(get_db)):
    """A standalone shared expense that isn't part of any trip."""
    g = _group(db, group_id, me)
    return _guard(money.create_expense, db, amount=body.amount, description=body.description,
                  payer_id=body.payer_id, split_among=body.split_among, split_mode=body.split_mode,
                  values=_values(body.splits), group_id=g.id, allowed={m.id for m in g.members},
                  currency=body.currency, date=body.date)


@router.post("/groups/{group_id}/debts", response_model=schemas.Expense)
def create_group_debt(group_id: int, body: schemas.DebtCreate, me: models.User = Me, db: Session = Depends(get_db)):
    """Record an existing IOU, e.g. "Sam already owes Maya $30"."""
    g = _group(db, group_id, me)
    if body.from_user_id == body.to_user_id:
        raise HTTPException(status_code=400, detail="Pick two different people")
    return _guard(money.create_expense, db, amount=body.amount, description=body.description,
                  payer_id=body.to_user_id, split_among=[body.from_user_id], split_mode="exact",
                  values={body.from_user_id: body.amount}, group_id=g.id,
                  allowed={m.id for m in g.members}, currency=body.currency)


@router.get("/groups/{group_id}/balances")
def group_balances(group_id: int, me: models.User = Me, db: Session = Depends(get_db)):
    """Combined balances across all of the group's trips plus standalone debts and payments."""
    return money.group_ledger(db, _group(db, group_id, me))


@router.post("/groups/{group_id}/settle", response_model=schemas.Settlement)
def settle_group_pair(group_id: int, body: schemas.SettleRequest, me: models.User = Me, db: Session = Depends(get_db)):
    g = _group(db, group_id, me)
    return _guard(money.record_settlement, db, money.group_ledger(db, g), body.from_user_id, body.to_user_id,
                  body.amount, body.note, group_id=g.id, mode=body.mode)


@router.post("/groups/{group_id}/settle-all", response_model=list[schemas.Settlement])
def settle_group_all(group_id: int, me: models.User = Me, db: Session = Depends(get_db)):
    g = _group(db, group_id, me)
    return money.settle_all(db, money.group_ledger(db, g), group_id=g.id)
