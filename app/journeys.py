"""Journeys: several trips linked into one long trip, plus merge, item moves and link suggestions.

Linking is non-destructive. A journey only points at its trips (trips.journey_id); unlinking or
deleting the journey leaves every trip exactly as it was. Dates, places, nights, miles and cost
are computed from the child trips on every read, reusing the per-trip story generator.

Merging is the destructive option: everything on trip B moves to trip A and B is deleted.

Who can do what:
- A journey is visible to its owner and (read-only) to travelers on any of its trips. Its detail
  only includes the trips the reader can see.
- Only the journey's owner can edit it, and only trips you own can be linked.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from . import access, airports, models, money, stories

NEAR_MILES = 60          # two places this close count as the same place (SJC ~ Fremont)
MAX_GAP_DAYS = 2         # back-to-back: the next trip starts within this many calendar days
KIND_ORDER = {"travelers": -1, "flight": 0, "rental": 1, "lodging": 2, "expenses": 3}


# --- access ---------------------------------------------------------------------------------

def visible_journeys(db: Session, user: models.User) -> list[models.Journey]:
    own = db.query(models.Journey).filter(models.Journey.owner_id == user.id).all()
    via = (db.query(models.Journey).join(models.Trip, models.Trip.journey_id == models.Journey.id)
           .filter(models.Trip.id.in_(access.trip_ids_subquery(user.id)))
           .filter(models.Journey.owner_id != user.id).distinct().all())
    return sorted({j.id: j for j in own + via}.values(), key=lambda j: j.id)


def journey_or_404(db: Session, journey_id: int, user: models.User) -> models.Journey:
    j = db.get(models.Journey, journey_id)
    if j is None:
        raise HTTPException(status_code=404, detail="Journey not found")
    if j.owner_id != user.id and not any(access.can_see_trip(user, t) for t in j.trips):
        raise HTTPException(status_code=404, detail="Journey not found")
    return j


def owned_journey_or_404(db: Session, journey_id: int, user: models.User) -> models.Journey:
    j = journey_or_404(db, journey_id, user)
    if j.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the journey's owner can change it")
    return j


def ordered_trips(j: models.Journey, user: Optional[models.User] = None) -> list[models.Trip]:
    trips = [t for t in j.trips if t.deleted_at is None and (user is None or access.can_see_trip(user, t))]
    far = datetime.max
    return sorted(trips, key=lambda t: (t.journey_position if t.journey_position is not None else 10**6,
                                        t.start_date or far, t.id))


def _renumber(j: models.Journey, trips: list[models.Trip]) -> None:
    for i, t in enumerate(trips):
        t.journey_position = i


def _by_date(trips: list[models.Trip]) -> list[models.Trip]:
    return sorted(trips, key=lambda t: (t.start_date or datetime.max, t.id))


# --- link / unlink ------------------------------------------------------------------------------

def _owned_trips(db: Session, user: models.User, trip_ids: list[int]) -> list[models.Trip]:
    out = []
    for tid in dict.fromkeys(trip_ids):
        out.append(access.owned_trip_or_404(db, tid, user))
    return out


def create(db: Session, user: models.User, title: Optional[str], trip_ids: list[int],
           description: Optional[str] = None, cover_photo: Optional[str] = None) -> models.Journey:
    trips = _owned_trips(db, user, trip_ids)
    if not title or not title.strip():
        title = suggested_title(db, user, trips) if trips else "New journey"
    j = models.Journey(owner_id=user.id, title=title.strip()[:120], description=description, cover_photo=cover_photo)
    db.add(j)
    db.flush()
    for t in trips:
        t.journey_id = j.id
    _renumber(j, _by_date(trips))
    db.commit()
    db.refresh(j)
    return j


def add_trips(db: Session, j: models.Journey, user: models.User, trip_ids: list[int]) -> models.Journey:
    trips = _owned_trips(db, user, trip_ids)
    current = ordered_trips(j)
    for t in trips:
        t.journey_id = j.id  # a trip in another journey moves here
    # New trips slot in by date among the existing (possibly hand-made) order.
    merged = list(current)
    for t in _by_date([t for t in trips if t not in current]):
        idx = next((i for i, c in enumerate(merged) if c.start_date and t.start_date and c.start_date > t.start_date),
                   len(merged))
        merged.insert(idx, t)
    _renumber(j, merged)
    db.commit()
    db.refresh(j)
    return j


def remove_trip(db: Session, j: models.Journey, user: models.User, trip_id: int) -> models.Journey:
    t = next((t for t in j.trips if t.id == trip_id), None)
    if t is None:
        raise HTTPException(status_code=404, detail="That trip isn't in this journey")
    t.journey_id = None
    t.journey_position = None
    db.flush()
    db.refresh(j)
    _renumber(j, ordered_trips(j))
    db.commit()
    db.refresh(j)
    return j


def reorder(db: Session, j: models.Journey, trip_ids: list[int]) -> models.Journey:
    have = {t.id: t for t in j.trips}
    if sorted(dict.fromkeys(trip_ids)) != sorted(have):
        raise HTTPException(status_code=400, detail="Send every trip in the journey exactly once")
    _renumber(j, [have[i] for i in trip_ids])
    db.commit()
    db.refresh(j)
    return j


def delete(db: Session, j: models.Journey) -> None:
    db.query(models.Drive).filter(models.Drive.journey_id == j.id).update({models.Drive.journey_id: None})
    for t in list(j.trips):
        t.journey_id = None
        t.journey_position = None
    db.delete(j)
    db.commit()


# --- places -----------------------------------------------------------------------------------

def _city(label: Optional[str]) -> Optional[str]:
    if not label:
        return None
    return label.split(",")[0].strip() or None


def _near(a: Optional[dict], b: Optional[dict]) -> bool:
    if not a or not b:
        return False
    if a.get("code") and a.get("code") == b.get("code"):
        return True
    ca, cb = (_city(a.get("city")) or "").lower(), (_city(b.get("city")) or "").lower()
    if ca and ca == cb:
        return True
    if None not in (a.get("lat"), a.get("lng"), b.get("lat"), b.get("lng")):
        return airports.haversine_miles(a["lat"], a["lng"], b["lat"], b["lng"]) <= NEAR_MILES
    return False


def _label(p: Optional[dict]) -> str:
    if not p:
        return "?"
    city = _city(p.get("city")) or p.get("code") or "?"
    return f"{city} ({p['code']})" if p.get("code") and p.get("code") != city else city


def _home_place(db: Session, user: models.User) -> Optional[dict]:
    return stories._place(stories.home_airport(db, user))


# --- per-trip summary ---------------------------------------------------------------------------

def _trip_cost(trip: models.Trip, rentals: list[models.RentalCar]) -> dict[str, float]:
    """Same rule as the app: logged expenses if there are any, else what was booked."""
    out: Counter = Counter()
    if trip.expenses:
        for e in trip.expenses:
            out[(e.currency or "USD").upper()] += e.amount or 0
        return dict(out)
    for f in trip.flights:
        if f.cost:
            out[(f.currency or "USD").upper()] += f.cost
    for r in rentals:
        if r.cost:
            out[(r.currency or "USD").upper()] += r.cost
    for h in trip.lodgings:
        if h.cost and (h.status or "").lower() != "cancelled":
            out[(h.currency or "USD").upper()] += h.cost
    return dict(out)


def _add(a: dict[str, float], b: dict[str, float]) -> dict[str, float]:
    out = dict(a)
    for k, v in b.items():
        out[k] = round(out.get(k, 0) + v, 2)
    return out


def _parse(s: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(s) if s else None


def _leg(db: Session, trip: models.Trip, user: models.User) -> dict:
    g = stories.generate(db, trip, user)
    rentals = stories.trip_rentals(db, trip, user)
    st = g["stats"]
    title = (trip.title or "Trip").removesuffix(" (auto)")
    return {
        "trip_id": trip.id, "title": title, "owner_id": trip.owner_id,
        "start_date": g["start_date"], "end_date": g["end_date"],
        "places": [_city(p.get("city")) for p in g["route"] if p.get("city")],
        "route": g["route"],
        "stats": {k: st[k] for k in ("days", "flights", "rentals", "stays", "nights", "flight_miles",
                                       "drive_miles", "distance_miles", "places", "countries")},
        "cost_by_currency": {k: round(v, 2) for k, v in _trip_cost(trip, rentals).items()},
        "items": [i for i in g["items"] if i["kind"] != "travelers"],
        "travelers": g["travelers"],
        "_countries": {p["country"] for p in g["route"] if p.get("country")},
        "_cities": set(st["cities"]),
    }


def _route_join(legs: list[dict]) -> list[dict]:
    route: list[dict] = []
    for leg in legs:
        for p in leg["route"]:
            if route and _near(route[-1], p) and route[-1].get("city") == p.get("city"):
                continue
            route.append(p)
    return route


def summary(db: Session, j: models.Journey, user: models.User, legs: Optional[list[dict]] = None) -> dict:
    trips = ordered_trips(j, user)
    legs = legs if legs is not None else [_leg(db, t, user) for t in trips]
    starts = [_parse(l["start_date"]) for l in legs if l["start_date"]]
    ends = [_parse(l["end_date"]) for l in legs if l["end_date"]]
    start, end = (min(starts) if starts else None), (max(ends) if ends else None)
    days = (end.date() - start.date()).days + 1 if start and end else None
    cost: dict[str, float] = {}
    for l in legs:
        cost = _add(cost, l["cost_by_currency"])
    tot = lambda k: sum(l["stats"][k] or 0 for l in legs)  # noqa: E731
    places: list[str] = []
    for l in legs:
        for p in l["places"]:
            if p and (not places or places[-1] != p):
                places.append(p)
    cities = set().union(*(l["_cities"] for l in legs)) if legs else set()
    countries = set().union(*(l["_countries"] for l in legs)) if legs else set()
    return {
        "id": j.id, "owner_id": j.owner_id, "title": j.title, "description": j.description,
        "cover_photo": j.cover_photo, "is_owner": j.owner_id == user.id,
        "trip_ids": [t.id for t in trips], "trip_count": len(trips),
        "start_date": start.isoformat() if start else None, "end_date": end.isoformat() if end else None,
        "places": places,
        "stats": {"days": days, "trips": len(legs), "flights": tot("flights"), "rentals": tot("rentals"),
                  "stays": tot("stays"), "nights": tot("nights"), "flight_miles": tot("flight_miles"),
                  "drive_miles": tot("drive_miles"), "miles": tot("distance_miles"),
                  "places": len(cities), "countries": len(countries)},
        "cost_by_currency": cost,
    }


def ledger(db: Session, trips: list[models.Trip]) -> dict:
    """One combined balance across every child trip's expenses and settlements."""
    expenses, settlements, people = [], [], []
    titles = {}
    for t in trips:
        e, s = money._trip_parts(db, t)
        expenses += e
        settlements += s
        titles[t.id] = t.title
        people += [t.owner_id] + [p.id for p in t.participants]
    edges = money._edges(expenses, settlements, lambda e: titles.get(e.trip_id) or "Trip")
    return money._ledger(db, edges, list(dict.fromkeys(people)), expenses, settlements)


