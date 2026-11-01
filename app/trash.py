"""Deleting trips: a deleted trip goes to Recently Deleted for 30 days, then it is purged.

While it is there the trip and everything on it (flights, stays, rentals, expenses, settlements)
is hidden from lists, stats, stories, journeys, suggestions and email-in matching. Imports still
see its bookings when they check for duplicates, so a forwarded email can't bring them back.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from . import crud, models, money

log = logging.getLogger("trippy.trash")

KEEP_DAYS = 30
PURGE_EVERY_SECONDS = 6 * 3600
_STORY_FIELDS = ("user_id", "title", "subtitle", "theme", "cover_photo", "order_json", "items_json")


def counts(db: Session, trip: models.Trip) -> dict:
    return {
        "flights": len(trip.flights),
        "stays": len(trip.lodgings),
        "rentals": len(trip.rental_cars),
        "expenses": len(trip.expenses),
        "activities": len(trip.activities),
        "documents": len(trip.documents),
        "settlements": db.query(models.Settlement).filter(models.Settlement.trip_id == trip.id).count(),
        "travelers": len(trip.participants),
    }


def unsettled(db: Session, trip: models.Trip) -> dict:
    people = [p for p in money.trip_ledger(db, trip)["people"] if p["net_cents"]]
    return {"unsettled": bool(people), "unsettled_people": len(people),
            "unsettled_cents": sum(p["net_cents"] for p in people if p["net_cents"] > 0)}


def _journey_after(trip: models.Trip) -> Optional[dict]:
    j = trip.journey
    if j is None:
        return None
    left = len([t for t in j.trips if t.id != trip.id and t.deleted_at is None])
    return {"id": j.id, "title": j.title, "trips_left": left, "journey_deleted": left == 0}


def preview(db: Session, trip: models.Trip, user: models.User) -> dict:
    owner = trip.owner_id == user.id
    return {
        "trip_id": trip.id, "title": trip.title, "is_owner": owner,
        "action": "delete" if owner else "leave",
        "counts": counts(db, trip), **unsettled(db, trip),
        "journey": _journey_after(trip), "keep_days": KEEP_DAYS,
    }


def _summary(db: Session, trip: models.Trip) -> dict:
    purge_at = trip.deleted_at + timedelta(days=KEEP_DAYS) if trip.deleted_at else None
    return {"id": trip.id, "title": trip.title, "start_date": trip.start_date, "end_date": trip.end_date,
            "deleted_at": trip.deleted_at, "purge_at": purge_at, "counts": counts(db, trip)}


def soft_delete(db: Session, trip: models.Trip, now: Optional[datetime] = None) -> dict:
    """Moves the trip to Recently Deleted. Story edits and its journey slot are kept for restore.
    Leaves its journey; a journey left with no trips is deleted. Caller commits."""
    stories = db.query(models.TripStory).filter(models.TripStory.trip_id == trip.id).all()
    saved = {"stories": [{k: getattr(s, k) for k in _STORY_FIELDS} for s in stories]}
    for s in stories:
        db.delete(s)
    journey = _journey_after(trip)
    if trip.journey is not None:
        saved["journey"] = {"id": trip.journey_id, "position": trip.journey_position}
        j = trip.journey
        trip.journey_id = None
        trip.journey_position = None
        db.flush()
        db.refresh(j)
        if not [t for t in j.trips if t.deleted_at is None]:
            for t in list(j.trips):  # trashed trips still pointing here
                t.journey_id = None
            db.query(models.Drive).filter(models.Drive.journey_id == j.id).update({models.Drive.journey_id: None})
            db.delete(j)
    trip.trash_json = json.dumps(saved)
    trip.deleted_at = now or datetime.utcnow()
    db.flush()
    return {"id": trip.id, "journey": journey}


def restore(db: Session, trip: models.Trip) -> models.Trip:
    saved = json.loads(trip.trash_json or "{}")
    for s in saved.get("stories", []):
        exists = db.query(models.TripStory).filter(models.TripStory.trip_id == trip.id,
                                                   models.TripStory.user_id == s["user_id"]).first()
        if exists is None and db.get(models.User, s["user_id"]) is not None:
            db.add(models.TripStory(trip_id=trip.id, **s))
    slot = saved.get("journey")
    if slot:
        j = db.get(models.Journey, slot["id"])
        if j is not None and j.owner_id == trip.owner_id:
            trip.journey_id = j.id
            trip.journey_position = slot.get("position")
    trip.deleted_at = None
    trip.trash_json = None
    db.commit()
    db.refresh(trip)
    return trip


def purge(db: Session, trip: models.Trip) -> None:
    """Permanently deletes the trip and what's on it. Bookings that belong to another traveler
    are unlinked and kept, so nobody loses their own records."""
    for coll in (trip.flights, trip.rental_cars, trip.lodgings):
        for row in list(coll):
            if row.owner_id in (None, trip.owner_id):
                if isinstance(row, models.RentalCar):
                    db.query(models.Drive).filter(models.Drive.rental_id == row.id).update({models.Drive.rental_id: None})
                db.delete(row)
            else:
                row.trip_id = None
    db.flush()
    db.refresh(trip)
    if trip.journey_id is not None:
        trip.journey_id = None
    crud.delete_trip(db, trip)  # expenses, settlements, invites, stories, activities, documents; commits


def trash(db: Session, user: models.User) -> list[dict]:
    rows = (db.query(models.Trip).filter(models.Trip.owner_id == user.id, models.Trip.deleted_at.isnot(None))
            .order_by(models.Trip.deleted_at.desc()).all())
    return [_summary(db, t) for t in rows]


def purge_expired(db: Session, now: Optional[datetime] = None) -> int:
    cutoff = (now or datetime.utcnow()) - timedelta(days=KEEP_DAYS)
    old = db.query(models.Trip).filter(models.Trip.deleted_at.isnot(None), models.Trip.deleted_at < cutoff).all()
    for t in old:
        purge(db, t)
    if old:
        log.info("trash: purged %d trip(s) deleted more than %d days ago", len(old), KEEP_DAYS)
    return len(old)


def start(session_factory) -> threading.Thread:
    """Purge once at startup, then every few hours."""
    def loop():
        while True:
            db = session_factory()
            try:
                purge_expired(db)
            except Exception:  # never take the API down over housekeeping
                log.exception("trash: purge failed")
                db.rollback()
            finally:
                db.close()
            time.sleep(PURGE_EVERY_SECONDS)
    t = threading.Thread(target=loop, name="trippy-trash-purge", daemon=True)
    t.start()
    return t
