"""Flighty CSV export (Flighty app → Settings → Export → Export Flights).

Column names are taken from third-party importers that read this file (Flighty does not
publish a spec, and this hasn't been checked against a real export yet):
  Date, Airline (ICAO), Flight, From, To (IATA), Dep/Arr Terminal & Gate, Canceled,
  Diverted To, Gate Departure (Scheduled|Actual), Take off (Scheduled|Actual),
  Landing (Scheduled|Actual), Gate Arrival (Scheduled|Actual), Aircraft Type Name,
  Tail Number, PNR, Seat, Seat Type, Cabin Class, Flight Reason, Notes, … Flighty ID columns.
Times are local wall-clock "YYYY-MM-DDTHH:MM" with no zone.
If the header doesn't match, the API answers 400 and the app offers the generic CSV mapper.
"""
from __future__ import annotations

import csv
import io

from .common import ImportError_, airline_name, default_arrival, flight_label, fmt_day, iata_carrier, item, parse_dt

REQUIRED = ("Date", "Airline", "Flight", "From", "To")
CABINS = {"economy": "economy", "premium economy": "premium_economy", "premium_economy": "premium_economy",
          "business": "business", "first": "first"}


def _truthy(v: str) -> bool:
    return (v or "").strip().lower() in {"true", "yes", "1", "y"}


def decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ImportError_("Couldn't read the file's text encoding")


def looks_like_flighty(header: list[str]) -> bool:
    names = {h.strip() for h in header}
    return all(c in names for c in REQUIRED) and any("Flighty ID" in h or h.startswith("Gate Departure") for h in names)


def parse_flighty_csv(data: bytes) -> tuple[list[dict], dict]:
    text = decode(data)
    reader = csv.DictReader(io.StringIO(text))
    header = [h.strip() for h in (reader.fieldnames or [])]
    missing = [c for c in REQUIRED if c not in header]
    if missing:
        raise ImportError_("This doesn't look like a Flighty export (missing columns: " + ", ".join(missing)
                           + "). Use Generic CSV to map the columns yourself.")
    items, stats = [], {"rows": 0, "skipped": 0, "canceled": 0}
    for row in reader:
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        stats["rows"] += 1
        if _truthy(row.get("Canceled", "")):
            stats["canceled"] += 1
            continue
        warnings: list[str] = []
        dep = (parse_dt(row.get("Gate Departure (Actual)")) or parse_dt(row.get("Gate Departure (Scheduled)"))
               or parse_dt(row.get("Take off (Actual)")) or parse_dt(row.get("Take off (Scheduled)"))
               or parse_dt(row.get("Date")))
        if dep is None or not row.get("From") or not row.get("To"):
            stats["skipped"] += 1
            continue
        arr = (parse_dt(row.get("Gate Arrival (Actual)")) or parse_dt(row.get("Gate Arrival (Scheduled)"))
               or parse_dt(row.get("Landing (Actual)")) or parse_dt(row.get("Landing (Scheduled)")))
        to = row.get("Diverted To") or row["To"]
        if row.get("Diverted To"):
            warnings.append(f"Diverted to {row['Diverted To']} (planned {row['To']})")
        carrier = iata_carrier(row.get("Airline"))
        label = flight_label(carrier, row.get("Flight", "")) if row.get("Flight") else carrier or "Flight"
        sched = parse_dt(row.get("Gate Departure (Scheduled)"))
        actual = parse_dt(row.get("Gate Departure (Actual)"))
        delay = max(0, int((actual - sched).total_seconds() // 60)) if sched and actual else 0
        notes = " · ".join(x for x in (row.get("Flight Reason"), row.get("Notes")) if x)
        fields = {
            "airline": airline_name(row.get("Airline")), "flight_number": label,
            "departure_airport": row["From"].upper(), "arrival_airport": to.upper(),
            "departure_time": dep, "arrival_time": default_arrival(dep, arr, warnings),
            "aircraft_model": row.get("Aircraft Type Name") or None, "delay_minutes": delay,
            "status": "Landed" if parse_dt(row.get("Gate Arrival (Actual)")) else "Scheduled",
            "confirmation_number": row.get("PNR") or None, "seat": row.get("Seat") or None,
            "cabin_class": CABINS.get((row.get("Cabin Class") or "").lower().replace("_", " "))
                           or (row.get("Cabin Class") or None),
            "booking_source": "flighty",
            "external_id": f"flighty:{row['Flight Flighty ID']}" if row.get("Flight Flighty ID") else None,
        }
        if fields["arrival_time"] and fields["departure_time"]:
            mins = int((fields["arrival_time"] - dep).total_seconds() // 60)
            if mins > 0:
                fields["duration_minutes"] = mins
        if notes:
            warnings.append(f"Note: {notes}")
        items.append(item("flight", fields, source="flighty", ref=fields["external_id"], warnings=warnings,
                          summary=f"{label} {fields['departure_airport']} → {fields['arrival_airport']} · {fmt_day(dep)}"))
    return items, stats