def detail(db: Session, j: models.Journey, user: models.User) -> dict:
    trips = ordered_trips(j, user)
    legs = [_leg(db, t, user) for t in trips]
    out = summary(db, j, user, legs)
    timeline = []
    for n, (t, leg) in enumerate(zip(trips, legs), start=1):
        for i in leg["items"]:
            timeline.append({**i, "trip_id": t.id, "leg": n, "trip_title": leg["title"]})
    people: dict[int, dict] = {}
    for leg in legs:
        for p in leg["travelers"]:
            people.setdefault(p["id"], p)
    out.update({
        "legs": [{k: v for k, v in l.items() if not k.startswith("_") and k not in ("items", "travelers")}
                 | {"leg": n, "item_count": len(l["items"])} for n, l in enumerate(legs, start=1)],
        "timeline": timeline,
        "route": _route_join(legs),
        "travelers": list(people.values()),
        "balances": ledger(db, trips),
    })
    return out


def story(db: Session, j: models.Journey, user: models.User) -> dict:
    """A journey story in the same shape as a trip story (read-only; edits live on each trip)."""
    trips = ordered_trips(j, user)
    if not trips:
        raise HTTPException(status_code=404, detail="This journey has no trips you can see")
    gens = [stories.build(db, t, user) for t in trips]
    items, travelers, highlights = [], {}, []
    for g in gens:
        for p in g["travelers"]:
            travelers.setdefault(p["id"], p)
        items += [i for i in g["items"] if i["kind"] != "travelers"]
        highlights += g["highlights"]
    dated = sorted([i for i in items if i["date"]], key=lambda i: (i["date"], KIND_ORDER.get(i["kind"], 9)))
    undated = [i for i in items if not i["date"]]
    s = summary(db, j, user)
    start = _parse(s["start_date"])
    for i in dated:
        i["day"] = (_parse(i["date"]).date() - start.date()).days + 1 if start else None
    if len(travelers) > 1:
        people = list(travelers.values())
        dated.insert(0, {"key": "travelers", "kind": "travelers", "date": s["start_date"], "end_date": None,
                         "title": f"{len(people)} travelers", "subtitle": ", ".join(p["name"] for p in people[:5]),
                         "place": None, "from_place": None, "to_place": None, "metric": None, "miles": None,
                         "brand": None, "code": None, "people": people, "money": False, "day": 1,
                         "hidden": False, "note": None, "photos": []})
    # Keep the best of each highlight type across legs.
    best: dict[str, dict] = {}
    for h in highlights:
        def num(x):
            try:
                return float("".join(c for c in (x.get("detail") or x.get("value") or "") if c.isdigit() or c == "."))
            except ValueError:
                return 0
        if h["label"] not in best or num(h) > num(best[h["label"]]):
            best[h["label"]] = h
    spend: Counter = Counter()
    stay_spend: Counter = Counter()
    for g in gens:
        spend.update(g["stats"]["spend"])
        stay_spend.update(g["stats"]["stay_spend"])
    cities = sorted(set().union(*(set(g["stats"]["cities"]) for g in gens)))
    st = s["stats"]
    return {
        "trip_id": trips[0].id, "journey_id": j.id,
        "generated_title": j.title, "title": j.title, "subtitle": " → ".join(s["places"][:6]) or None,
        "theme": "indigo", "cover_photo": j.cover_photo or next((g["cover_photo"] for g in gens if g["cover_photo"]), None),
        "edited": False, "updated_at": None,
        "start_date": s["start_date"], "end_date": s["end_date"],
        "items": dated + undated,
        "route": _route_join([{"route": g["route"]} for g in gens]),
        "travelers": list(travelers.values()),
        "highlights": list(best.values()),
        "stats": {
            "days": st["days"], "places": len(cities), "countries": st["countries"], "flights": st["flights"],
            "rentals": st["rentals"], "stays": st["stays"], "nights": st["nights"],
            "flight_miles": st["flight_miles"], "drive_miles": st["drive_miles"], "distance_miles": st["miles"],
            "travelers": len(travelers), "spend": {k: round(v, 2) for k, v in spend.items()},
            "stay_spend": {k: round(v, 2) for k, v in stay_spend.items()},
            "spend_text": " + ".join(stories._money(v, c) for c, v in spend.most_common()) if spend else None,
            "cities": cities,
        },
    }


