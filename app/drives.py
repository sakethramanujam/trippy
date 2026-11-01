"""Drives: storing Timeline drives, matching them to trips/journeys/rentals, and the numbers
other features need (story driving days, Driver's Log miles, journey routes).

Drives are private to the account that imported them: every query filters on owner_id.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from . import access, airports, models

TRIP_SLACK = timedelta(days=1)
PICKUP_WINDOW = (timedelta(hours=-1), timedelta(hours=4))    # drive starts this close after pickup
DROPOFF_WINDOW = (timedelta(hours=-4), timedelta(hours=1))   # drive ends this close before dropoff
NEAR_STATION_MILES = 15


def _iso(d: Optional[datetime]) -> Optional[str]:
    return d.isoformat() if d else None


def _loads(text: Optional[str], default):
    try:
        return json.loads(text) if text else default
    except (TypeError, ValueError):
        return default


def own(db: Session, user: models.User):
    return db.query(models.Drive).filter(models.Drive.owner_id == user.id)


def drive_or_404(db: Session, drive_id: int, user: models.User) -> models.Drive:
    d = db.get(models.Drive, drive_id)
    if d is None or d.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Drive not found")
    return d


def to_dict(d: models.Drive, with_path: bool = True) -> dict[str, Any]:
    out = {
        "id": d.id, "trip_id": d.trip_id, "journey_id": d.journey_id, "rental_id": d.rental_id,
        "source": d.source, "start_time": _iso(d.start_time), "end_time": _iso(d.end_time),
        "start_utc_offset": d.start_utc_offset, "end_utc_offset": d.end_utc_offset,
        "date": d.start_time.date().isoformat() if d.start_time else None,
        "distance_miles": round(d.distance_miles or 0, 1), "duration_minutes": d.duration_minutes,
        "start_place": {"name": d.start_name, "lat": d.start_lat, "lng": d.start_lng},
        "end_place": {"name": d.end_name, "lat": d.end_lat, "lng": d.end_lng},
        "stops": _loads(d.stops_json, []),
    }
    if with_path:
        out["path"] = _loads(d.path_json, [])
    return out


# --- trip / journey matching ------------------------------------------------------------------

class Matcher:
    """Which of your trips (or journeys) a drive at `when` belongs to, by date range."""

    def __init__(self, db: Session, user: models.User):
        self.trips = [t for t in access.trips(db, user).filter(models.Trip.deleted_at.is_(None)).all()
                      if t.start_date and t.end_date]
        self.trips.sort(key=lambda t: (t.start_date, t.id))
        self.journeys: list[tuple[models.Journey, date, date]] = []
        for j in db.query(models.Journey).filter(models.Journey.owner_id == user.id).all():
            live = [t for t in j.trips if t.deleted_at is None and t.start_date and t.end_date]
            if live:
                self.journeys.append((j, min(t.start_date for t in live).date(), max(t.end_date for t in live).date()))

    def trip(self, when: Optional[datetime]) -> Optional[models.Trip]:
        if when is None:
            return None
        exact = [t for t in self.trips if t.start_date.date() <= when.date() <= t.end_date.date()]
        if exact:
            return exact[0]
        for t in self.trips:
            if t.start_date.date() - TRIP_SLACK <= when.date() <= t.end_date.date() + TRIP_SLACK:
                return t
        return None

    def journey(self, when: Optional[datetime], trip: Optional[models.Trip]) -> Optional[models.Journey]:
        if trip is not None and trip.journey_id:
            return trip.journey
        if when is None:
            return None
        for j, lo, hi in self.journeys:
            if lo - TRIP_SLACK <= when.date() <= hi + TRIP_SLACK:
                return j
        return None

    def describe(self, when: Optional[datetime]) -> dict:
        t = self.trip(when)
        j = self.journey(when, t)
        return {"trip_id": t.id if t else None, "trip_title": (t.title or "").removesuffix(" (auto)") if t else None,
                "journey_id": j.id if j else None, "journey_title": j.title if j else None}


def annotate_preview(db: Session, user: models.User, items: list[dict], scope: str) -> dict:
    """Adds `match` and `suggested` to drive items. scope="trips" keeps only drives during a trip or
    journey; "all" keeps everything. Returns counts for the preview's stats."""
    m = Matcher(db, user)
    kept, outside = [], 0
    for it in items:
        if it["kind"] != "drive":
            kept.append(it)
            continue
        start = it["fields"].get("start_time")
        it["match"] = m.describe(start)
        it["suggested"] = bool(it["match"]["trip_id"] or it["match"]["journey_id"])
        if not it["suggested"]:
            outside += 1
            if scope == "trips":
                continue
        kept.append(it)
    items[:] = kept
    return {"outside_trips": outside, "scope": scope}


