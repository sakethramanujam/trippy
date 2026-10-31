"""One-time invite codes for claiming a placeholder traveler.

A placeholder is someone added to a trip who hasn't signed up. Whoever claims it gets every trip,
expense and group attached to it, so knowing the email address isn't enough: the claimer needs a
code that a traveler on the trip shared with them (or an email on TRIPPY_SIGNUP_ALLOWLIST).
Codes are random, single use, expire after INVITE_DAYS, and only their SHA-256 is stored.
"""
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from . import models

INVITE_DAYS = 14
ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"  # no 0/O, 1/I/L, U
CODE_LEN = 10


def normalize(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())


def hash_code(code: str) -> str:
    return hashlib.sha256(normalize(code).encode()).hexdigest()


def new_code() -> str:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LEN))
    return f"{raw[:5]}-{raw[5:]}"


def issue(db: Session, trip: models.Trip, person: models.User, inviter: models.User) -> tuple[str, datetime]:
    """Create (or replace) the code for `person` on `trip`. Any earlier code for them stops working."""
    if not person.is_placeholder:
        raise HTTPException(status_code=400, detail="That traveler already has an account")
    if person.id not in {p.id for p in trip.participants} and person.id != trip.owner_id:
        raise HTTPException(status_code=404, detail="That person isn't on this trip")
    inv = (db.query(models.TripInvite)
           .filter(models.TripInvite.trip_id == trip.id, models.TripInvite.user_id == person.id,
                   models.TripInvite.claimed_at.is_(None)).first())
    if inv is None:
        email = person.email if person.email and not person.email.endswith("@travelers.trippy.local") else ""
        inv = models.TripInvite(trip_id=trip.id, email=email, user_id=person.id)
        db.add(inv)
    code = new_code()
    inv.code_hash = hash_code(code)
    inv.code_expires_at = datetime.utcnow() + timedelta(days=INVITE_DAYS)
    inv.invited_by_id = inviter.id
    db.commit()
    return code, inv.code_expires_at


def find(db: Session, code: Optional[str]) -> Optional[models.TripInvite]:
    """The unclaimed, unexpired invite for `code`, whose traveler is still a placeholder."""
    if not code or len(normalize(code)) != CODE_LEN:
        return None
    inv = db.query(models.TripInvite).filter(models.TripInvite.code_hash == hash_code(code)).first()
    if inv is None or inv.claimed_at is not None:
        return None
    if inv.code_expires_at is None or inv.code_expires_at < datetime.utcnow():
        return None
    person = db.get(models.User, inv.user_id)
    if person is None or not person.is_placeholder:
        return None
    return inv


def mark_claimed(db: Session, user_id: int) -> int:
    """Close every open invite for this traveler (they now have an account). Returns the count."""
    now = datetime.utcnow()
    rows = db.query(models.TripInvite).filter(models.TripInvite.user_id == user_id,
                                              models.TripInvite.claimed_at.is_(None)).all()
    for inv in rows:
        inv.claimed_at = now
        inv.code_hash = None
    return len(rows)


def absorb(db: Session, placeholder: models.User, me: models.User) -> int:
    """An existing account redeems a code: it takes the placeholder's place on its trips, groups,
    expenses and settlements, and the placeholder is removed. Returns the number of trips joined.
    Refuses (409) when the two already overlap in a way that can't be merged automatically."""
    pid, mid = placeholder.id, me.id
    owned = [m for m in (models.Trip, models.RentalCar, models.Lodging, models.Journey, models.Group)
             if db.query(m).filter(m.owner_id == pid).first() is not None]
    split_clash = (db.query(models.ExpenseSplit.expense_id)
                   .filter(models.ExpenseSplit.user_id == pid)
                   .filter(models.ExpenseSplit.expense_id.in_(
                       db.query(models.ExpenseSplit.expense_id).filter(models.ExpenseSplit.user_id == mid)))
                   .first())
    settle_clash = db.query(models.Settlement).filter(or_(
        (models.Settlement.from_user_id == pid) & (models.Settlement.to_user_id == mid),
        (models.Settlement.from_user_id == mid) & (models.Settlement.to_user_id == pid))).first()
    if owned or split_clash or settle_clash:
        raise HTTPException(status_code=409, detail=(
            "You and this traveler already share expenses, so they can't be merged automatically. "
            "Ask the trip's organizer to add you directly."))
    joined = 0
    for trip in list(placeholder.participating_trips):
        trip.participants.remove(placeholder)
        if me not in trip.participants and trip.owner_id != mid:
            trip.participants.append(me)
            joined += 1
    for g in db.query(models.Group).filter(models.Group.members.any(models.User.id == pid)).all():
        g.members.remove(placeholder)
        if me not in g.members:
            g.members.append(me)
    db.query(models.Expense).filter(models.Expense.payer_id == pid).update({"payer_id": mid}, synchronize_session=False)
    db.query(models.ExpenseSplit).filter(models.ExpenseSplit.user_id == pid).update({"user_id": mid}, synchronize_session=False)
    db.query(models.Settlement).filter(models.Settlement.from_user_id == pid).update({"from_user_id": mid}, synchronize_session=False)
    db.query(models.Settlement).filter(models.Settlement.to_user_id == pid).update({"to_user_id": mid}, synchronize_session=False)
    mark_claimed(db, pid)
    db.query(models.TripInvite).filter(models.TripInvite.user_id == pid).update({"user_id": mid}, synchronize_session=False)
    db.flush()
    db.delete(placeholder)
    db.commit()
    return joined