# --- merge ------------------------------------------------------------------------------------

def merge(db: Session, target: models.Trip, source: models.Trip) -> dict:
    """Move everything from `source` into `target`, then delete `source`."""
    if target.id == source.id:
        raise HTTPException(status_code=400, detail="Pick a different trip to merge")
    moved = Counter()
    for model, key in ((models.Flight, "flights"), (models.RentalCar, "rentals"), (models.Lodging, "stays"),
                       (models.Expense, "expenses"), (models.Activity, "activities"), (models.Document, "documents"),
                       (models.Settlement, "settlements"), (models.Drive, "drives")):
        rows = db.query(model).filter(model.trip_id == source.id).all()
        for r in rows:
            r.trip_id = target.id
        moved[key] = len(rows)
    have = {p.id for p in target.participants} | {target.owner_id}
    for p in list(source.participants):
        if p.id not in have:
            target.participants.append(p)
            moved["travelers"] += 1
    for inv in db.query(models.TripInvite).filter(models.TripInvite.trip_id == source.id).all():
        inv.trip_id = target.id
    db.query(models.TripStory).filter(models.TripStory.trip_id == source.id).delete()
    for d in db.query(models.DismissedSuggestion).all():
        if str(source.id) in d.trip_key.split(","):
            db.delete(d)
    if source.start_date and (not target.start_date or source.start_date < target.start_date):
        target.start_date = source.start_date
    if source.end_date and (not target.end_date or source.end_date > target.end_date):
        target.end_date = source.end_date
    if target.journey_id is None and source.journey_id is not None:
        target.journey_id, target.journey_position = source.journey_id, source.journey_position
    if not target.native_album_id and source.native_album_id:
        target.native_album_id = source.native_album_id
    if not target.group_id and source.group_id:
        target.group_id = source.group_id
    source.participants = []
    db.flush()
    db.delete(source)
    db.commit()
    db.refresh(target)
    return {k: v for k, v in moved.items()}