def find_duplicate(db: Session, user: models.User, f: dict) -> Optional[int]:
    q = own(db, user)
    if f.get("external_id") and (hit := q.filter(models.Drive.external_id == f["external_id"]).first()):
        return hit.id
    start = f.get("start_time")
    if isinstance(start, datetime):
        hit = q.filter(models.Drive.start_time >= start - timedelta(minutes=2),
                       models.Drive.start_time <= start + timedelta(minutes=2)).first()
        if hit and abs((hit.distance_miles or 0) - (f.get("distance_miles") or 0)) < 1.0:
            return hit.id
    return None


def create(db: Session, user: models.User, data: dict, trip: Optional[models.Trip],
           matcher: Optional[Matcher]) -> models.Drive:
    sp, ep = data.get("start_place") or {}, data.get("end_place") or {}
    data = {**data, "start_time": data["start_time"].replace(tzinfo=None),
            "end_time": data["end_time"].replace(tzinfo=None)}  # Trippy stores wall-clock times
    journey = None
    if matcher is not None:
        trip = trip or matcher.trip(data["start_time"])
        journey = matcher.journey(data["start_time"], trip)
    elif trip is not None and trip.journey_id:
        journey = trip.journey
    row = models.Drive(
        owner_id=user.id, trip_id=trip.id if trip else None, journey_id=journey.id if journey else None,
        source="google_timeline", external_id=data["external_id"],
        start_time=data["start_time"], end_time=data["end_time"],
        start_utc_offset=data.get("start_utc_offset"), end_utc_offset=data.get("end_utc_offset"),
        distance_miles=data.get("distance_miles") or 0.0, duration_minutes=data.get("duration_minutes"),
        start_name=sp.get("name"), start_lat=sp.get("lat"), start_lng=sp.get("lng"),
        end_name=ep.get("name"), end_lat=ep.get("lat"), end_lng=ep.get("lng"),
        path_json=json.dumps(data.get("path") or []), stops_json=json.dumps(data.get("stops") or []),
    )
    db.add(row)
    db.flush()
    return row


# --- miles (Driver's Log, stories) ------------------------------------------------------------

def _rental_has_miles(r: models.RentalCar) -> bool:
    from .stories import _rental_miles  # local import: stories imports this module
    return bool(_rental_miles(r))


def counted_miles(drives: list[models.Drive], rentals: list[models.RentalCar]) -> float:
    """Timeline miles that aren't already in a rental's odometer/mileage (no double counting):
    a drive linked to, or inside the dates of, a rental with recorded miles is skipped."""
    covered = [(r.pickup_time, r.dropoff_time) for r in rentals
               if r.pickup_time and r.dropoff_time and _rental_has_miles(r)]
    by_id = {r.id: r for r in rentals}
    total = 0.0
    for d in drives:
        r = by_id.get(d.rental_id) if d.rental_id else None
        if r is not None and _rental_has_miles(r):
            continue
        if any(a <= d.start_time <= b for a, b in covered):
            continue
        total += d.distance_miles or 0
    return total


def trip_drives(db: Session, trip: models.Trip, user: models.User) -> list[models.Drive]:
    return own(db, user).filter(models.Drive.trip_id == trip.id).order_by(models.Drive.start_time).all()


def _place(name, lat, lng) -> Optional[dict]:
    if lat is None or lng is None:
        return {"code": None, "city": name, "country": None, "lat": None, "lng": None} if name else None
    code = airports.nearest(lat, lng, max_miles=250)
    hit = airports.lookup(code) if code else None
    city = name if name and not name.startswith("Near ") else (hit[0] if hit else name)
    return {"code": None, "city": city or name, "country": hit[1] if hit else None, "lat": lat, "lng": lng}


