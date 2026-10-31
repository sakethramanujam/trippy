"""Delete trips (to Recently Deleted), preview what goes with them, restore, purge, bulk delete."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import access, models, money, schemas, trash
from .auth import get_current_user
from .database import get_db

router = APIRouter(tags=["trash"])
Me = Depends(get_current_user)
Db = Depends(get_db)


class TripIds(BaseModel):
    trip_ids: list[int] = Field(min_length=1, max_length=200)
    permanent: bool = False


def delete_one(db: Session, trip: models.Trip, permanent: bool) -> dict:
    if permanent:
        info = trash.soft_delete(db, trip)  # same journey handling as a normal delete
        db.commit()
        trash.purge(db, trip)
        return {**info, "permanent": True}
    info = trash.soft_delete(db, trip)
    db.commit()
    return {**info, "permanent": False}


@router.get("/trips/{trip_id}/delete-preview")
def delete_preview(trip_id: int, db: Session = Db, me: models.User = Me):
    """What deleting this trip removes, and whether anyone still owes money on it."""
    return jsonable_encoder(trash.preview(db, access.trip_or_404(db, trip_id, me), me))


@router.post("/trips/bulk-delete")
def bulk_delete(body: TripIds, db: Session = Db, me: models.User = Me):
    deleted, skipped = [], []
    for tid in dict.fromkeys(body.trip_ids):
        trip = db.get(models.Trip, tid)
        if trip is None or trip.deleted_at is not None or not access.can_see_trip(me, trip):
            skipped.append({"id": tid, "reason": "not_found"})
        elif trip.owner_id != me.id:
            skipped.append({"id": tid, "reason": "not_owner"})
        else:
            deleted.append(delete_one(db, trip, body.permanent))
    return jsonable_encoder({"deleted": deleted, "skipped": skipped, "keep_days": trash.KEEP_DAYS})


@router.post("/trips/{trip_id}/leave", status_code=204)
def leave_trip(trip_id: int, force: bool = False, db: Session = Db, me: models.User = Me):
    """For travelers who aren't the owner: take yourself off the trip (the trip stays)."""
    trip = access.trip_or_404(db, trip_id, me)
    if trip.owner_id == me.id:
        raise HTTPException(status_code=400, detail="You own this trip. Delete it instead.")
    if not force and money.person_net(money.trip_ledger(db, trip), me.id):
        raise HTTPException(status_code=409, detail="You have an unsettled balance on this trip. Settle up first, or pass force=true.")
    trip.participants.remove(me)
    db.commit()


@router.get("/trash/trips")
def list_trash(db: Session = Db, me: models.User = Me):
    return jsonable_encoder({"keep_days": trash.KEEP_DAYS, "trips": trash.trash(db, me)})


@router.post("/trash/trips/{trip_id}/restore", response_model=schemas.Trip)
def restore(trip_id: int, db: Session = Db, me: models.User = Me):
    return trash.restore(db, access.trashed_trip_or_404(db, trip_id, me))


@router.post("/trash/trips/restore")
def bulk_restore(body: TripIds, db: Session = Db, me: models.User = Me):
    restored = []
    for tid in dict.fromkeys(body.trip_ids):
        restored.append(trash.restore(db, access.trashed_trip_or_404(db, tid, me)).id)
    return {"restored": restored}


@router.delete("/trash/trips/{trip_id}", status_code=204)
def delete_now(trip_id: int, db: Session = Db, me: models.User = Me):
    trash.purge(db, access.trashed_trip_or_404(db, trip_id, me))


@router.delete("/trash/trips")
def empty_trash(db: Session = Db, me: models.User = Me):
    rows = db.query(models.Trip).filter(models.Trip.owner_id == me.id, models.Trip.deleted_at.isnot(None)).all()
    for t in rows:
        trash.purge(db, t)
    return {"purged": len(rows)}


# --- Pins (swipe right on a trip: keep it at the top of your own list) ----------------

@router.put("/trips/{trip_id}/pin")
def pin_trip(trip_id: int, db: Session = Db, me: models.User = Me):
    access.trip_or_404(db, trip_id, me)
    if not db.query(models.TripPin).filter(models.TripPin.trip_id == trip_id, models.TripPin.user_id == me.id).first():
        db.add(models.TripPin(trip_id=trip_id, user_id=me.id))
        db.commit()
    return {"trip_id": trip_id, "pinned": True}


@router.delete("/trips/{trip_id}/pin")
def unpin_trip(trip_id: int, db: Session = Db, me: models.User = Me):
    access.trip_or_404(db, trip_id, me)
    db.query(models.TripPin).filter(models.TripPin.trip_id == trip_id, models.TripPin.user_id == me.id).delete()
    db.commit()
    return {"trip_id": trip_id, "pinned": False}
