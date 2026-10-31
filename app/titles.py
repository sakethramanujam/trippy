"""Route titles for auto-generated trips ("… (auto)", "… (flights)", "… (email)").

The title lists every place the trip visits, in time order: flights by airport city, rental
pickups and drop-offs, and hotel cities. A trip whose title the user set (title_auto false)
is never touched.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from . import airports, models

AUTO_SUFFIXES = ("(auto)", "(flights)", "(email)")
_SUFFIX_RE = re.compile(r"\s*\((auto|flights|email)\)\s*$")
MAX_PLACES = 4


def is_auto_title(title: Optional[str]) -> bool:
    return bool(_SUFFIX_RE.search(title or ""))


def _suffix(title: str) -> str:
    m = _SUFFIX_RE.search(title or "")
    return f" ({m.group(1)})" if m else " (auto)"


NEAR_MILES = 50  # an airport and a town this close are one place (fly into PHX, stay in Tempe)
_STATE_RE = re.compile(r",\s*[A-Z]{2}$")


def _airport(code: Optional[str]):
    hit = airports.lookup(code)
    return (hit[0], hit[2], hit[3]) if hit else None


def _airport_city(code: Optional[str]) -> Optional[str]:
    hit = _airport(code)
    return hit[0] if hit else None


def _clean(name: Optional[str]) -> Optional[str]:
    name = _STATE_RE.sub("", (name or "").strip()).strip()  # "Tempe, AZ" -> "Tempe"
    return name or None


class _Stop:
    def __init__(self, when: datetime, order: int, name: str, lat=None, lng=None, airport=False):
        self.when, self.order, self.name, self.lat, self.lng, self.airport = when, order, name, lat, lng, airport

    def near(self, other: "_Stop") -> bool:
        if self.name.lower() == other.name.lower():
            return True
        if not (self.airport or other.airport):
            return False  # two towns are two places, however close (Tempe → Phoenix)
        if None in (self.lat, self.lng, other.lat, other.lng):
            return False
        return airports.haversine_miles(self.lat, self.lng, other.lat, other.lng) <= NEAR_MILES


def _stops(trip: models.Trip) -> list[_Stop]:
    out: list[_Stop] = []

    def at_airport(when, order, code):
        a = _airport(code)
        if when and a:
            out.append(_Stop(when, order, a[0], a[1], a[2], airport=True))

    def at_place(when, order, name, lat, lng, code=None):
        name = _clean(name)
        a = _airport(code)
        if lat is None and a:
            lat, lng = a[1], a[2]
        if when and (name or a):
            out.append(_Stop(when, order, name or a[0], lat, lng, airport=not name))

    flights = sorted((f for f in trip.flights or [] if f.departure_time), key=lambda f: f.departure_time)
    for i, f in enumerate(flights):
        nxt = flights[i + 1] if i + 1 < len(flights) else None
        prev = flights[i - 1] if i else None
        if not _layover(prev, f):
            at_airport(f.departure_time, 0, f.departure_airport)
        if not _layover(f, nxt):
            at_airport(f.arrival_time or f.departure_time, 1, f.arrival_airport)
    for r in trip.rental_cars or []:
        at_place(r.pickup_time, 0, r.pickup_city, r.pickup_lat, r.pickup_lng, r.pickup_code)
        at_place(r.dropoff_time or r.pickup_time, 1, r.dropoff_city, r.dropoff_lat, r.dropoff_lng, r.dropoff_code)
    for h in trip.lodgings or []:
        if (h.status or "") != "cancelled":
            at_place(h.check_in, 2, h.city, h.lat, h.lng)
    out.sort(key=lambda s: (s.when, s.order))
    return out


LAYOVER = timedelta(hours=8)


def _layover(arriving, leaving) -> bool:
    """A connection: the next flight leaves the same airport within a few hours."""
    if arriving is None or leaving is None:
        return False
    same = (arriving.arrival_airport or "").upper() == (leaving.departure_airport or "").upper() != ""
    landed = arriving.arrival_time or arriving.departure_time
    return same and landed is not None and timedelta(0) <= leaving.departure_time - landed <= LAYOVER


def _groups(stops: list[_Stop]) -> list[list[_Stop]]:
    groups: list[list[_Stop]] = []
    for s in stops:
        if groups and any(s.near(g) for g in groups[-1]):
            groups[-1].append(s)
        else:
            groups.append([s])
    return groups


def _name(group: list[_Stop]) -> str:
    """The town you were in rather than the airport you flew into."""
    return next((s.name for s in group if not s.airport), group[0].name)


def route_places(trip: models.Trip, home: Optional[_Stop] = None) -> list[str]:
    """Places in visit order: nearby stops merged, a round trip's return and home dropped."""
    groups = _groups(_stops(trip))

    def flown_from_home(g):  # only the home airport: nothing happened there on this trip
        return home is not None and all(s.airport for s in g) and any(home.near(s) for s in g)

    if len(groups) > 1 and flown_from_home(groups[0]):
        groups = groups[1:]
    if len(groups) > 1 and flown_from_home(groups[-1]):
        groups = groups[:-1]
    names: list[str] = []
    kept: list[list[_Stop]] = []
    for g in groups:  # each place once: A → B → A reads as A → B
        if not any(a.near(b) for k in kept for a in k for b in g):
            kept.append(g)
            names.append(_name(g))
    return names


def route_title(trip: models.Trip, home: Optional[_Stop] = None) -> Optional[str]:
    """None when nothing on the trip names a place (keep the current title)."""
    places = route_places(trip, home)
    if not places:
        return None
    name = " → ".join(places[:MAX_PLACES])
    if len(places) > MAX_PLACES:
        name += f" +{len(places) - MAX_PLACES}"
    return name + _suffix(trip.title or "")


def _home(db: Session, owner_id: Optional[int]) -> Optional[_Stop]:
    user = db.get(models.User, owner_id) if owner_id is not None else None
    a = _airport(getattr(user, "home_airport", None)) if user else None
    return _Stop(datetime.min, 0, a[0], a[1], a[2], airport=True) if a else None


def refresh(db: Session, trips: Iterable[models.Trip], commit: bool = True) -> list[tuple[int, str, str]]:
    """Retitle auto-titled trips whose route changed. Returns (id, old, new) for each change."""
    changes: list[tuple[int, str, str]] = []
    homes: dict[Optional[int], Optional[_Stop]] = {}
    for t in trips:
        if not t.title_auto:
            continue
        if t.owner_id not in homes:
            homes[t.owner_id] = _home(db, t.owner_id)
        new = route_title(t, homes[t.owner_id])
        if new and new != t.title:
            changes.append((t.id, t.title, new))
            t.title = new
    if changes and commit:
        db.commit()
        journal(db, changes)
    return changes


def journal_path(db: Session) -> Optional[Path]:
    """Where automatic retitles are recorded: TRIPPY_TITLE_LOG, else next to a SQLite database."""
    if os.environ.get("TRIPPY_TITLE_LOG"):
        return Path(os.environ["TRIPPY_TITLE_LOG"])
    url = db.get_bind().url
    if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
        return Path(url.database).with_name("title-changes.jsonl")
    return None


def journal(db: Session, changes: list[tuple[int, str, str]]) -> None:
    """Append each change so `scripts/retitle_trips.py --revert` can put old titles back."""
    path = journal_path(db)
    if path is None:
        return
    try:
        stamp = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        with path.open("a") as f:
            for tid, old, new in changes:
                f.write(json.dumps({"id": tid, "old": old, "new": new, "at": stamp}) + "\n")
    except OSError:
        pass  # a read-only volume must not break reads
