"""Journeys (linked trips), trip merge, moving items between trips, and link suggestions."""
from __future__ import annotations

from datetime import datetime

from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import access, journeys, models, schemas
from .auth import get_current_user
from .database import get_db

router = APIRouter(tags=["journeys"])
Me = Depends(get_current_user)
Db = Depends(get_db)


class JourneyCreate(BaseModel):
    title: Optional[str] = Field(None, max_length=120)
    description: Optional[str] = Field(None, max_length=1000)
    cover_photo: Optional[str] = Field(None, max_length=200)
    trip_ids: List[int] = Field(default_factory=list, max_length=200)


class JourneyUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=120)
    description: Optional[str] = Field(None, max_length=1000)
    cover_photo: Optional[str] = Field(None, max_length=200)


class TripIds(BaseModel):
    trip_ids: List[int] = Field(..., min_length=1, max_length=200)


class MergeRequest(BaseModel):
    source_trip_id: int
    confirm: bool = False


class MoveItem(BaseModel):
    kind: Literal["flight", "rental", "lodging", "stay", "expense"]
    id: int


class MoveRequest(BaseModel):
    trip_id: Optional[int] = None  # None takes flights/rentals/stays off their trip
    items: List[MoveItem] = Field(..., min_length=1, max_length=500)


@router.get("/journeys/")
def list_journeys(db: Session = Db, me: models.User = Me):
    return [journeys.summary(db, j, me) for j in journeys.visible_journeys(db, me)]


@router.post("/journeys/", status_code=201)
def create_journey(body: JourneyCreate, db: Session = Db, me: models.User = Me):
    j = journeys.create(db, me, body.title, body.trip_ids, body.description, body.cover_photo)
    return jsonable_encoder(journeys.detail(db, j, me))


@router.get("/journeys/suggestions")
def journey_suggestions(include_dismissed: bool = False, db: Session = Db, me: models.User = Me):
    return journeys.suggestions(db, me, include_dismissed)


@router.post("/journeys/suggestions/dismiss")
def dismiss_suggestion(body: TripIds, db: Session = Db, me: models.User = Me):
    for tid in body.trip_ids:
        access.owned_trip_or_404(db, tid, me)
    return {"key": journeys.dismiss(db, me, body.trip_ids)}


@router.post("/journeys/title")
def suggest_title(body: TripIds, db: Session = Db, me: models.User = Me):
    """A title for a new journey made of these trips (\"Lisbon → Porto → Madrid\")."""
    trips = [access.trip_or_404(db, t, me) for t in body.trip_ids]
    return {"title": journeys.suggested_title(db, me, trips)}


@router.get("/journeys/{journey_id}")
def get_journey(journey_id: int, db: Session = Db, me: models.User = Me):
    return jsonable_encoder(journeys.detail(db, journeys.journey_or_404(db, journey_id, me), me))


@router.patch("/journeys/{journey_id}")
def update_journey(journey_id: int, body: JourneyUpdate, db: Session = Db, me: models.User = Me):
    j = journeys.owned_journey_or_404(db, journey_id, me)
    for k, v in body.model_dump(exclude_unset=True).items():
        if k == "title" and v is not None:
            v = v.strip()
        setattr(j, k, v)
    db.commit()
    db.refresh(j)
    return jsonable_encoder(journeys.detail(db, j, me))


@router.delete("/journeys/{journey_id}")
def delete_journey(journey_id: int, delete_trips: bool = False, db: Session = Db, me: models.User = Me):
    """Deletes the journey. By default its trips are unlinked and kept as they are.
    delete_trips=true also moves your trips in it to Recently Deleted (30 days, restorable)."""
    j = journeys.owned_journey_or_404(db, journey_id, me)
    ids = [t.id for t in j.trips if t.deleted_at is None]
    if not delete_trips:
        journeys.delete(db, j)
        return {"ok": True, "unlinked_trip_ids": ids, "deleted_trip_ids": []}
    from . import trash
    mine = [t for t in j.trips if t.deleted_at is None and t.owner_id == me.id]
    now = datetime.utcnow()
    for t in mine:
        trash.soft_delete(db, t, now=now)  # the last one deletes the journey
    db.commit()
    if db.get(models.Journey, journey_id) is not None:  # someone else's trips were left in it
        journeys.delete(db, db.get(models.Journey, journey_id))
    return {"ok": True, "unlinked_trip_ids": [i for i in ids if i not in {t.id for t in mine}],
            "deleted_trip_ids": [t.id for t in mine]}


@router.post("/journeys/{journey_id}/trips")
def add_trips(journey_id: int, body: TripIds, db: Session = Db, me: models.User = Me):
    j = journeys.owned_journey_or_404(db, journey_id, me)
    return jsonable_encoder(journeys.detail(db, journeys.add_trips(db, j, me, body.trip_ids), me))


@router.delete("/journeys/{journey_id}/trips/{trip_id}")
def remove_trip(journey_id: int, trip_id: int, db: Session = Db, me: models.User = Me):
    j = journeys.owned_journey_or_404(db, journey_id, me)
    return jsonable_encoder(journeys.detail(db, journeys.remove_trip(db, j, me, trip_id), me))


@router.put("/journeys/{journey_id}/order")
def reorder(journey_id: int, body: TripIds, db: Session = Db, me: models.User = Me):
    j = journeys.owned_journey_or_404(db, journey_id, me)
    return jsonable_encoder(journeys.detail(db, journeys.reorder(db, j, body.trip_ids), me))


@router.get("/journeys/{journey_id}/story")
def journey_story(journey_id: int, db: Session = Db, me: models.User = Me):
    return jsonable_encoder(journeys.story(db, journeys.journey_or_404(db, journey_id, me), me))


@router.post("/trips/{trip_id}/merge", response_model=schemas.Trip)
def merge_trips(trip_id: int, body: MergeRequest, db: Session = Db, me: models.User = Me):
    """Destructive: moves everything from source_trip_id into this trip and deletes the source."""
    target = access.owned_trip_or_404(db, trip_id, me)
    source = access.owned_trip_or_404(db, body.source_trip_id, me)
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Merging deletes the other trip. Send confirm: true.")
    journeys.merge(db, target, source)
    return target


@router.post("/items/move")
def move_items(body: MoveRequest, db: Session = Db, me: models.User = Me):
    return journeys.move_items(db, me, body.trip_id, [i.model_dump() for i in body.items])
