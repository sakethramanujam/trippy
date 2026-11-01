"""Trip stories and Year in Travel.

A story is generated from the trip every time it's read (flights, rentals, stays, spending,
travelers), then the reader's saved edits are layered on top: title, subtitle, theme, item
order, hidden items, notes and photo ids. Photos themselves stay on the phone; the server only
keeps their ids so the order and captions follow the account.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Optional

from sqlalchemy.orm import Session

from . import access, airports, models
from . import drives as drives_mod
from . import photos as photos_mod

MAX_NOTE = 280
MAX_TITLE = 80
MAX_PHOTOS = 10
THEMES = ("indigo", "sunset", "ocean", "forest", "rose")


def _name(u: Optional[models.User]) -> str:
    if u is None:
        return "Someone"
    return u.display_name or u.username or (u.email or "").split("@")[0] or f"Traveler {u.id}"


def _iso(d: Optional[datetime]) -> Optional[str]:
    return d.isoformat() if d else None


def _place(code: Optional[str], city: Optional[str] = None, lat=None, lng=None) -> Optional[dict]:
    code = (code or "").strip().upper() or None
    hit = airports.lookup(code)
    if hit:
        return {"code": code, "city": city or hit[0], "country": hit[1], "lat": lat if lat is not None else hit[2],
                "lng": lng if lng is not None else hit[3]}
    if city or code or lat is not None:
        return {"code": code, "city": city or code, "country": None, "lat": lat, "lng": lng}
    return None


def _rental_place(code, location, city, lat, lng) -> Optional[dict]:
    """Rental stations: a stored IATA code, else a code at the start of the location text
    ("LHR Airport"), else the city / location as written."""
    if not code and location:
        first = location.strip().split()[0].strip(",").upper() if location.strip() else ""
        if airports.lookup(first):
            code = first
    if code and airports.lookup(code):
        return _place(code, city, lat, lng)
    label = city or (location.strip() if location else None)
    if not label and lat is None:
        return None
    near = airports.nearest(lat, lng)
    return {"code": None, "city": label, "country": airports.lookup(near)[1] if near else None, "lat": lat, "lng": lng}


def home_airport(db: Session, user: models.User) -> Optional[str]:
    """The profile's home airport, else the airport the user departs from most."""
    if airports.lookup(user.home_airport):
        return user.home_airport.upper()
    deps = Counter((f.departure_airport or "").upper() for f in access.flights(db, user).all())
    for code, _ in deps.most_common():
        if airports.lookup(code):
            return code
    return None


def _money(amount: float, currency: str) -> str:
    sym = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "INR": "₹", "CAD": "CA$", "AUD": "A$"}.get(currency)
    whole = amount >= 100 or float(amount).is_integer()
    num = f"{amount:,.0f}" if whole else f"{amount:,.2f}"
    return f"{sym}{num}" if sym else f"{num} {currency}"


def _flight_miles(f: models.Flight) -> Optional[float]:
    if f.distance_miles:
        return float(f.distance_miles)
    return airports.route_miles(f.departure_airport, f.arrival_airport)


def _rental_miles(r: models.RentalCar) -> Optional[float]:
    if r.mileage_driven:
        return float(r.mileage_driven)
    if r.pickup_odometer is not None and r.dropoff_odometer is not None and r.dropoff_odometer > r.pickup_odometer:
        return float(r.dropoff_odometer - r.pickup_odometer)
    return None


