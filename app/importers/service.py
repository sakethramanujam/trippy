"""Preview → de-duplicate → commit, shared by every importer."""
from __future__ import annotations

import base64
import binascii
from datetime import datetime, timedelta
from typing import Optional

from pydantic import ValidationError
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import access, drives, models, schemas
from . import csv_generic, emails, flighty, google_timeline, ics, pkpass
from .common import KINDS, ImportError_, flight_key

SOURCES = ("ics", "ics_url", "flighty_csv", "pkpass", "email", "csv", "google_timeline")
MAX_UPLOAD = 5 * 1024 * 1024
MAX_TIMELINE_UPLOAD = 20 * 1024 * 1024  # Timeline exports are big; the apps strip rawSignals first
MAX_DRIVES = 2000
MAX_ITEMS = 2000


def decode_payload(text: Optional[str], data_base64: Optional[str], limit: int = MAX_UPLOAD) -> bytes:
    mb = limit // (1024 * 1024)
    if data_base64:
        if len(data_base64) > limit * 4 // 3 + 8:
            raise ImportError_(f"That file is larger than {mb} MB")
        try:
            return base64.b64decode(data_base64, validate=False)
        except (binascii.Error, ValueError):
            raise ImportError_("The file data isn't valid base64")
    if text:
        if len(text) > limit:
            raise ImportError_(f"That text is larger than {mb} MB")
        return text.encode("utf-8")
    raise ImportError_("Send a file or paste some text")


def run_parser(source: str, data: bytes, filename: str, csv_kind: str, mapping: Optional[dict],
               timezone: Optional[str] = None) -> dict:
    """Returns {items, stats} or, for a generic CSV without a mapping, {columns, …}."""
    if source in ("ics", "ics_url"):
        items, stats = ics.parse_ics(data, source="ics")
    elif source == "flighty_csv":
        items, stats = flighty.parse_flighty_csv(data)
    elif source == "pkpass":
        items, stats = pkpass.parse_pkpass(data)
    elif source == "email":
        items, stats = emails.parse_email(data, filename or "pasted.txt")
    elif source == "google_timeline":
        items, stats = google_timeline.parse_timeline(data, timezone)
    elif source == "csv":
        if not mapping:
            return {"needs_mapping": True, **csv_generic.describe(data, csv_kind), "items": [], "stats": {}}
        items, stats = csv_generic.parse_csv(data, csv_kind, mapping)
    else:
        raise ImportError_("Unknown import type")
    if len(items) > MAX_ITEMS:
        raise ImportError_(f"That file has more than {MAX_ITEMS} items ({len(items)}); split it into smaller batches")
    return {"needs_mapping": False, "items": items, "stats": stats}


# --- de-duplication -----------------------------------------------------------

def _same_day(a: Optional[datetime], b: Optional[datetime]) -> bool:
    return bool(a and b and a.date() == b.date())


def find_duplicate(db: Session, me: models.User, kind: str, f: dict) -> Optional[int]:
    """Id of an existing record you can see that is the same booking, or None. Bookings on trips in
    Recently Deleted count too, so a deleted trip's flights aren't imported again."""
    ext = f.get("external_id")
    conf = (f.get("confirmation_number") or "").strip().upper()
    if kind == "drive":
        return drives.find_duplicate(db, me, f)
    if kind == "flight":
        q = access.flights(db, me, include_trashed=True)
        if ext and (hit := q.filter(models.Flight.external_id == ext).first()):
            return hit.id
        dep = f.get("departure_time")
        if not dep:
            return None
        lo, hi = datetime(dep.year, dep.month, dep.day), datetime(dep.year, dep.month, dep.day) + timedelta(days=1)
        same_day = q.filter(models.Flight.departure_time >= lo, models.Flight.departure_time < hi).all()
        key = flight_key(f.get("flight_number", ""))
        for fl in same_day:
            same_origin = not f.get("departure_airport") or not fl.departure_airport or \
                fl.departure_airport.upper() == f["departure_airport"].upper()
            if key and flight_key(fl.flight_number) == key and same_origin:  # one number can fly 2 legs a day
                return fl.id
            if (fl.departure_airport or "").upper() == (f.get("departure_airport") or "").upper() and \
               (fl.arrival_airport or "").upper() == (f.get("arrival_airport") or "").upper():
                return fl.id
        return None
    if kind == "rental":
        q = access.rentals(db, me, include_trashed=True)
        if ext and (hit := q.filter(models.RentalCar.external_id == ext).first()):
            return hit.id
        if conf and (hit := q.filter(func.upper(models.RentalCar.confirmation_number) == conf).first()):
            return hit.id
        for r in q.filter(func.lower(models.RentalCar.rental_company) == (f.get("rental_company") or "").lower()).all():
            if _same_day(r.pickup_time, f.get("pickup_time")):
                return r.id
        return None
    if kind == "lodging":
        q = access.lodgings(db, me, include_trashed=True)
        if ext and (hit := q.filter(models.Lodging.external_id == ext).first()):
            return hit.id
        if conf and (hit := q.filter(func.upper(models.Lodging.confirmation_number) == conf).first()):
            return hit.id
        for l in q.filter(func.lower(models.Lodging.name) == (f.get("name") or "").lower()).all():
            if _same_day(l.check_in, f.get("check_in")):
                return l.id
        return None
    return None


