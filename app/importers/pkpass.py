"""Apple Wallet boarding passes (.pkpass = zip with pass.json).

Reads the barcode as an IATA Bar Coded Boarding Pass (Resolution 792, "M1…" format) when
present; otherwise falls back to the pass's boardingPass fields and relevantDate. Only the
first flight leg of a multi-leg barcode is used for the airports; every leg becomes an item.
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import date, datetime, timedelta
from typing import Optional

from .common import ImportError_, airline_name, default_arrival, flight_label, fmt_day, item, parse_dt


MAX_PASS_JSON = 1 * 1024 * 1024  # real pass.json files are a few KB
MAX_MEMBERS = 200


def read_pass_json(data: bytes) -> dict:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            infos = z.infolist()
            if len(infos) > MAX_MEMBERS:
                raise ImportError_("That .pkpass has too many files")
            info = next((i for i in infos if i.filename.rsplit("/", 1)[-1] == "pass.json"), None)
            if info is None:
                raise ImportError_("No pass.json inside that .pkpass")
            if info.file_size > MAX_PASS_JSON:
                raise ImportError_("pass.json is too large")
            with z.open(info) as fh:  # don't trust the header size: cap the bytes actually inflated
                raw = fh.read(MAX_PASS_JSON + 1)
            if len(raw) > MAX_PASS_JSON:
                raise ImportError_("pass.json is too large")
    except zipfile.BadZipFile:
        raise ImportError_("That isn't a .pkpass file")
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except ValueError:
        raise ImportError_("pass.json isn't valid JSON")


def parse_bcbp(msg: str) -> list[dict]:
    """Mandatory fields of IATA BCBP (fixed widths). Returns one dict per leg."""
    if not msg or len(msg) < 58 or msg[0] != "M" or not msg[1].isdigit():
        return []
    legs = int(msg[1])
    name = msg[2:22].strip()
    out, pos = [], 23
    for i in range(legs):
        seg = msg[pos:pos + 37]
        if len(seg) < 37:
            break
        leg = {
            "name": name, "pnr": seg[0:7].strip(), "from": seg[7:10].strip(), "to": seg[10:13].strip(),
            "carrier": seg[13:16].strip(), "flight": seg[16:21].strip().lstrip("0"),
            "julian": seg[21:24].strip(), "cabin": seg[24:25].strip(), "seat": seg[25:29].strip().lstrip("0"),
            "sequence": seg[29:34].strip(),
        }
        out.append(leg)
        try:
            cond_len = int(msg[pos + 35:pos + 37], 16)
        except ValueError:
            break
        pos += 37 + cond_len
    return out


def _date_from_julian(julian: str, hint: Optional[datetime]) -> Optional[date]:
    if not julian.isdigit():
        return None
    day = int(julian)
    anchor = (hint or datetime.utcnow()).date()
    best = None
    for year in (anchor.year - 1, anchor.year, anchor.year + 1):
        try:
            d = date(year, 1, 1) + timedelta(days=day - 1)
        except OverflowError:
            continue
        if d.year != year:
            continue
        if best is None or abs((d - anchor).days) < abs((best - anchor).days):
            best = d
    return best


def _fields(p: dict) -> dict[str, str]:
    bp = p.get("boardingPass") or {}
    out = {}
    for group in ("headerFields", "primaryFields", "secondaryFields", "auxiliaryFields", "backFields"):
        for f in bp.get(group) or []:
            key = str(f.get("key", "")).lower()
            label = str(f.get("label", "")).lower()
            val = f.get("value")
            if val is None:
                continue
            out[key] = str(val)
            if label:
                out.setdefault("label:" + label, str(val))
    return out


def _pick(fields: dict, *names: str) -> Optional[str]:
    for n in names:
        for k, v in fields.items():
            if k == n or k == "label:" + n or k.endswith(n):
                return v
    return None


def parse_pkpass(data: bytes) -> tuple[list[dict], dict]:
    p = read_pass_json(data)
    if "boardingPass" not in p:
        raise ImportError_("That Wallet pass isn't a boarding pass")
    fields = _fields(p)
    relevant = parse_dt(p.get("relevantDate")) or parse_dt(p.get("expirationDate"))
    barcodes = list(p.get("barcodes") or []) + ([p["barcode"]] if p.get("barcode") else [])
    legs = []
    for b in barcodes:
        legs = parse_bcbp(str(b.get("message", "")))
        if legs:
            break
    items, warnings = [], []
    org = p.get("organizationName") or ""
    if legs:
        for leg in legs:
            d = _date_from_julian(leg["julian"], relevant)
            dep = relevant if relevant and d and relevant.date() == d else (datetime(d.year, d.month, d.day) if d else relevant)
            w = []
            if dep is None:
                continue
            if not relevant or relevant.date() != dep.date():
                w.append("Departure time not on the pass; only the date is known")
            label = flight_label(leg["carrier"], leg["flight"])
            f = {"airline": org or airline_name(leg["carrier"]), "flight_number": label,
                 "departure_airport": leg["from"], "arrival_airport": leg["to"], "departure_time": dep,
                 "arrival_time": default_arrival(dep, None, w), "seat": leg["seat"] or None,
                 "confirmation_number": leg["pnr"] or None, "booking_source": "wallet",
                 "external_id": f"pkpass:{p.get('serialNumber')}:{leg['from']}{leg['to']}" if p.get("serialNumber") else None}
            items.append(item("flight", f, source="pkpass", ref=p.get("serialNumber"), warnings=w,
                              summary=f"{label} {leg['from']} → {leg['to']} · {fmt_day(dep)}"))
        return items, {"legs": len(legs), "barcode": "bcbp"}
    # No BCBP barcode: use the visible pass fields.
    dep_code = _pick(fields, "origin", "depart", "from")
    arr_code = _pick(fields, "destination", "arrive", "to")
    flight = _pick(fields, "flight", "flightnumber", "flight number")
    if not (dep_code and arr_code and relevant):
        raise ImportError_("Couldn't find the flight on that pass (no IATA barcode, airports or date)")
    w = ["Read from the pass's display fields (no IATA barcode); check the details"]
    m = re.search(r"([A-Z0-9]{2})\s?(\d{1,4})", (flight or "").upper())
    label = flight_label(m.group(1), m.group(2)) if m else (flight or "Flight")
    f = {"airline": org or "Unknown airline", "flight_number": label,
         "departure_airport": dep_code.strip()[:3].upper(), "arrival_airport": arr_code.strip()[:3].upper(),
         "departure_time": relevant, "arrival_time": default_arrival(relevant, None, w),
         "seat": _pick(fields, "seat"), "confirmation_number": _pick(fields, "confirmation", "pnr", "record locator"),
         "booking_source": "wallet",
         "external_id": f"pkpass:{p.get('serialNumber')}" if p.get("serialNumber") else None}
    items.append(item("flight", f, source="pkpass", ref=p.get("serialNumber"), confidence="medium", warnings=w,
                      summary=f"{label} {f['departure_airport']} → {f['arrival_airport']} · {fmt_day(relevant)}"))
    return items, {"legs": 1, "barcode": "none"}