# --- moving items -------------------------------------------------------------------------------

ITEM_MODELS = {"flight": models.Flight, "rental": models.RentalCar, "lodging": models.Lodging,
               "stay": models.Lodging, "expense": models.Expense}


def move_items(db: Session, user: models.User, target_trip_id: Optional[int], items: list[dict]) -> dict:
    target = access.trip_or_404(db, target_trip_id, user) if target_trip_id is not None else None
    rows = []
    for it in items:  # check everything first: all or nothing
        kind, iid = it["kind"], it["id"]
        if kind == "flight":
            row = access.flights(db, user).filter(models.Flight.id == iid).first()
        elif kind == "rental":
            row = access.rentals(db, user).filter(models.RentalCar.id == iid).first()
        elif kind in ("lodging", "stay"):
            row = access.lodgings(db, user).filter(models.Lodging.id == iid).first()
        elif kind == "expense":
            row = access.expenses(db, user).filter(models.Expense.id == iid).first()
            if row is not None and target is None:
                raise HTTPException(status_code=400, detail="An expense has to stay on a trip")
        else:
            raise HTTPException(status_code=400, detail=f"Can't move a {kind}")
        if row is None:
            raise HTTPException(status_code=404, detail=f"{kind.capitalize()} {iid} not found")
        owner = getattr(row, "owner_id", None) if kind != "expense" else row.payer_id
        trip_owner = row.trip.owner_id if row.trip is not None else None
        if user.id not in (owner, trip_owner):
            raise HTTPException(status_code=403, detail=f"Only its owner or the trip's owner can move that {kind}")
        rows.append((kind, row))
    added: list[int] = []
    from_trips: set[int] = set()
    for kind, row in rows:
        if row.trip_id:
            from_trips.add(row.trip_id)
        if kind != "expense" and row.trip_id is not None and getattr(row, "owner_id", None) is None:
            row.owner_id = row.trip.owner_id  # keep an owner when it leaves the trip
        row.trip_id = target.id if target else None
        if kind == "expense":
            row.group_id = None
            people = {row.payer_id} | {s.user_id for s in row.splits}
            have = {p.id for p in target.participants} | {target.owner_id}
            for uid in sorted(people - have):
                u = db.get(models.User, uid)
                if u is not None:
                    target.participants.append(u)
                    added.append(uid)
    if target is not None:
        dated = [(k, r) for k, r in rows if k != "expense"]  # expense dates default to "now"
        starts = [s for s in (_item_start(k, r) for k, r in dated) if s]
        ends = [e for e in (_item_end(k, r) for k, r in dated) if e]
        if starts and target.start_date and min(starts) < target.start_date:
            target.start_date = min(starts)
        if ends and target.end_date and max(ends) > target.end_date:
            target.end_date = max(ends)
    db.commit()
    return {"moved": [{"kind": k, "id": r.id, "trip_id": r.trip_id} for k, r in rows],
            "from_trip_ids": sorted(from_trips), "added_traveler_ids": sorted(set(added))}


