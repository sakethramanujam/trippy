"""Trip stories (GET/PUT/DELETE /trips/{id}/story) and Year in Travel (GET /stories/year)."""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from . import access, models, stories
from .auth import get_current_user
from .database import get_db

router = APIRouter(tags=["stories"])
Me = Depends(get_current_user)

PhotoId = str


class StoryItemEdit(BaseModel):
    hidden: bool = False
    note: Optional[str] = Field(default=None, max_length=stories.MAX_NOTE)
    photos: List[PhotoId] = Field(default_factory=list, max_length=stories.MAX_PHOTOS)

    @field_validator("photos")
    @classmethod
    def _ids(cls, v: List[str]) -> List[str]:
        for p in v:
            if not p or len(p) > 64 or not all(ch.isalnum() or ch in "-_." for ch in p):
                raise ValueError("photo ids are 1-64 letters, digits, '-', '_' or '.'")
        return v


class StoryEdit(BaseModel):
    title: Optional[str] = Field(default=None, max_length=stories.MAX_TITLE)
    subtitle: Optional[str] = Field(default=None, max_length=stories.MAX_TITLE)
    theme: Optional[Literal[stories.THEMES]] = None  # type: ignore[valid-type]
    cover_photo: Optional[PhotoId] = Field(default=None, max_length=64)
    order: Optional[List[str]] = Field(default=None, max_length=1000)
    items: Optional[Dict[str, StoryItemEdit]] = None


@router.get("/trips/{trip_id}/story")
def get_story(trip_id: int, user: models.User = Me, db: Session = Depends(get_db)):
    """The trip's story with your edits applied (each traveler keeps their own version)."""
    trip = access.trip_or_404(db, trip_id, user)
    return stories.build(db, trip, user)


@router.put("/trips/{trip_id}/story")
def put_story(trip_id: int, body: StoryEdit, user: models.User = Me, db: Session = Depends(get_db)):
    """Save your edits. Omitted fields keep their saved value; `items` and `order` replace."""
    trip = access.trip_or_404(db, trip_id, user)
    data = body.model_dump(exclude_unset=True)
    if body.items is not None:
        data["items"] = {k: v.model_dump() for k, v in body.items.items()}
    return stories.save(db, trip, user, data)


@router.delete("/trips/{trip_id}/story")
def reset_story(trip_id: int, user: models.User = Me, db: Session = Depends(get_db)):
    """Throw away your edits and go back to the generated story."""
    trip = access.trip_or_404(db, trip_id, user)
    return stories.reset(db, trip, user)


@router.get("/stories/year")
def year_in_travel(year: Optional[int] = Query(default=None, ge=1990, le=2100),
                   user: models.User = Me, db: Session = Depends(get_db)):
    return stories.year_in_travel(db, user, year or datetime.utcnow().year)