def _duration(a: Optional[datetime], b: Optional[datetime]) -> Optional[str]:
    if not a or not b or b <= a:
        return None
    mins = int((b - a).total_seconds() // 60)
    h, m = divmod(mins, 60)
    return f"{h}h {m}m" if h else f"{m}m"


def trip_rentals(db: Session, trip: models.Trip, user: models.User) -> list[models.RentalCar]:
    """Rentals on the trip, plus your unassigned rentals picked up during it (same rule as the app)."""
    by_id = {r.id: r for r in trip.rental_cars}
    if trip.start_date and trip.end_date:
        lo, hi = trip.start_date - timedelta(hours=12), trip.end_date + timedelta(hours=36)
        for r in access.rentals(db, user).filter(models.RentalCar.trip_id.is_(None)).all():
            if r.pickup_time and lo <= r.pickup_time <= hi:
                by_id[r.id] = r
    return sorted(by_id.values(), key=lambda r: r.pickup_time or datetime.max)


def _hm(minutes: int) -> Optional[str]:
    if not minutes:
        return None
    h, m = divmod(int(minutes), 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


def drive_items(day_rows: list[dict]) -> list[dict[str, Any]]:
    """Story/timeline entries for Timeline drives: one "Driving day" per day, with each drive's path."""
    out = []
    for d in day_rows:
        a, b = d["from_name"], d["to_name"]
        title = f"{a} → {b}" if a and b and a != b else "Driving day"
        n, stops = d["drives"], len(d["stops"])
        sub = ["Driving day" if title != "Driving day" else None,
               f"{n} drives" if n > 1 else None, _hm(d["minutes"]),
               f"{stops} stop{'s' if stops != 1 else ''}" if stops else None]
        out.append({
            "key": f"drive:{d['date'].isoformat()}", "kind": "drive",
            "date": _iso(d["start"]), "end_date": _iso(d["end"]),
            "title": title, "subtitle": " · ".join(x for x in sub if x) or None,
            "place": d["place"], "from_place": d["from_place"], "to_place": None,
            "metric": f"{d['miles']:,.0f} mi" if d["miles"] >= 1 else f"{d['miles']:.1f} mi",
            "miles": round(d["miles"], 1), "brand": None, "code": None,
            "paths": d["paths"], "stops": d["stops"], "drive_ids": d["drive_ids"],
        })
    return out


KIND_SORT = {"flight": 0, "rental": 1, "drive": 2, "lodging": 3, "expenses": 4}


def generate(db: Session, trip: models.Trip, user: models.User) -> dict[str, Any]:
    """The unedited story: chronological items, places, route and stats."""
    items: list[dict[str, Any]] = []
    route: list[dict] = []
    flight_miles = drive_miles = 0.0
    longest_flight: Optional[tuple[float, models.Flight]] = None
    longest_drive: Optional[tuple[float, models.RentalCar]] = None

    for f in trip.flights:
        miles = _flight_miles(f)
        if miles:
            flight_miles += miles
            if not longest_flight or miles > longest_flight[0]:
                longest_flight = (miles, f)
        dep, arr = _place(f.departure_airport), _place(f.arrival_airport)
        bits = [f"{f.airline} {f.flight_number}".strip(), _duration(f.departure_time, f.arrival_time)]
        items.append({
            "key": f"flight:{f.id}", "kind": "flight",
            "date": _iso(f.departure_time), "end_date": _iso(f.arrival_time),
            "title": f"{(dep or {}).get('city') or f.departure_airport} to {(arr or {}).get('city') or f.arrival_airport}",
            "subtitle": " · ".join(b for b in bits if b),
            "place": arr, "from_place": dep,
            "metric": f"{miles:,.0f} mi" if miles else None, "miles": miles,
            "brand": f.airline, "code": f.flight_number,
        })

    rentals = trip_rentals(db, trip, user)
    for r in rentals:
        miles = _rental_miles(r)
        if miles:
            drive_miles += miles
            if not longest_drive or miles > longest_drive[0]:
                longest_drive = (miles, r)
        pick = _rental_place(r.pickup_code, r.pickup_location, r.pickup_city, r.pickup_lat, r.pickup_lng)
        drop = _rental_place(r.dropoff_code, r.dropoff_location, r.dropoff_city, r.dropoff_lat, r.dropoff_lng)
        car = " ".join(x for x in (r.vehicle_make, r.car_model) if x) or r.vehicle_class or "Rental car"
        days = None
        if r.pickup_time and r.dropoff_time:
            days = max(1, (r.dropoff_time.date() - r.pickup_time.date()).days)
        sub = [r.rental_company, f"{days} day{'s' if days != 1 else ''}" if days else None]
        if pick and drop and pick.get("city") != drop.get("city"):
            sub.append(f"one-way to {drop.get('city')}")
        items.append({
            "key": f"rental:{r.id}", "kind": "rental",
            "date": _iso(r.pickup_time), "end_date": _iso(r.dropoff_time),
            "title": car, "subtitle": " · ".join(s for s in sub if s),
            "place": pick, "from_place": None, "to_place": drop if drop != pick else None,
            "metric": f"{miles:,.0f} mi driven" if miles else None, "miles": miles,
            "brand": r.rental_company, "code": r.license_plate,
        })

    # Your Timeline drives (private to you). Miles a rental already recorded aren't counted twice.
    tdrives = drives_mod.trip_drives(db, trip, user)
    timeline_miles = sum(d.distance_miles or 0 for d in tdrives)
    drive_miles += drives_mod.counted_miles(tdrives, rentals)
    day_rows = drives_mod.driving_days(tdrives)
    items += drive_items(day_rows)
    longest_day = max(day_rows, key=lambda d: d["miles"], default=None)

    nights_total = 0
    stays = [h for h in trip.lodgings if (h.status or "").lower() != "cancelled"]
    stay_spend: Counter = Counter()
    for h in stays:
        nights = h.nights if h.nights is not None else (
            (h.check_out.date() - h.check_in.date()).days if h.check_in and h.check_out else None)
        nights_total += nights or 0
        if h.cost:
            stay_spend[(h.currency or "USD").upper()] += h.cost
        city = h.city or h.address
        place = {"code": None, "city": city, "country": h.country, "lat": h.lat, "lng": h.lng} if city else None
        sub = (f"{nights} night{'s' if nights != 1 else ''}" if nights else None,
               h.city or h.address, h.booking_source if h.booking_source and h.booking_source != "direct" else None)
        items.append({
            "key": f"lodging:{h.id}", "kind": "lodging",
            "date": _iso(h.check_in), "end_date": _iso(h.check_out),
            "title": h.name,
            "subtitle": " · ".join(s for s in sub if s),
            "place": place,
            "metric": _money(h.cost, (h.currency or "USD").upper()) if h.cost else None, "miles": None,
            "brand": h.brand, "code": h.confirmation_number,
        })

    by_day: dict[date, list[models.Expense]] = defaultdict(list)
    spend: Counter = Counter()
    biggest: Optional[models.Expense] = None
    spend.update(stay_spend)  # booked stays count toward the trip's spend
    for e in trip.expenses:
        cur = (e.currency or "USD").upper()
        spend[cur] += e.amount or 0
        if e.date:
            by_day[e.date.date()].append(e)
        if biggest is None or (e.amount or 0) > (biggest.amount or 0):
            biggest = e
    for day, rows in sorted(by_day.items()):
        rows.sort(key=lambda e: -(e.amount or 0))
        per_cur: Counter = Counter()
        for e in rows:
            per_cur[(e.currency or "USD").upper()] += e.amount or 0
        total = " + ".join(_money(v, c) for c, v in per_cur.most_common())
        items.append({
            "key": f"expenses:{day.isoformat()}", "kind": "expenses",
            "date": datetime.combine(day, datetime.min.time()).replace(hour=20).isoformat(), "end_date": None,
            "title": f"Spent {total}",
            "subtitle": ", ".join(e.description or "Expense" for e in rows[:3]) + (f" +{len(rows) - 3} more" if len(rows) > 3 else ""),
            "place": None, "metric": f"{len(rows)} expense{'s' if len(rows) != 1 else ''}", "miles": None,
            "brand": None, "code": None, "money": True,
        })

    people = []
    seen = set()
    for u in [trip.owner, *trip.participants]:
        if u is not None and u.id not in seen:
            seen.add(u.id)
            people.append({"id": u.id, "name": _name(u)})

    dated = [i for i in items if i["date"]]
    undated = [i for i in items if not i["date"]]
    dated.sort(key=lambda i: (i["date"], KIND_SORT[i["kind"]]))
    start = trip.start_date or (datetime.fromisoformat(dated[0]["date"]) if dated else None)
    end = trip.end_date or (datetime.fromisoformat(max(i["end_date"] or i["date"] for i in dated)) if dated else None)
    if start and end and end < start:
        end = start

    if len(people) > 1:
        dated.insert(0, {
            "key": "travelers", "kind": "travelers", "date": _iso(start), "end_date": None,
            "title": f"{len(people)} travelers",
            "subtitle": ", ".join(p["name"] for p in people[:5]) + (f" +{len(people) - 5}" if len(people) > 5 else ""),
            "place": None, "metric": None, "miles": None, "brand": None, "code": None, "people": people,
        })
    ordered = dated + undated
    for i in ordered:
        i.setdefault("from_place", None)
        i.setdefault("to_place", None)
        i.setdefault("people", None)
        i.setdefault("money", False)
        i["day"] = (datetime.fromisoformat(i["date"]).date() - start.date()).days + 1 if (i["date"] and start) else None

    # Route: chronological stops, consecutive duplicates collapsed.
    for i in ordered:
        for p in (i.get("from_place"), i.get("place"), i.get("to_place")):
            if not p or p.get("lat") is None or i["kind"] == "lodging":
                continue
            if route and route[-1].get("city") == p.get("city"):
                continue
            route.append(p)

    cities = {p["city"] for p in route if p.get("city")}
    countries = {p["country"] for p in route if p.get("country")}
    days = (end.date() - start.date()).days + 1 if start and end else None

    home = airports.lookup(user.home_airport)
    highlights = []
    if longest_flight:
        m, f = longest_flight
        highlights.append({"icon": "airplane", "label": "Longest flight",
                           "value": f"{f.departure_airport} → {f.arrival_airport}", "detail": f"{m:,.0f} mi"})
    if longest_drive:
        m, r = longest_drive
        highlights.append({"icon": "car.fill", "label": "Longest drive",
                           "value": f"{m:,.0f} mi", "detail": f"{r.rental_company}"})
    elif longest_day and longest_day["miles"] >= 20:
        highlights.append({"icon": "car.fill", "label": "Longest drive",
                           "value": f"{longest_day['miles']:,.0f} mi",
                           "detail": longest_day["date"].strftime("%b %-d")})
    if home and route:
        far = max(route, key=lambda p: airports.haversine_miles(home[2], home[3], p["lat"], p["lng"]))
        d = airports.haversine_miles(home[2], home[3], far["lat"], far["lng"])
        if d > 50:
            highlights.append({"icon": "location.north.fill", "label": "Furthest from home",
                               "value": far["city"], "detail": f"{d:,.0f} mi"})
    if biggest and biggest.amount:
        highlights.append({"icon": "creditcard.fill", "label": "Biggest spend", "money": True,
                           "value": _money(biggest.amount, (biggest.currency or "USD").upper()),
                           "detail": biggest.description or "Expense"})

    return {
        "trip_id": trip.id,
        "generated_title": trip.title.removesuffix(" (auto)") if trip.title else "Trip",
        "start_date": _iso(start), "end_date": _iso(end),
        "items": ordered,
        "route": route,
        "travelers": people,
        "highlights": highlights,
        "stats": {
            "days": days, "places": len(cities), "countries": len(countries),
            "flights": len(trip.flights), "rentals": len(rentals), "stays": len(stays),
            "nights": nights_total, "flight_miles": round(flight_miles), "drive_miles": round(drive_miles),
            "distance_miles": round(flight_miles + drive_miles), "travelers": len(people),
            "drives": len(tdrives), "timeline_miles": round(timeline_miles),
            "spend": {k: round(v, 2) for k, v in spend.items()},
            "stay_spend": {k: round(v, 2) for k, v in stay_spend.items()},
            "spend_text": " + ".join(_money(v, c) for c, v in spend.most_common()) if spend else None,
            "cities": sorted(cities),
        },
    }


# --- Edits -----------------------------------------------------------------------------------

def _load(row: Optional[models.TripStory]) -> tuple[list[str], dict[str, dict]]:
    if row is None:
        return [], {}
    try:
        order = json.loads(row.order_json or "[]")
        edits = json.loads(row.items_json or "{}")
    except ValueError:
        return [], {}
    return [k for k in order if isinstance(k, str)], edits if isinstance(edits, dict) else {}


def merge_order(generated: list[str], saved: list[str]) -> list[str]:
    """Saved order for keys that still exist; new keys go right after their chronological
    predecessor (or first, if they come before everything)."""
    alive = set(generated)
    out = [k for k in dict.fromkeys(saved) if k in alive]
    placed = set(out)
    for idx, key in enumerate(generated):
        if key in placed:
            continue
        prev = next((generated[j] for j in range(idx - 1, -1, -1) if generated[j] in placed), None)
        out.insert(out.index(prev) + 1 if prev else 0, key)
        placed.add(key)
    return out


def story_row(db: Session, trip_id: int, user: models.User) -> Optional[models.TripStory]:
    return db.query(models.TripStory).filter_by(trip_id=trip_id, user_id=user.id).first()


def build(db: Session, trip: models.Trip, user: models.User) -> dict[str, Any]:
    story = generate(db, trip, user)
    row = story_row(db, trip.id, user)
    saved_order, edits = _load(row)
    by_key = {i["key"]: i for i in story["items"]}
    order = merge_order([i["key"] for i in story["items"]], saved_order)
    items = []
    for k in order:
        i = dict(by_key[k])
        e = edits.get(k) or {}
        i["hidden"] = bool(e.get("hidden", False))
        i["note"] = e.get("note") or None
        i["photos"] = [p for p in (e.get("photos") or []) if isinstance(p, str)][:MAX_PHOTOS]
        items.append(i)
    story["items"] = items
    story["title"] = (row.title if row and row.title else None) or story["generated_title"]
    story["subtitle"] = row.subtitle if row else None
    story["theme"] = (row.theme if row and row.theme in THEMES else None) or "indigo"
    story["cover_photo"] = row.cover_photo if row else None
    story["edited"] = row is not None
    story["updated_at"] = _iso(row.updated_at) if row else None
    start = datetime.fromisoformat(story["start_date"]) if story.get("start_date") else None
    story["trip_photos"] = photos_mod.story_photos(db, trip, user, items, start)  # your thumbnails, by day
    return story


def save(db: Session, trip: models.Trip, user: models.User, body: dict[str, Any]) -> dict[str, Any]:
    """Replace your edits. Keys that aren't in the story are dropped."""
    current = generate(db, trip, user)
    alive = {i["key"] for i in current["items"]}
    row = story_row(db, trip.id, user)
    if row is None:
        row = models.TripStory(trip_id=trip.id, user_id=user.id)
        db.add(row)
    old_order, old_edits = _load(row)
    if "title" in body:
        row.title = (body.get("title") or "").strip() or None
    if "subtitle" in body:
        row.subtitle = (body.get("subtitle") or "").strip() or None
    if "theme" in body:
        row.theme = body.get("theme") or None
    if "cover_photo" in body:
        row.cover_photo = body.get("cover_photo") or None
    order = body.get("order")
    if order is not None:
        row.order_json = json.dumps([k for k in dict.fromkeys(order) if k in alive])
    elif not old_order:
        row.order_json = json.dumps([])
    items = body.get("items")
    if items is not None:
        clean = {}
        for k, e in items.items():
            if k not in alive or e is None:
                continue
            entry = {"hidden": bool(e.get("hidden", False)),
                     "note": (e.get("note") or "").strip() or None,
                     "photos": list(dict.fromkeys(e.get("photos") or []))}
            if entry["hidden"] or entry["note"] or entry["photos"]:
                clean[k] = entry
        row.items_json = json.dumps(clean)
    row.updated_at = datetime.utcnow()
    db.commit()
    return build(db, trip, user)


def reset(db: Session, trip: models.Trip, user: models.User) -> dict[str, Any]:
    row = story_row(db, trip.id, user)
    if row is not None:
        db.delete(row)
        db.commit()
    return build(db, trip, user)


# --- Year in Travel --------------------------------------------------------------------------

def _days_in_year(ranges: Iterable[tuple[date, date]], year: int) -> int:
    lo, hi = date(year, 1, 1), date(year, 12, 31)
    days: set[date] = set()
    for a, b in ranges:
        a, b = max(a, lo), min(b, hi)
        while a <= b:
            days.add(a)
            a += timedelta(days=1)
    return len(days)


def year_in_travel(db: Session, user: models.User, year: int) -> dict[str, Any]:
    home_code = home_airport(db, user)
    home = airports.lookup(home_code)
    home_city = home[0] if home else None
    flights = [f for f in access.flights(db, user).all() if f.departure_time and f.departure_time.year == year]
    rentals = [r for r in access.rentals(db, user).all() if r.pickup_time and r.pickup_time.year == year]

    ranges: list[tuple[date, date]] = []
    trips = []
    for t in access.trips(db, user).all():
        s = t.start_date or min((f.departure_time for f in t.flights if f.departure_time), default=None)
        e = t.end_date or max((f.arrival_time or f.departure_time for f in t.flights if f.departure_time), default=None) or s
        if not s or not (s.year == year or (e and e.year == year)):
            continue
        trips.append((t, s, e))
        ranges.append((s.date(), (e or s).date()))
    for r in rentals:  # rentals outside any trip still mean a day away
        if r.dropoff_time:
            ranges.append((r.pickup_time.date(), r.dropoff_time.date()))

    visits: Counter = Counter()
    points: dict[str, dict] = {}
    arcs: dict[tuple, dict] = {}
    flight_miles = drive_miles = 0.0
    airlines: Counter = Counter()
    for f in flights:
        flight_miles += _flight_miles(f) or 0
        airlines[f.airline] += 1
        a, b = _place(f.departure_airport), _place(f.arrival_airport)
        for p in (a, b):
            if p and p.get("lat") is not None:
                points.setdefault(p["city"], {**p, "visits": 0})
        if b and b.get("city") and b["city"] != home_city:
            visits[b["city"]] += 1
            points[b["city"]]["visits"] += 1
        if a and b and a.get("lat") is not None and b.get("lat") is not None:
            key = tuple(sorted((a["city"], b["city"])))
            arcs.setdefault(key, {"from": [a["lat"], a["lng"]], "to": [b["lat"], b["lng"]], "count": 0})["count"] += 1
    companies: Counter = Counter()
    for r in rentals:
        drive_miles += _rental_miles(r) or 0
        companies[r.rental_company] += 1
        p = _rental_place(r.pickup_code, r.pickup_location, r.pickup_city, r.pickup_lat, r.pickup_lng)
        if p and p.get("city"):
            if p.get("lat") is not None:
                points.setdefault(p["city"], {**p, "visits": 0})
            if p["city"] != home_city:
                visits[p["city"]] += 1
                if p["city"] in points:
                    points[p["city"]]["visits"] += 1

    year_drives = drives_mod.own(db, user).filter(models.Drive.start_time >= datetime(year, 1, 1),
                                                  models.Drive.start_time < datetime(year + 1, 1, 1)).all()
    timeline_miles = drives_mod.counted_miles(year_drives, rentals)
    drive_miles += timeline_miles

    cities = {c for c in points if c}
    countries = {p["country"] for p in points.values() if p.get("country")}
    longest = max(trips, key=lambda x: ((x[2] or x[1]) - x[1]).days, default=None)
    return {
        "year": year,
        "trips": len(trips),
        "days_away": _days_in_year(ranges, year),
        "flights": len(flights),
        "rentals": len(rentals),
        "cities": len(cities),
        "countries": len(countries),
        "country_codes": sorted(countries),
        "flight_miles": round(flight_miles),
        "drive_miles": round(drive_miles),
        "timeline_drive_miles": round(timeline_miles),  # part of drive_miles: Timeline drives outside rentals
        "drives": len(year_drives),
        "miles": round(flight_miles + drive_miles),
        "around_earth": round((flight_miles + drive_miles) / 24901, 2),
        "top_destinations": [{"city": c, "visits": n} for c, n in visits.most_common(5)],
        "top_airline": airlines.most_common(1)[0][0] if airlines else None,
        "top_rental_company": companies.most_common(1)[0][0] if companies else None,
        "longest_trip": {"title": longest[0].title.removesuffix(" (auto)"), "days": ((longest[2] or longest[1]).date() - longest[1].date()).days + 1} if longest else None,
        "home": {"code": home_code, "city": home_city, "lat": home[2], "lng": home[3]} if home else None,
        "points": sorted(points.values(), key=lambda p: -p["visits"]),
        "arcs": list(arcs.values()),
    }