_START = {"flight": "departure_time", "rental": "pickup_time", "lodging": "check_in", "stay": "check_in", "expense": "date"}
_END = {"flight": "arrival_time", "rental": "dropoff_time", "lodging": "check_out", "stay": "check_out", "expense": "date"}


def _item_start(kind, r):
    return getattr(r, _START[kind])


def _item_end(kind, r):
    return getattr(r, _END[kind])


# --- suggestions --------------------------------------------------------------------------------

def _features(db: Session, trip: models.Trip, user: models.User, home: Optional[dict]) -> dict:
    """Where a trip starts and ends, its travel legs (flights + drives) and the places it touches."""
    legs = []
    for f in trip.flights:
        a, b = stories._place(f.departure_airport), stories._place(f.arrival_airport)
        if a and b:
            legs.append((f.departure_time or datetime.max, a, b, "fly"))
    for r in stories.trip_rentals(db, trip, user):
        a = stories._rental_place(r.pickup_code, r.pickup_location, r.pickup_city, r.pickup_lat, r.pickup_lng)
        b = stories._rental_place(r.dropoff_code, r.dropoff_location, r.dropoff_city, r.dropoff_lat, r.dropoff_lng)
        if a and b:
            legs.append((r.pickup_time or datetime.max, a, b, "drive"))
    legs.sort(key=lambda x: x[0])
    stays = sorted([h for h in trip.lodgings if (h.status or "").lower() != "cancelled"],
                   key=lambda h: h.check_in or datetime.max)
    stay_places = [{"code": None, "city": h.city or h.address, "country": h.country, "lat": h.lat, "lng": h.lng}
                   for h in stays if h.city or h.address]
    times = [t for t in [trip.start_date, trip.end_date] if t]
    for f in trip.flights:
        times += [t for t in (f.departure_time, f.arrival_time) if t]
    for h in stays:
        times += [t for t in (h.check_in, h.check_out) if t]
    start = trip.start_date or (min(times) if times else None)
    end = trip.end_date or (max(times) if times else None)
    first = legs[0][1] if legs else (stay_places[0] if stay_places else None)
    last = legs[-1][2] if legs else (stay_places[-1] if stay_places else None)
    places = [p for _, a, b, _ in legs for p in (a, b)] + stay_places
    away = [p for p in places if not _near(p, home)]
    return {"trip": trip, "start": start, "end": end, "first": first, "last": last, "legs": legs,
            "places": places, "away": away,
            "starts_home": _near(first, home), "ends_home": _near(last, home)}