def in_trash(db: Session, kind: str, row_id: Optional[int]) -> bool:
    """Is this booking on a trip in Recently Deleted?"""
    model = {"flight": models.Flight, "rental": models.RentalCar, "lodging": models.Lodging}.get(kind)
    row = db.get(model, row_id) if model and row_id else None
    return bool(row and row.trip and row.trip.deleted_at is not None)


def dup_reason(db: Session, kind: str, row_id: Optional[int]) -> str:
    return "deleted" if in_trash(db, kind, row_id) else "duplicate"


def _batch_key(kind: str, f: dict) -> tuple:
    if kind == "drive":
        return (kind, "ext", f.get("external_id"))
    if f.get("external_id"):
        return (kind, "ext", f["external_id"])
    if kind == "flight":
        d = f.get("departure_time")
        return (kind, flight_key(f.get("flight_number", "")), (f.get("departure_airport") or "").upper(), d.date() if d else None)
    if kind == "rental":
        d = f.get("pickup_time")
        return (kind, (f.get("rental_company") or "").lower(), d.date() if d else None)
    d = f.get("check_in")
    return (kind, (f.get("name") or "").lower(), d.date() if d else None)


def mark_duplicates(db: Session, me: models.User, items: list[dict]) -> list[dict]:
    seen: dict[tuple, int] = {}
    for i, it in enumerate(items):
        it["index"] = i
        it["duplicate_of"] = None
        it["duplicate_in_batch"] = None
        existing = find_duplicate(db, me, it["kind"], it["fields"])
        if existing:
            it["duplicate_of"] = {"kind": it["kind"], "id": existing, "in_trash": in_trash(db, it["kind"], existing)}
        key = _batch_key(it["kind"], it["fields"])
        if key in seen:
            it["duplicate_in_batch"] = seen[key]
        else:
            seen[key] = i
    return items


# --- commit -------------------------------------------------------------------

def _start(kind: str, f: dict) -> Optional[datetime]:
    return f.get({"flight": "departure_time", "rental": "pickup_time", "lodging": "check_in",
                  "drive": "start_time"}[kind])


def trip_for(db: Session, me: models.User, when: Optional[datetime]) -> Optional[models.Trip]:
    """A visible trip whose dates cover `when` (one day of slack either side)."""
    if when is None:
        return None
    for t in access.trips(db, me).order_by(models.Trip.start_date).all():
        if t.start_date and t.end_date and \
           t.start_date.date() - timedelta(days=1) <= when.date() <= t.end_date.date() + timedelta(days=1):
            return t
    return None


def validate(kind: str, fields: dict) -> dict:
    """Run the fields through the API's own schemas (no extra keys reach the DB)."""
    if kind not in KINDS:
        raise ImportError_(f"Unknown item kind {kind!r}")
    extra = {"external_id": fields.get("external_id")}
    fields = {k: v for k, v in fields.items() if v is not None}
    try:
        if kind == "drive":
            return schemas.DriveImport(**fields).model_dump()
        if kind == "flight":
            data = schemas.FlightCreate(**{k: v for k, v in fields.items() if k in schemas.FlightCreate.model_fields}).model_dump()
            data.pop("trip_id", None)
        elif kind == "rental":
            data = schemas.RentalCarBase(**{k: v for k, v in fields.items() if k in schemas.RentalCarBase.model_fields}).model_dump()
        else:
            data = schemas.LodgingBase(**{k: v for k, v in fields.items() if k in schemas.LodgingBase.model_fields}).model_dump()
    except ValidationError as exc:
        first = exc.errors()[0]
        raise ImportError_(f"{kind}: {'.'.join(str(p) for p in first['loc'])} {first['msg']}")
    if kind != "rental":
        data.update(extra)
    return data


def commit(db: Session, me: models.User, items: list[dict], trip_id: Optional[int], auto_trip: bool) -> dict:
    fixed_trip = access.trip_or_404(db, trip_id, me) if trip_id else None
    created, skipped = [], []
    seen: set[tuple] = set()
    matcher = drives.Matcher(db, me) if auto_trip and not fixed_trip else None
    for i, it in enumerate(items):
        kind = it.get("kind")
        data = validate(kind, it.get("fields") or {})
        key = _batch_key(kind, data)
        dup = find_duplicate(db, me, kind, data)
        if dup or key in seen:
            skipped.append({"index": i, "kind": kind, "duplicate_of": dup, "reason": dup_reason(db, kind, dup)})
            continue
        seen.add(key)
        if kind == "drive":
            row = drives.create(db, me, data, fixed_trip, matcher)
            created.append({"index": i, "kind": kind, "id": row.id, "trip_id": row.trip_id,
                            "journey_id": row.journey_id})
            continue
        trip = fixed_trip or (trip_for(db, me, _start(kind, data)) if auto_trip else None)
        model = {"flight": models.Flight, "rental": models.RentalCar, "lodging": models.Lodging}[kind]
        row = model(**data, owner_id=me.id, trip_id=trip.id if trip else None)
        db.add(row)
        db.flush()
        created.append({"index": i, "kind": kind, "id": row.id, "trip_id": row.trip_id})
    db.commit()
    return {"created": created, "skipped": skipped}
