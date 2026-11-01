"""/drives: your imported Timeline drives (see IMPORTERS.md → Google Maps Timeline)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from . import access, drives, models, schemas
from .auth import get_current_user
from .database import get_db

router = APIRouter(tags=["drives"])
Me = Depends(get_current_user)
Db = Depends(get_db)


@router.get("/drives")
def list_drives(trip_id: Optional[int] = None, journey_id: Optional[int] = None,
                year: Optional[int] = Query(default=None, ge=1990, le=2100), with_path: bool = True,
                db: Session = Db, me: models.User = Me):
    q = drives.own(db, me)
    if trip_id is not None:
        q = q.filter(models.Drive.trip_id == trip_id)
    if journey_id is not None:
        trip_ids = [t.id for t in db.query(models.Trip).filter(models.Trip.journey_id == journey_id).all()]
        q = q.filter((models.Drive.journey_id == journey_id) | (models.Drive.trip_id.in_(trip_ids or [-1])))
    if year is not None:
        q = q.filter(models.Drive.start_time >= datetime(year, 1, 1), models.Drive.start_time < datetime(year + 1, 1, 1))
    return [drives.to_dict(d, with_path=with_path) for d in q.order_by(models.Drive.start_time).all()]


@router.get("/drives/rental-suggestions")
def rental_suggestions(db: Session = Db, me: models.User = Me):
    return drives.rental_suggestions(db, me)


@router.get("/drives/{drive_id}")
def get_drive(drive_id: int, db: Session = Db, me: models.User = Me):
    return drives.to_dict(drives.drive_or_404(db, drive_id, me))


@router.patch("/drives/{drive_id}")
def update_drive(drive_id: int, body: schemas.DriveUpdate, db: Session = Db, me: models.User = Me):
    d = drives.drive_or_404(db, drive_id, me)
    if body.clear_trip:
        d.trip_id = None
    elif body.trip_id is not None:
        trip = access.trip_or_404(db, body.trip_id, me)
        d.trip_id = trip.id
        d.journey_id = trip.journey_id or d.journey_id
    db.commit()
    return drives.to_dict(d)


@router.post("/drives/{drive_id}/rental")
def link_rental(drive_id: int, body: schemas.DriveRentalLink, db: Session = Db, me: models.User = Me):
    d = drives.drive_or_404(db, drive_id, me)
    return drives.to_dict(drives.link_rental(db, me, d, body.rental_id))


@router.post("/drives/{drive_id}/rental/dismiss", status_code=204)
def dismiss_rental(drive_id: int, body: schemas.DriveRentalLink, db: Session = Db, me: models.User = Me):
    d = drives.drive_or_404(db, drive_id, me)
    if body.rental_id is None:
        raise HTTPException(status_code=400, detail="rental_id is required")
    drives.dismiss_rental(db, d, body.rental_id)


@router.delete("/drives/{drive_id}", status_code=204)
def delete_drive(drive_id: int, db: Session = Db, me: models.User = Me):
    d = drives.drive_or_404(db, drive_id, me)
    db.delete(d)
    db.commit()
