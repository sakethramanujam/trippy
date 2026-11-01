"""Trip photos: thumbnails only. Full-size photos stay on the device they came from.

The apps suggest photos taken during a trip (by date taken, and location when the photo has it); you
accept the ones you want, and the app uploads a ≤512 px JPEG thumbnail with the device's asset id.
Thumbnails are private to whoever added them and go away with the trip."""
from __future__ import annotations

import base64
import binascii
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from . import models

MAX_SIDE = 512
MAX_BYTES = 256 * 1024
MAX_PER_TRIP = 500


def jpeg_size(data: bytes) -> Optional[tuple[int, int]]:
    """(width, height) from a JPEG's SOF header, or None if it isn't a JPEG we can read."""
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return None
    i = 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        if marker == 0xFF:  # fill byte
            i += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg = int.from_bytes(data[i + 2:i + 4], "big")
        if seg < 2:
            return None
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            if i + 9 > len(data):
                return None
            h = int.from_bytes(data[i + 5:i + 7], "big")
            w = int.from_bytes(data[i + 7:i + 9], "big")
            return (w, h) if w and h else None
        if marker in (0xD9, 0xDA):  # end / start of scan before any frame header
            return None
        i += 2 + seg
    return None


def decode_thumb(b64: str) -> tuple[bytes, int, int]:
    try:
        data = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=422, detail="thumb_base64 isn't valid base64")
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"Thumbnail is over {MAX_BYTES // 1024} KB")
    size = jpeg_size(data)
    if not size:
        raise HTTPException(status_code=422, detail="Thumbnail must be a JPEG")
    w, h = size
    if max(w, h) > MAX_SIDE:
        raise HTTPException(status_code=422, detail=f"Thumbnail must be at most {MAX_SIDE} px on its longest side")
    return data, w, h


def own(db: Session, user: models.User, trip_id: Optional[int] = None):
    q = db.query(models.TripPhoto).filter(models.TripPhoto.user_id == user.id)
    if trip_id is not None:
        q = q.filter(models.TripPhoto.trip_id == trip_id)
    return q


def photo_or_404(db: Session, photo_id: int, user: models.User) -> models.TripPhoto:
    p = db.get(models.TripPhoto, photo_id)
    if p is None or p.user_id != user.id or p.trip is None or p.trip.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Photo not found")
    return p


def to_dict(p: models.TripPhoto) -> dict:
    return {"id": p.id, "trip_id": p.trip_id, "device_id": p.device_id, "asset_id": p.asset_id,
            "taken_at": p.taken_at.isoformat() if p.taken_at else None, "lat": p.lat, "lng": p.lng,
            "width": p.width, "height": p.height, "thumb_url": f"/photos/{p.id}/thumb"}


def add(db: Session, trip: models.Trip, user: models.User, body) -> tuple[models.TripPhoto, bool]:
    """Add (or refresh) a photo; returns (photo, created). The same asset from the same device is one photo."""
    data, w, h = decode_thumb(body.thumb_base64)
    taken = body.taken_at.replace(tzinfo=None) if body.taken_at else None
    p = own(db, user, trip.id).filter(models.TripPhoto.device_id == body.device_id,
                                      models.TripPhoto.asset_id == body.asset_id).first()
    created = p is None
    if created:
        if own(db, user, trip.id).count() >= MAX_PER_TRIP:
            raise HTTPException(status_code=409, detail=f"A trip can have up to {MAX_PER_TRIP} photos")
        p = models.TripPhoto(trip_id=trip.id, user_id=user.id, device_id=body.device_id, asset_id=body.asset_id)
        db.add(p)
    p.taken_at, p.lat, p.lng, p.width, p.height, p.thumb = taken, body.lat, body.lng, w, h, data
    db.commit()
    db.refresh(p)
    return p, created


def delete_for_trip(db: Session, trip_id: int, user_id: Optional[int] = None) -> None:
    q = db.query(models.TripPhoto).filter(models.TripPhoto.trip_id == trip_id)
    if user_id is not None:
        q = q.filter(models.TripPhoto.user_id == user_id)
    q.delete(synchronize_session=False)


def move(db: Session, source_id: int, target_id: int) -> int:
    """Merge: move photos to the target trip; one that's already there (same asset) is dropped."""
    n = 0
    for p in db.query(models.TripPhoto).filter(models.TripPhoto.trip_id == source_id).all():
        dup = db.query(models.TripPhoto).filter_by(trip_id=target_id, user_id=p.user_id, device_id=p.device_id,
                                                   asset_id=p.asset_id).first()
        if dup:
            db.delete(p)
        else:
            p.trip_id = target_id
            n += 1
    db.flush()
    return n


def story_photos(db: Session, trip: models.Trip, user: models.User, items: list[dict], start: Optional[datetime]) -> list[dict]:
    """Your photos for a story, each tagged with its trip day and the item on that day it belongs to."""
    rows = own(db, user, trip.id).order_by(models.TripPhoto.taken_at).all()
    dated = [i for i in items if i.get("date") and i.get("kind") != "travelers"]
    out = []
    for p in rows:
        d = to_dict(p)
        d["day"] = (p.taken_at.date() - start.date()).days + 1 if p.taken_at and start else None
        d["item_key"] = None
        if p.taken_at:
            for i in dated:
                a = datetime.fromisoformat(i["date"]).date()
                b = datetime.fromisoformat(i["end_date"]).date() if i.get("end_date") else a
                if a <= p.taken_at.date() <= b and (d["item_key"] is None or i["kind"] != "lodging"):
                    d["item_key"] = i["key"]
        out.append(d)
    return out