def suggested_title(db: Session, user: models.User, trips: list[models.Trip]) -> str:
    """Places you went, in order, without home, the place you set out from, or plane changes."""
    home = _home_place(db, user)
    feats = [_features(db, t, user, home) for t in _by_date(trips)]
    origin = feats[0]["first"] if feats else None
    legs = sorted((l for f in feats for l in f["legs"]), key=lambda l: l[0])
    connections = [a[2] for a, b in zip(legs, legs[1:]) if a[3] == b[3] == "fly" and _near(a[2], b[1])
                   and (b[0] - a[0]).total_seconds() < 10 * 3600]
    seq = [(when, b) for when, _a, b, _how in legs]
    for f in feats:
        for h in sorted(f["trip"].lodgings, key=lambda h: h.check_in or datetime.max):
            if h.city and (h.status or "").lower() != "cancelled":
                seq.append((h.check_in or datetime.max, {"code": None, "city": h.city, "lat": h.lat, "lng": h.lng}))
    seq.sort(key=lambda x: x[0])
    names: list[str] = []
    seen: list[dict] = []
    for _, p in seq:
        c = _city(p.get("city"))
        if not c or _near(p, home) or any(_near(p, x) for x in connections):
            continue
        if origin and _near(p, origin) and len(legs) > 2:
            continue
        if p.get("lat") is None and len(c) == 3 and c.isupper():
            continue  # an airport we can't name
        if c in names or any(_near(p, q) for q in seen):
            continue
        names.append(c)
        seen.append(p)
    if not names:
        names = [(t.title or "Trip").removesuffix(" (auto)") for t in _by_date(trips)]
    if len(names) > 3:
        return f"{names[0]} → … → {names[-1]}"
    return " → ".join(names)


