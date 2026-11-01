"""Who can see what. Every query that returns user data goes through these helpers.

- Trips: the owner and the trip's travelers.
- Flights, rentals, stays: their owner, or anyone who can see the trip they're on.
- Expenses: the payer, people in the split, and members of the trip or group it belongs to.
- Groups (and their IOUs/settlements): members and the creator.
- People: yourself plus anyone you share a trip or group with.
Things you can't see answer 404, so ids don't leak.
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Query, Session

from . import models


def trashed_trip_ids():
    """Trips in Recently Deleted. Their bookings and expenses are hidden with them."""
    return select(models.Trip.id).where(models.Trip.deleted_at.isnot(None))


def trip_ids_subquery(user_id: int):
    part = (select(models.trip_participants.c.trip_id)
            .where(models.trip_participants.c.user_id == user_id,
                   models.trip_participants.c.trip_id.notin_(trashed_trip_ids())))
    owned = select(models.Trip.id).where(models.Trip.owner_id == user_id, models.Trip.deleted_at.is_(None))
    return owned.union(part)


def live(model):
    """Rows not on a trip in Recently Deleted."""
    return or_(model.trip_id.is_(None), model.trip_id.notin_(trashed_trip_ids()))


def group_ids_subquery(user_id: int):
    member = select(models.group_members.c.group_id).where(models.group_members.c.user_id == user_id)
    owned = select(models.Group.id).where(models.Group.owner_id == user_id)
    return owned.union(member)


def trips(db: Session, user: models.User) -> Query:
    return db.query(models.Trip).filter(models.Trip.id.in_(trip_ids_subquery(user.id)))


def can_see_trip(user: models.User, trip: models.Trip) -> bool:
    return trip.owner_id == user.id or any(p.id == user.id for p in trip.participants)


def trip_or_404(db: Session, trip_id: int, user: models.User) -> models.Trip:
    trip = db.get(models.Trip, trip_id)
    if trip is None or trip.deleted_at is not None or not can_see_trip(user, trip):
        raise HTTPException(status_code=404, detail="Trip not found")
    return trip


def trashed_trip_or_404(db: Session, trip_id: int, user: models.User) -> models.Trip:
    """A trip of yours in Recently Deleted (only the owner can see or restore it)."""
    trip = db.get(models.Trip, trip_id)
    if trip is None or trip.deleted_at is None or trip.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Deleted trip not found")
    return trip


def owned_trip_or_404(db: Session, trip_id: int, user: models.User) -> models.Trip:
    trip = trip_or_404(db, trip_id, user)
    if trip.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the trip's owner can do that")
    return trip


def _owned_or_on_trip(model, user: models.User):
    return or_(model.owner_id == user.id, model.trip_id.in_(trip_ids_subquery(user.id)))


def flights(db: Session, user: models.User, include_trashed: bool = False) -> Query:
    q = db.query(models.Flight).filter(_owned_or_on_trip(models.Flight, user))
    return q if include_trashed else q.filter(live(models.Flight))


def rentals(db: Session, user: models.User, include_trashed: bool = False) -> Query:
    q = db.query(models.RentalCar).filter(_owned_or_on_trip(models.RentalCar, user))
    return q if include_trashed else q.filter(live(models.RentalCar))


def lodgings(db: Session, user: models.User, include_trashed: bool = False) -> Query:
    q = db.query(models.Lodging).filter(_owned_or_on_trip(models.Lodging, user))
    return q if include_trashed else q.filter(live(models.Lodging))


def expenses(db: Session, user: models.User) -> Query:
    in_split = select(models.ExpenseSplit.expense_id).where(models.ExpenseSplit.user_id == user.id)
    return db.query(models.Expense).filter(or_(
        models.Expense.payer_id == user.id,
        models.Expense.id.in_(in_split),
        models.Expense.trip_id.in_(trip_ids_subquery(user.id)),
        models.Expense.group_id.in_(group_ids_subquery(user.id)),
    )).filter(live(models.Expense))


def groups(db: Session, user: models.User) -> Query:
    return db.query(models.Group).filter(models.Group.id.in_(group_ids_subquery(user.id)))


def group_or_404(db: Session, group_id: int, user: models.User) -> models.Group:
    g = db.get(models.Group, group_id)
    if g is None or not (g.owner_id == user.id or any(m.id == user.id for m in g.members)):
        raise HTTPException(status_code=404, detail="Group not found")
    return g


def expense_or_404(db: Session, expense_id: int, user: models.User) -> models.Expense:
    e = expenses(db, user).filter(models.Expense.id == expense_id).first()
    if e is None:
        raise HTTPException(status_code=404, detail="Expense not found")
    return e


def rental_or_404(db: Session, rental_id: int, user: models.User) -> models.RentalCar:
    r = rentals(db, user).filter(models.RentalCar.id == rental_id).first()
    if r is None:
        raise HTTPException(status_code=404, detail="Rental car not found")
    return r


def editable_rental_or_404(db: Session, rental_id: int, user: models.User) -> models.RentalCar:
    r = rental_or_404(db, rental_id, user)
    trip_owner = r.trip.owner_id if r.trip is not None else None
    if user.id not in (r.owner_id, trip_owner):
        raise HTTPException(status_code=403, detail="Only its owner or the trip's owner can change that rental")
    return r


def lodging_or_404(db: Session, lodging_id: int, user: models.User) -> models.Lodging:
    h = lodgings(db, user).filter(models.Lodging.id == lodging_id).first()
    if h is None:
        raise HTTPException(status_code=404, detail="Stay not found")
    return h


def editable_lodging_or_404(db: Session, lodging_id: int, user: models.User) -> models.Lodging:
    h = lodging_or_404(db, lodging_id, user)
    trip_owner = h.trip.owner_id if h.trip is not None else None
    if user.id not in (h.owner_id, trip_owner):
        raise HTTPException(status_code=403, detail="Only its owner or the trip's owner can change that stay")
    return h


def known_user_ids(db: Session, user: models.User) -> set[int]:
    """Yourself plus everyone on a trip or in a group with you."""
    ids = {user.id}
    for t in trips(db, user).all():
        ids.add(t.owner_id)
        ids.update(p.id for p in t.participants)
    for g in groups(db, user).all():
        ids.update(m.id for m in g.members)
    ids.discard(None)
    return ids


def user_or_404(db: Session, user_id: int, user: models.User) -> models.User:
    if user_id not in known_user_ids(db, user):
        raise HTTPException(status_code=404, detail="User not found")
    return db.get(models.User, user_id)


def mark_pinned(db: Session, user: models.User, trips):
    """Sets `pinned` on each trip for this user (pins are per user, kept in trip_pins)."""
    rows = list(trips)
    ids = {t.id for t in rows}
    pins = {p for (p,) in db.query(models.TripPin.trip_id).filter(models.TripPin.user_id == user.id,
                                                                   models.TripPin.trip_id.in_(ids))} if ids else set()
    for t in rows:
        t.pinned = t.id in pins
    return rows
