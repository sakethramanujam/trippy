#!/usr/bin/env python3
"""Create trips from rental-car history by clustering rentals by date and place.

Every generated trip is clearly marked so it is easy to find and remove:
  * its title ends with " (auto)"
  * its description starts with AUTO_MARKER

Usage (backend must be running):
  python scripts/generate_trips_from_rentals.py            # create trips + link rentals
  python scripts/generate_trips_from_rentals.py --dry-run  # print clusters only
  python scripts/generate_trips_from_rentals.py --delete-auto  # remove all auto trips (rentals are kept)

Only rentals not already attached to a trip are used, so re-running is safe.
No flights or other data are invented; trips contain only the real rentals.
"""
import argparse
import json
import math
import urllib.request
from collections import Counter
from datetime import datetime, timedelta

AUTO_MARKER = "Auto-generated from rental history"
GAP = timedelta(days=2)
NEAR_KM = 150


def call(api, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(api + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def parse(ts):
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "")).replace(tzinfo=None)


def km(a, b):
    (la1, lo1), (la2, lo2) = a, b
    p1, p2 = math.radians(la1), math.radians(la2)
    d = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(d))


def coord(r, side="pickup"):
    la, lo = r.get(f"{side}_lat"), r.get(f"{side}_lng")
    return (la, lo) if la is not None and lo is not None else None


def city(r, side="pickup"):
    c = r.get(f"{side}_city") or ""
    c = c.split(",")[0].strip()
    return c or (r.get(f"{side}_code") or r.get(f"{side}_location") or "").strip() or None


def end_of(r):
    return parse(r.get("dropoff_time")) or parse(r.get("pickup_time")) + timedelta(days=1)


def cluster(rentals):
    rs = sorted((r for r in rentals if not r.get("trip_id") and parse(r.get("pickup_time"))),
                key=lambda r: parse(r["pickup_time"]))
    clusters = []
    for r in rs:
        start = parse(r["pickup_time"])
        c = coord(r)
        cur = clusters[-1] if clusters else None
        if cur and start <= cur["end"] + GAP:
            coords = [x for x in (coord(m) for m in cur["rentals"]) if x] + \
                     [x for x in (coord(m, "dropoff") for m in cur["rentals"]) if x]
            if c is None or not coords or min(km(c, x) for x in coords) <= NEAR_KM:
                cur["rentals"].append(r)
                cur["end"] = max(cur["end"], end_of(r))
                continue
        clusters.append({"rentals": [r], "start": start, "end": end_of(r)})
    return clusters


def title_for(cl):
    places = []
    for r in cl["rentals"]:
        for side in ("pickup", "dropoff"):
            c = city(r, side)
            if c:
                places.append(c)
    if not places:
        name = f"{cl['rentals'][0].get('rental_company', 'Rental')} rental · {cl['start']:%b %Y}"
    else:
        common = [p for p, _ in Counter(places).most_common()]
        ordered = []
        for p in places:
            if p not in ordered:
                ordered.append(p)
        # one-way trips read better as A → B
        first, last = ordered[0], places[-1]
        if first != last and len(cl["rentals"]) == 1:
            name = f"{first} → {last}"
        else:
            name = common[0]
            if len(ordered) > 1 and len(cl["rentals"]) > 1:
                name = f"{common[0]} +{len(ordered) - 1}"
    return f"{name} (auto)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--owner", type=int, default=1)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--delete-auto", action="store_true")
    a = ap.parse_args()

    trips = call(a.api, "GET", "/trips/?limit=1000")
    if a.delete_auto:
        n = 0
        for t in trips:
            if (t.get("description") or "").startswith(AUTO_MARKER):
                call(a.api, "DELETE", f"/trips/{t['id']}")
                n += 1
        print(f"Deleted {n} auto-generated trips (rentals kept, now unlinked).")
        return

    rentals = call(a.api, "GET", "/rental_cars/?limit=1000")
    clusters = cluster(rentals)
    for cl in clusters:
        title = title_for(cl)
        ids = [r["id"] for r in cl["rentals"]]
        print(f"{cl['start']:%Y-%m-%d} → {cl['end']:%Y-%m-%d}  {title:40s} rentals {ids}")
        if a.dry_run:
            continue
        n = len(ids)
        trip = call(a.api, "POST", f"/users/{a.owner}/trips/", {
            "title": title,
            "description": f"{AUTO_MARKER} ({n} rental{'s' if n != 1 else ''}) · safe to delete",
            "start_date": cl["start"].isoformat(),
            "end_date": cl["end"].isoformat(),
        })
        for rid in ids:
            call(a.api, "PATCH", f"/rental_cars/{rid}", {"trip_id": trip["id"]})
    print(f"{'Would create' if a.dry_run else 'Created'} {len(clusters)} trips from {sum(len(c['rentals']) for c in clusters)} rentals.")


if __name__ == "__main__":
    main()
