"""Trip photos (thumbnails only; see app/photos.py)."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import access, models, photos
from .auth import get_current_user
from .database import get_db

router = APIRouter(tags=["photos"])
Me = Depends(get_current_user)
Db = Depends(get_db)


class PhotoIn(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=100)
    asset_id: str = Field(..., min_length=1, max_length=300)
    taken_at: Optional[datetime] = None
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lng: Optional[float] = Field(default=None, ge=-180, le=180)
    thumb_base64: str = Field(..., min_length=4, max_length=400_000)


@router.get("/trips/{trip_id}/photos")
def list_photos(trip_id: int, device_id: Optional[str] = None, db: Session = Db, me: models.User = Me) -> List[dict]:
    """Your photos on this trip (oldest first). `device_id` narrows to one device's photos."""
    access.trip_or_404(db, trip_id, me)
    q = photos.own(db, me, trip_id)
    if device_id:
        q = q.filter(models.TripPhoto.device_id == device_id)
    return [photos.to_dict(p) for p in q.order_by(models.TripPhoto.taken_at, models.TripPhoto.id).all()]


@router.post("/trips/{trip_id}/photos")
def add_photo(trip_id: int, body: PhotoIn, response: Response, db: Session = Db, me: models.User = Me):
    trip = access.trip_or_404(db, trip_id, me)
    p, created = photos.add(db, trip, me, body)
    response.status_code = 201 if created else 200
    return photos.to_dict(p)


@router.get("/photos/{photo_id}/thumb")
def get_thumb(photo_id: int, db: Session = Db, me: models.User = Me):
    p = photos.photo_or_404(db, photo_id, me)
    return Response(content=p.thumb, media_type="image/jpeg",
                    headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"})


@router.delete("/photos/{photo_id}", status_code=204)
def delete_photo(photo_id: int, db: Session = Db, me: models.User = Me):
    db.delete(photos.photo_or_404(db, photo_id, me))
    db.commit()
    return Response(status_code=204)