def driving_days(drives: list[models.Drive]) -> list[dict]:
    """One story/timeline entry per day you drove: total miles, first start → last end, stops,
    and every drive's path."""
    by_day: dict[date, list[models.Drive]] = defaultdict(list)
    for d in drives:
        by_day[d.start_time.date()].append(d)
    out = []
    for day, rows in sorted(by_day.items()):
        rows.sort(key=lambda d: d.start_time)
        first, last = rows[0], rows[-1]
        miles = sum(d.distance_miles or 0 for d in rows)
        stops = [s for d in rows for s in _loads(d.stops_json, [])]
        for d in rows[:-1]:  # where one drive ends and the next starts is a stop too
            stops.append({"name": d.end_name, "lat": d.end_lat, "lng": d.end_lng, "minutes": None})
        mins = sum(d.duration_minutes or 0 for d in rows)
        out.append({
            "date": day, "start": first.start_time, "end": last.end_time, "miles": miles,
            "minutes": mins, "drives": len(rows), "drive_ids": [d.id for d in rows],
            "from_place": _place(first.start_name, first.start_lat, first.start_lng),
            "place": _place(last.end_name, last.end_lat, last.end_lng),
            "from_name": first.start_name, "to_name": last.end_name,
            "stops": stops[:30],
            "paths": [_loads(d.path_json, []) for d in rows],
        })
    return out


# --- rental match suggestions -------------------------------------------------------------------

def _station(r: models.RentalCar, which: str) -> Optional[tuple[float, float]]:
    lat, lng, code = (r.pickup_lat, r.pickup_lng, r.pickup_code) if which == "pickup" else \
        (r.dropoff_lat, r.dropoff_lng, r.dropoff_code)
    if lat is not None and lng is not None:
        return (lat, lng)
    hit = airports.lookup(code or (r.pickup_location if which == "pickup" else r.dropoff_location))
    return (hit[2], hit[3]) if hit else None


def rental_suggestions(db: Session, user: models.User) -> list[dict]:
    """Drives whose start lines up with a rental pickup (or end with a dropoff), in time and place.
    Suggestions only: nothing is linked until you accept one."""
    rentals = [r for r in access.rentals(db, user).all() if r.pickup_time and r.owner_id in (None, user.id)]
    drives = own(db, user).filter(models.Drive.rental_id.is_(None)).order_by(models.Drive.start_time).all()
    out = []
    for d in drives:
        dismissed = set(_loads(d.dismissed_rentals_json, []))
        for r in rentals:
            if r.id in dismissed:
                continue
            for which, when, window, here in (
                ("pickup", r.pickup_time, PICKUP_WINDOW, (d.start_lat, d.start_lng)),
                ("dropoff", r.dropoff_time, DROPOFF_WINDOW, (d.end_lat, d.end_lng)),
            ):
                if not when or here[0] is None:
                    continue
                t = d.start_time if which == "pickup" else d.end_time
                if not (when + window[0] <= t <= when + window[1]):
                    continue
                st = _station(r, which)
                if st is None:
                    continue
                miles = airports.haversine_miles(here[0], here[1], st[0], st[1])
                if miles > NEAR_STATION_MILES:
                    continue
                gap = int(abs((t - when).total_seconds()) // 60)
                verb = "starts" if which == "pickup" else "ends"
                out.append({
                    "drive_id": d.id, "rental_id": r.id, "match": which,
                    "reason": f"Drive {verb} {miles:.1f} mi from the {which} station, {gap} min "
                              f"{'after' if t >= when else 'before'} {which}",
                    "drive": to_dict(d, with_path=False),
                    "rental": {"id": r.id, "company": r.rental_company, "car": r.car_model,
                               "pickup_time": _iso(r.pickup_time), "dropoff_time": _iso(r.dropoff_time),
                               "pickup_location": r.pickup_location, "dropoff_location": r.dropoff_location},
                })
                break
    return out


def link_rental(db: Session, user: models.User, d: models.Drive, rental_id: Optional[int]) -> models.Drive:
    if rental_id is None:
        d.rental_id = None
    else:
        r = db.get(models.RentalCar, rental_id)
        if r is None or not access.rentals(db, user).filter(models.RentalCar.id == rental_id).first():
            raise HTTPException(status_code=404, detail="Rental not found")
        d.rental_id = r.id
        if d.trip_id is None and r.trip_id is not None:
            d.trip_id = r.trip_id
    db.commit()
    return d


def dismiss_rental(db: Session, d: models.Drive, rental_id: int) -> None:
    ids = set(_loads(d.dismissed_rentals_json, []))
    ids.add(int(rental_id))
    d.dismissed_rentals_json = json.dumps(sorted(ids))
    db.commit()