def _pair(a: dict, b: dict) -> Optional[tuple[float, list[str]]]:
    if not (a["start"] and a["end"] and b["start"]):
        return None
    gap = (b["start"].date() - a["end"].date()).days
    overlap = b["start"] < a["end"]
    if gap > MAX_GAP_DAYS:
        return None
    ta = (a["trip"].title or "Trip").removesuffix(" (auto)")
    tb = (b["trip"].title or "Trip").removesuffix(" (auto)")
    when = "overlaps it" if overlap else ("starts the same day" if gap <= 0 else f"starts {gap} day{'s' if gap != 1 else ''} later")
    reasons, score = [], 0.0
    shared = [p for p in reversed(a["away"]) if any(_near(p, q) for q in b["away"])]
    if a["ends_home"] or b["starts_home"]:
        # You went home in between: two trips. Unless one side is just a stay somewhere the other
        # trip also went (a hotel booked separately from the flights).
        if shared and (not a["legs"] or not b["legs"]):
            return 0.35, [f"Both trips are in {_label(shared[0])}; “{tb}” {when}"]
        return None
    if _near(a["last"], b["first"]):
        score += 0.45
        reasons.append(f"“{ta}” ends in {_label(a['last'])} and “{tb}” {when} from there")
    elif a["legs"] and b["legs"] and _near(a["legs"][-1][2], b["legs"][0][1]):
        score += 0.4
        reasons.append(f"Travel chains: {_label(a['legs'][-1][2])} is where one leg ends and the next begins")
    if shared and not reasons:
        score += 0.3
        reasons.append(f"Both trips are in {_label(shared[0])}; “{tb}” {when}")
    if not reasons:
        if overlap or a["last"] is None or b["first"] is None:
            return None  # overlapping dates alone isn't enough (e.g. Tokyo vs Denver)
        if gap > 1:
            return None
        score += 0.2
        reasons.append(f"“{tb}” {when} and you didn't fly home in between")
    else:
        score += 0.1 if gap <= 1 else 0.0
    score += 0.2  # no trip home between them
    return score, reasons


def _stops(group: list[dict]) -> list[dict]:
    """Places along the chained legs, consecutive repeats collapsed."""
    legs = [l for f in group for l in f["legs"]]
    stops: list[dict] = []
    for _, a, b, _how in legs:
        for p in (a, b):
            if not stops or not _near(stops[-1], p):
                stops.append(p)
    return stops


def _route_text(group: list[dict]) -> Optional[str]:
    stops = _stops(group)
    if len(stops) < 3:
        return None
    return " → ".join(p.get("code") or _city(p.get("city")) or "?" for p in stops)


