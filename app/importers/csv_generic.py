"""Any CSV: you pick which column feeds which Trippy field."""
from __future__ import annotations

import csv
import io
import re
from typing import Optional

from .common import ImportError_, airline_name, default_arrival, fmt_day, item, parse_dt
from .flighty import decode

TARGETS = {
    "flight": {
        "required": ["flight_number", "departure_airport", "arrival_airport", "departure_time"],
        "optional": ["airline", "arrival_time", "confirmation_number", "seat", "cabin_class", "cost", "currency"],
    },
    "rental": {
        "required": ["rental_company", "pickup_time"],
        "optional": ["pickup_location", "dropoff_location", "dropoff_time", "car_model", "confirmation_number",
                     "cost", "currency"],
    },
    "lodging": {
        "required": ["name", "check_in"],
        "optional": ["check_out", "address", "confirmation_number", "cost", "currency"],
    },
}
DATE_FIELDS = {"departure_time", "arrival_time", "pickup_time", "dropoff_time", "check_in", "check_out"}
GUESSES = {
    "flight_number": ["flight", "flight number", "flight no", "flight #"],
    "airline": ["airline", "carrier"],
    "departure_airport": ["from", "origin", "departure airport", "dep", "departure"],
    "arrival_airport": ["to", "destination", "arrival airport", "arr", "arrival"],
    "departure_time": ["departure time", "departs", "date", "departure date", "dep time"],
    "arrival_time": ["arrival time", "arrives", "arrival date"],
    "confirmation_number": ["confirmation", "confirmation number", "pnr", "record locator", "booking reference"],
    "seat": ["seat"], "cabin_class": ["cabin", "class", "cabin class"],
    "cost": ["cost", "price", "amount", "total"], "currency": ["currency"],
    "rental_company": ["company", "rental company", "vendor"],
    "pickup_time": ["pickup", "pickup time", "pick up", "pickup date", "start"],
    "dropoff_time": ["dropoff", "return", "drop off", "return date", "dropoff time", "end"],
    "pickup_location": ["pickup location", "location"], "dropoff_location": ["dropoff location", "return location"],
    "car_model": ["car", "vehicle", "model"],
    "name": ["hotel", "property", "name"], "address": ["address"],
    "check_in": ["check in", "check-in", "checkin", "arrival"], "check_out": ["check out", "check-out", "checkout"],
}


def read_rows(data: bytes) -> tuple[list[str], list[dict]]:
    text = decode(data)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    header = [h.strip() for h in (reader.fieldnames or []) if h]
    if not header:
        raise ImportError_("The CSV has no header row")
    rows = [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in reader]
    return header, rows


def suggest(header: list[str], kind: str) -> dict:
    norm = {re.sub(r"[^a-z0-9#]+", " ", h.lower()).strip(): h for h in header}
    out = {}
    for target in TARGETS[kind]["required"] + TARGETS[kind]["optional"]:
        for guess in GUESSES.get(target, []):
            if guess in norm and norm[guess] not in out.values():
                out[target] = norm[guess]
                break
    return out


def describe(data: bytes, kind: str) -> dict:
    header, rows = read_rows(data)
    return {"columns": header, "sample_rows": rows[:5], "row_count": len(rows),
            "targets": TARGETS, "suggested_mapping": suggest(header, kind)}


def _num(v: str) -> Optional[float]:
    v = re.sub(r"[^0-9.\-]", "", v or "")
    try:
        return float(v) if v else None
    except ValueError:
        return None


def parse_csv(data: bytes, kind: str, mapping: dict) -> tuple[list[dict], dict]:
    if kind not in TARGETS:
        raise ImportError_("Pick what the rows are: flight, rental or lodging")
    header, rows = read_rows(data)
    missing = [t for t in TARGETS[kind]["required"] if not mapping.get(t)]
    if missing:
        raise ImportError_("Map a column for: " + ", ".join(missing))
    unknown = [c for c in mapping.values() if c and c not in header]
    if unknown:
        raise ImportError_("Unknown column(s): " + ", ".join(unknown))
    items, stats = [], {"rows": len(rows), "skipped": 0}
    for i, row in enumerate(rows, start=2):
        f, warnings = {}, []
        for target, col in mapping.items():
            if not col or target not in TARGETS[kind]["required"] + TARGETS[kind]["optional"]:
                continue
            raw = row.get(col, "")
            if target in DATE_FIELDS:
                f[target] = parse_dt(raw)
                if raw and f[target] is None:
                    warnings.append(f"Couldn't read {target.replace('_', ' ')} '{raw}'")
            elif target == "cost":
                f[target] = _num(raw)
            else:
                f[target] = raw or None
        if any(f.get(t) in (None, "") for t in TARGETS[kind]["required"]):
            stats["skipped"] += 1
            continue
        f["booking_source"] = "csv"
        if kind == "flight":
            f["airline"] = f.get("airline") or airline_name(re.sub(r"\d.*", "", f["flight_number"]).strip())
            f["departure_airport"] = f["departure_airport"].upper()
            f["arrival_airport"] = f["arrival_airport"].upper()
            f["arrival_time"] = default_arrival(f["departure_time"], f.get("arrival_time"), warnings)
            summary = f"{f['flight_number']} {f['departure_airport']} → {f['arrival_airport']} · {fmt_day(f['departure_time'])}"
        elif kind == "rental":
            f["pickup_location"] = f.get("pickup_location") or ""
            f["dropoff_location"] = f.get("dropoff_location") or f["pickup_location"]
            summary = f"{f['rental_company']} · {fmt_day(f['pickup_time'])}"
        else:
            summary = f"{f['name']} · {fmt_day(f['check_in'])}"
        items.append(item(kind, f, source="csv", ref=f"row {i}", summary=summary, warnings=warnings))
    return items, stats
