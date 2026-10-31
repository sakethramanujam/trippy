#!/usr/bin/env python3
"""Import rentals from a Rental Car Tracker export into the Trippy API.

    python scripts/import_rentals.py ~/Downloads/rentals.private.json \
        --api http://127.0.0.1:8000

The export is personal data: keep it OUTSIDE this repo. The script only reads it.

Each rental is upserted with PUT /rental_cars/external/{tracker id}, so running it
again updates rows instead of duplicating them. Stations are geocoded (airport
table first, then OpenStreetMap Nominatim) and a representative car photo is looked
up on Wikipedia. Both lookups are cached next to the input file
(<input>.trippy-cache.json) and can be skipped with --offline.

Standard library only, so it runs from the backend venv or any python3.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "TrippyRentalImport/1.0 (self-hosted travel companion)"

# IATA code -> (lat, lng, city) for airport stations; avoids a network lookup.
AIRPORTS = {
    "PHX": (33.4352, -112.0101, "Phoenix, AZ"), "LAS": (36.0840, -115.1537, "Las Vegas, NV"),
    "SJC": (37.3639, -121.9289, "San Jose, CA"), "LAX": (33.9416, -118.4085, "Los Angeles, CA"),
    "SEA": (47.4502, -122.3088, "SeaTac, WA"), "SFO": (37.6213, -122.3790, "San Francisco, CA"),
    "IAD": (38.9531, -77.4565, "Dulles, VA"), "ORD": (41.9742, -87.9073, "Chicago, IL"),
    "AUS": (30.1975, -97.6664, "Austin, TX"), "BOS": (42.3656, -71.0096, "Boston, MA"),
    "OAK": (37.7126, -122.2197, "Oakland, CA"), "DCA": (38.8512, -77.0402, "Arlington, VA"),
    "JFK": (40.6413, -73.7781, "New York, NY"), "EWR": (40.6895, -74.1745, "Newark, NJ"),
    "DEN": (39.8561, -104.6737, "Denver, CO"), "LHR": (51.4700, -0.4543, "London, UK"),
}
# Location names that mean "this airport" in the source receipts.
AIRPORT_HINTS = {
    "PHOENIX APO": "PHX", "PHX SKY HARBOR": "PHX", "PHXAP": "PHX", "LAS VEGAS APO": "LAS",
    "SAN JOSE APO": "SJC", "LOS ANGELES CA AP": "LAX", "WASH DULLES": "IAD", "OHARE APO": "ORD",
    "AUSTIN AIRPORT": "AUS",
}
COMPANY_NAMES = {"enterprise": "Enterprise", "avis": "Avis", "hertz": "Hertz", "budget": "Budget",
                 "national": "National", "alamo": "Alamo", "sixt": "Sixt", "other": "Other"}
HERTZ_CLASS_CODES = {"A": "Economy", "B": "Compact", "C": "Midsize", "D": "Midsize", "F": "Full Size",
                     "G": "Premium", "L": "SUV", "R": "Minivan"}


def http_json(url: str, method: str = "GET", body: dict | None = None, timeout: float = 15):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "User-Agent": USER_AGENT, "Accept": "application/json",
        **({"Content-Type": "application/json"} if data else {}),
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else None


def clean(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def station_code(stop: dict) -> str | None:
    """IATA code if the station is an airport, else None."""
    code = clean(stop.get("code")).upper()
    if code in AIRPORTS or (len(code) == 3 and code.isalpha()):
        return code
    loc = clean(stop.get("location")).upper()
    m = re.search(r",\s*([A-Z]{3})$", loc)
    if m and m.group(1) in AIRPORTS:
        return m.group(1)
    m = re.search(r"\(([A-Z]{3})\)", loc)
    if m and m.group(1) in AIRPORTS:
        return m.group(1)
    for hint, iata in AIRPORT_HINTS.items():
        if loc.startswith(hint):
            return iata
    return None


def station_city(stop: dict, code: str | None) -> str | None:
    city = clean(stop.get("city"))
    if city:
        return city.title() if city.isupper() else city
    if code and code in AIRPORTS:
        return AIRPORTS[code][2]
    loc = clean(stop.get("location"))
    if not loc:
        return None
    # "Tempe,Q2T" / "Mountain View,V6W" (Avis station ids) / "TEMPE HLE" (Hertz local edition)
    loc = re.sub(r",\s*[A-Z0-9]{3}$", "", loc)
    loc = re.sub(r"\s+(HLE|APO.*|AP)$", "", loc, flags=re.I)
    loc = re.sub(r"^Hertz\s+", "", loc, flags=re.I)
    return loc.title() if loc.isupper() else loc


def tidy_address(addr) -> str:
    a = clean(addr)
    a = re.sub(r"\s*,(\s*,)+", ",", a)  # "Blvd ,, Chicago" -> "Blvd, Chicago"
    a = re.sub(r"\s+,", ",", a)
    return a.strip(" ,")


def station_name(stop: dict) -> str:
    loc = re.sub(r",\s*[A-Z0-9]{3}$", "", clean(stop.get("location")))  # "…Airport,ORD" -> "…Airport"
    addr = tidy_address(stop.get("address"))
    if loc and addr:
        return f"{loc} · {addr}"
    return loc or addr or clean(stop.get("city"))


def tidy_class(text: str | None) -> str | None:
    t = clean(text)
    if not t:
        return None
    if re.search(r"\bor similar\b", t, re.I):
        return None  # Avis "Toyota Camry or similar" is a car, not a class
    t = re.split(r"\s+(?:2/4|\d)\s*door|/Automatic", t, maxsplit=1)[0]
    t = t.replace("Fullsize", "Full Size")
    return t.strip() or None


def iso(dt: str | None) -> str | None:
    dt = clean(dt)
    if not dt:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", dt):
        return dt + "T12:00:00"
    return dt if len(dt) > 16 else dt + ":00"


class Lookups:
    def __init__(self, cache_path: Path, offline: bool):
        self.cache_path = cache_path
        self.offline = offline
        self.cache = {"geo": {}, "photo": {}}
        if cache_path.exists():
            self.cache.update(json.loads(cache_path.read_text()))
        self._last_nominatim = 0.0

    def save(self):
        self.cache_path.write_text(json.dumps(self.cache, indent=1, sort_keys=True))

    def geocode(self, query: str | None):
        if not query:
            return None
        if query in self.cache["geo"]:
            return self.cache["geo"][query]
        if self.offline:
            return None
        wait = 1.1 - (time.time() - self._last_nominatim)  # Nominatim policy: 1 req/s
        if wait > 0:
            time.sleep(wait)
        self._last_nominatim = time.time()
        url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
            {"q": query, "format": "json", "limit": 1, "countrycodes": "us"})
        try:
            hits = http_json(url)
            result = [float(hits[0]["lat"]), float(hits[0]["lon"])] if hits else None
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as exc:
            print(f"  geocode failed for {query!r}: {exc}", file=sys.stderr)
            return None
        self.cache["geo"][query] = result
        return result

    def photo(self, make: str | None, model: str | None):
        if not make or not model:
            return None
        key = f"{make} {model}"
        if key in self.cache["photo"]:
            return self.cache["photo"][key]
        if self.offline:
            return None
        title = urllib.parse.quote(key.replace(" ", "_"))
        try:
            summary = http_json(f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}")
            ok = summary and summary.get("type") == "standard"
            url = ((summary.get("originalimage") or summary.get("thumbnail") or {}).get("source")
                   if ok else None)
            if url and summary.get("thumbnail"):
                url = summary["thumbnail"]["source"]
                url = re.sub(r"/(\d+)px-", "/640px-", url)
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            print(f"  photo lookup failed for {key!r}: {exc}", file=sys.stderr)
            url = None
        self.cache["photo"][key] = url
        return url


def split_or_similar(text: str):
    """'Toyota Camry or similar' -> ('Toyota', 'Camry')."""
    m = re.match(r"^\s*([A-Za-z-]+)\s+(.+?)\s+or similar\s*$", text or "", re.I)
    if not m or m.group(1).lower() == "mystery":
        return None, None
    return m.group(1), re.sub(r"\s+(Hybrid|AWD|EV)$", "", m.group(2))


def to_payload(r: dict, look: Lookups) -> dict:
    v, p, q = r.get("vehicle") or {}, r.get("pickup") or {}, r.get("return") or {}
    make, model = clean(v.get("make")) or None, clean(v.get("model")) or None
    cls_text = clean(v.get("class"))
    similar_make, similar_model = split_or_similar(cls_text)

    if make and model:
        car_model = f"{make} {model}"
    elif make and clean(v.get("description")) and clean(v.get("description")) != make:
        car_model = clean(v.get("description"))
    elif cls_text and re.search(r"or similar", cls_text, re.I):
        car_model = cls_text
    else:
        car_model = make  # may be None

    vehicle_class = tidy_class(cls_text) or HERTZ_CLASS_CODES.get(clean(v.get("classCode")).upper())

    # Return falls back to the pickup station when the receipt didn't record it.
    q_has_place = any(clean(q.get(k)) for k in ("location", "city", "code"))
    q_place = q if q_has_place else p

    p_code, d_code = station_code(p), station_code(q_place)
    p_city, d_city = station_city(p, p_code), station_city(q_place, d_code)

    def coords(stop, code, city):
        if code and code in AIRPORTS:
            return list(AIRPORTS[code][:2])
        addr = tidy_address(stop.get("address"))
        if addr and city and city not in addr:
            addr = f"{addr}, {city}"
        return look.geocode(addr) or look.geocode(city)

    p_ll = coords(p, p_code, p_city)
    d_ll = p_ll if q_place is p else coords(q_place, d_code, d_city)

    mileage = r.get("mileage") or {}
    fuel = r.get("fuel") or {}
    company_key = clean(r.get("company")).lower() or "other"
    pickup_time = iso(p.get("datetime"))
    if not pickup_time:
        return {}
    photo = look.photo(make, model) or look.photo(similar_make, similar_model)

    notes = clean(r.get("notes"))
    fuel_line = " → ".join(x for x in (clean(fuel.get("out")), clean(fuel.get("in"))) if x)
    if fuel_line:
        notes = (notes + "\n" if notes else "") + f"Fuel: {fuel_line}"

    return {
        "rental_company": COMPANY_NAMES.get(company_key, company_key.title()),
        "car_model": car_model,
        "pickup_location": station_name(p) or (p_city or ""),
        "dropoff_location": station_name(q_place) or (d_city or ""),
        "pickup_time": pickup_time,
        "dropoff_time": iso(q.get("datetime")),
        "mileage_driven": float(mileage["driven"]) if mileage.get("driven") is not None else 0.0,
        "confirmation_number": clean(r.get("confirmation")) or None,
        "agreement_number": clean(r.get("agreement")) or None,
        "cost": r.get("total"),
        "currency": clean(r.get("currency")) or "USD",
        "vehicle_class": vehicle_class,
        "fuel_type": "EV" if re.search(r"\bEV\b", clean(v.get("trim")) + " " + clean(v.get("description"))) else None,
        "pickup_odometer": mileage.get("out"),
        "dropoff_odometer": mileage.get("in"),
        "booking_source": "ingestion",
        "vehicle_make": make or similar_make,
        "vehicle_year": v.get("year"),
        "vehicle_color": clean(v.get("color")) or None,
        "license_plate": " ".join(x for x in (clean(v.get("plateState")), clean(v.get("plate"))) if x) or None,
        "photo_url": photo,
        "pickup_code": p_code, "pickup_city": p_city,
        "pickup_lat": p_ll[0] if p_ll else None, "pickup_lng": p_ll[1] if p_ll else None,
        "dropoff_code": d_code, "dropoff_city": d_city,
        "dropoff_lat": d_ll[0] if d_ll else None, "dropoff_lng": d_ll[1] if d_ll else None,
        "date_approx": bool(r.get("dateApprox")),
        "notes": notes or None,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("export", type=Path, help="Rental Car Tracker export JSON (keep it outside the repo)")
    ap.add_argument("--api", default="http://127.0.0.1:8000", help="Trippy API base URL")
    ap.add_argument("--offline", action="store_true", help="skip geocoding and photo lookups")
    ap.add_argument("--include-samples", action="store_true", help="also import sample rentals")
    ap.add_argument("--dry-run", action="store_true", help="print payloads, don't call the API")
    args = ap.parse_args()

    doc = json.loads(args.export.expanduser().read_text())
    rentals = doc["rentals"] if isinstance(doc, dict) else doc
    look = Lookups(args.export.expanduser().with_suffix(".trippy-cache.json"), args.offline)
    api = args.api.rstrip("/")

    created = skipped = 0
    try:
        for r in rentals:
            if r.get("sample") and not args.include_samples:
                skipped += 1
                continue
            payload = to_payload(r, look)
            if not payload:
                print(f"  skip {r.get('id')}: no pickup date", file=sys.stderr)
                skipped += 1
                continue
            ext = r.get("id") or f"{r.get('company')}-{r.get('confirmation') or r.get('agreement')}"
            if args.dry_run:
                print(json.dumps(payload, indent=1))
                continue
            url = f"{api}/rental_cars/external/{urllib.parse.quote(ext, safe='')}"
            http_json(url, method="PUT", body=payload)
            print(f"  ✓ {payload['rental_company']:<10} {payload['pickup_time'][:10]}  {payload.get('car_model') or ''}")
            created += 1
    finally:
        look.save()

    print(f"\nImported {created} rentals ({skipped} skipped) into {api}")
    if not args.dry_run:
        total = http_json(f"{api}/rental_cars/?limit=10000")
        print(f"API now has {len(total)} rentals")
    return 0


if __name__ == "__main__":
    sys.exit(main())