def suggestions(db: Session, user: models.User, include_dismissed: bool = False) -> dict:
    home = _home_place(db, user)
    owned = (db.query(models.Trip).filter(models.Trip.owner_id == user.id, models.Trip.deleted_at.is_(None)).all())
    feats = sorted([_features(db, t, user, home) for t in owned],
                   key=lambda f: (f["start"] or datetime.max, f["trip"].id))
    feats = [f for f in feats if f["start"]]
    dismissed = {d.trip_key for d in db.query(models.DismissedSuggestion).filter_by(user_id=user.id).all()}

    groups: list[dict] = []
    for i in range(len(feats) - 1):
        a, b = feats[i], feats[i + 1]
        res = _pair(a, b)
        if res is None:
            continue
        score, reasons = res
        if groups and groups[-1]["members"][-1] is a:
            groups[-1]["members"].append(b)
            groups[-1]["scores"].append(score)
            groups[-1]["reasons"] += reasons
        else:
            groups.append({"members": [a, b], "scores": [score], "reasons": list(reasons)})

    out = []
    for g in groups:
        trips = [f["trip"] for f in g["members"]]
        key = ",".join(str(i) for i in sorted(t.id for t in trips))
        journeys = {t.journey_id for t in trips}
        if len(journeys) == 1 and None not in journeys:
            continue  # already linked
        if key in dismissed and not include_dismissed:
            continue
        score = min(g["scores"])
        reasons = list(dict.fromkeys(g["reasons"]))
        first, last = g["members"][0]["first"], g["members"][-1]["last"]
        route = _route_text(g["members"])
        if first and last and _near(first, last) and len(g["members"]) > 1 and g["members"][0]["legs"]:
            score += 0.15
            reasons.append(f"Together they loop back to {_label(first)}" + (f": {route}" if route else ""))
        elif route:
            reasons.append(f"Route: {route}")
        existing = sorted(j for j in journeys if j is not None)
        out.append({
            "key": key,
            "trip_ids": [t.id for t in trips],
            "trips": [{"id": t.id, "title": t.title,
                       "start_date": f["start"].isoformat() if f["start"] else None,
                       "end_date": f["end"].isoformat() if f["end"] else None} for t, f in zip(trips, g["members"])],
            "title": suggested_title(db, user, trips),
            "score": round(min(score, 0.99), 2),
            "confidence": "high" if score >= 0.75 else "medium" if score >= 0.55 else "low",
            "reasons": reasons,
            "journey_id": existing[0] if existing else None,  # link into this one if some are already linked
            "dismissed": key in dismissed,
        })
    out.sort(key=lambda s: (-s["score"], s["trip_ids"][0]))

    notes = []
    for f in feats:  # one trip that already holds a long multi-leg loop (e.g. drive SFO→LAX, fly LAX→ANC→PHX→SFO)
        clusters: list[dict] = []
        for p in f["away"]:
            if not any(_near(p, q) for q in clusters):
                clusters.append(p)
        title = (f["trip"].title or "").lower()
        route = _route_text([f])
        if route and len(f["legs"]) >= 3 and len(clusters) >= 3 and f["starts_home"] and f["ends_home"]:
            words = set(re.findall(r"[a-z]+", title))
            missing = [p for p in clusters if (_city(p.get("city")) or "").lower() not in title
                       and (p.get("code") or "").lower() not in words]
            if len(missing) >= 2:
                notes.append({"trip_id": f["trip"].id, "title": f["trip"].title,
                              "start_date": f["start"].isoformat() if f["start"] else None,
                              "end_date": f["end"].isoformat() if f["end"] else None,
                              "suggested_title": suggested_title(db, user, [f["trip"]]),
                              "note": f"Already one trip: {route}. Its title only names part of the route."})
    return {"suggestions": out, "notes": notes}


def dismiss(db: Session, user: models.User, trip_ids: list[int]) -> str:
    key = ",".join(str(i) for i in sorted(set(trip_ids)))
    if not db.query(models.DismissedSuggestion).filter_by(user_id=user.id, trip_key=key).first():
        db.add(models.DismissedSuggestion(user_id=user.id, trip_key=key))
        db.commit()
    return key
