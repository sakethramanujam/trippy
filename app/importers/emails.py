"""Forwarded confirmation emails (.eml) or pasted text.

- Rental receipts: Rental Car Tracker's parser (templates for Avis, Enterprise, Hertz plus
  generic rules that also read Budget/National-style receipts), mapped with Trippy's own
  rental importer (offline: no geocoding or photo lookups).
- Flights: first the real-layout templates in `airline_templates` (Frontier, American, United,
  Alaska, Delta, Southwest via BCD, Concur, Capital One Travel, StudentUniverse, CheapOair,
  IndiGo, Cleartrip, LY.com, Lufthansa baggage receipts), marked high confidence; then generic
  text heuristics (flight number + airport codes + dates), marked low confidence.
- Hotels: generic heuristics (hotel words + check-in/check-out dates), low confidence.
"""
from __future__ import annotations

import importlib.util
import json
import re
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from functools import lru_cache
from pathlib import Path
from typing import Optional

from . import airline_templates, hotel_templates
from .common import AIRLINES_IATA, AIRLINE_WORDS, ImportError_, airline_name, default_arrival, flight_key, flight_label, fmt_day, item
from .ics import NOT_AIRPORT, ROUTE_RE, PAREN_CODES_RE
from .vendor import receipts_engine

MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
DATE_RES = [
    (re.compile(rf"\b(\d{{4}})-(\d{{2}})-(\d{{2}})\b"), "ymd"),
    (re.compile(rf"\b(?:mon|tue|wed|thu|fri|sat|sun)?[a-z]*,?\s*({MONTHS})[a-z]*\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I), "mdy"),
    (re.compile(rf"\b(\d{{1,2}})\s+({MONTHS})[a-z]*\.?,?\s+(\d{{4}})\b", re.I), "dmy"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "us"),
]
TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\s*([AaPp]\.?[Mm]\.?)?")
FLIGHT_CTX_RE = re.compile(r"\b(?:flight|flt)\s*(?:number|no\.?|#)?\s*:?\s*([A-Z]{2}|[A-Z]\d|\d[A-Z])\s?(\d{1,4})\b", re.I)
FLIGHT_BARE_RE = re.compile(r"\b([A-Z]{2}|[A-Z]\d|\d[A-Z])\s?(\d{1,4})\b")
CONF_RE = re.compile(r"(?:confirmation(?:\s*(?:code|number|#))?|record locator|booking (?:reference|code)|pnr|"
                     r"reservation (?:code|number))\s*[:#]?\s*([A-Z0-9]{5,12})\b", re.I)
HOTEL_RE = re.compile(r"\b(hotel|inn|resort|suites|marriott|hilton|hyatt|sheraton|westin|holiday inn|"
                      r"hampton|courtyard|four seasons|ritz|ihg|booking\.com|expedia|hotels\.com|airbnb|vrbo)\b", re.I)
HOTEL_NAME_RES = [
    re.compile(r"(?:your stay at|stay at|reservation at|booking at|welcome to|booked at)\s+(?:the\s+)?([A-Z][^\n,.!|]{2,70})", re.I),
    re.compile(r"^\s*(?:hotel|property)\s*(?:name)?\s*:\s*([^\n]{3,70})$", re.I | re.M),
]
ADDRESS_RE = re.compile(r"^\s*(?:address|location)\s*:\s*([^\n]{5,120})$", re.I | re.M)


def _mon(s: str) -> int:
    return MONTHS.split("|").index(s[:3].lower()) + 1 if s[:3].lower() != "sep" else 9


def find_dates(text: str) -> list[tuple[int, datetime]]:
    """(position, date) for every date-looking string, in order."""
    out = []
    for rx, kind in DATE_RES:
        for m in rx.finditer(text):
            try:
                if kind == "ymd":
                    d = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                elif kind == "mdy":
                    d = datetime(int(m.group(3)), _mon(m.group(1)), int(m.group(2)))
                elif kind == "dmy":
                    d = datetime(int(m.group(3)), _mon(m.group(2)), int(m.group(1)))
                else:
                    d = datetime(int(m.group(3)), int(m.group(1)), int(m.group(2)))
            except ValueError:
                continue
            if 2000 <= d.year <= 2100:
                out.append((m.start(), d))
    return sorted(out, key=lambda x: x[0])


def _with_time(d: datetime, text: str) -> Optional[datetime]:
    m = TIME_RE.search(text)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    ap = (m.group(3) or "").lower().replace(".", "")
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    if h > 23 or mi > 59:
        return None
    return d.replace(hour=h, minute=mi)


def _times_after(text: str, start: int, limit: int = 400) -> list[datetime]:
    """Dates (with times when given) within `limit` chars after `start`."""
    window = text[start:start + limit]
    dates = find_dates(window)
    out = []
    for pos, d in dates:
        tail = window[pos:pos + 60]
        out.append(_with_time(d, tail) or d)
    if len(out) == 1:
        # Departure and arrival often share one date with two times.
        times = list(TIME_RE.finditer(window[dates[0][0]:]))
        if len(times) >= 2:
            second = _with_time(dates[0][1], window[dates[0][0] + times[1].start():])
            if second:
                if second < out[0]:
                    second += timedelta(days=1)  # "Arrives 2:45 PM (next day)"
                out.append(second)
    return out


def _airports(window: str) -> tuple[Optional[str], Optional[str]]:
    m = ROUTE_RE.search(window)
    if m and m.group(1) not in NOT_AIRPORT and m.group(2) not in NOT_AIRPORT:
        return m.group(1), m.group(2)
    codes = [c for c in PAREN_CODES_RE.findall(window) if c not in NOT_AIRPORT]
    if len(codes) >= 2:
        return codes[0], codes[1]
    return None, None


def _airline_from_text(text: str) -> Optional[str]:
    low = text.lower()
    for word, code in AIRLINE_WORDS.items():
        if word in low:
            return code
    return None


def parse_flights(text: str, subject: str = "") -> list[dict]:
    hint = _airline_from_text(subject + "\n" + text[:2000])
    conf = CONF_RE.search(text)
    hits = list(FLIGHT_CTX_RE.finditer(text))
    if not hits:
        hits = [m for m in FLIGHT_BARE_RE.finditer(text) if m.group(1).upper() in AIRLINES_IATA
                or (hint and m.group(1).upper() == hint)]
    items, seen = [], set()
    for m in hits:
        carrier, number = m.group(1).upper(), m.group(2)
        window = text[max(0, m.start() - 120): m.end() + 400]
        dep, arr = _airports(window)
        if not dep:
            continue
        times = _times_after(text, max(0, m.start() - 120), 520)
        if not times:
            continue
        key = (carrier, number, times[0].date())
        if key in seen:
            continue
        seen.add(key)
        warnings = ["Read from email text; check times and airports"]
        label = flight_label(carrier, number)
        departure = times[0]
        if departure.hour == 0 and departure.minute == 0:
            warnings.append("No departure time found; only the date")
        fields = {"airline": airline_name(carrier), "flight_number": label, "departure_airport": dep,
                  "arrival_airport": arr, "departure_time": departure,
                  "arrival_time": default_arrival(departure, times[1] if len(times) > 1 else None, warnings),
                  "confirmation_number": conf.group(1).upper() if conf else None, "booking_source": "email"}
        items.append(item("flight", fields, source="email", confidence="low", warnings=warnings,
                          summary=f"{label} {dep} → {arr} · {fmt_day(departure)}"))
    return items


def _sent_date(raw: str) -> datetime:
    """The email's Date: header (naive), or now; templates use it to infer years left off dates."""
    m = re.search(r"^Date:\s*(.+)$", raw[:20000], re.M | re.I)
    if m:
        try:
            return parsedate_to_datetime(m.group(1).strip()).replace(tzinfo=None)
        except (TypeError, ValueError, IndexError):
            pass
    return datetime.now().replace(microsecond=0)


def segment_items(segs: list, source_ref: Optional[str] = None) -> list[dict]:
    """Template `Segment`s -> importer items. A booking's printed total goes on its first flight."""
    items, priced = [], set()
    for seg in segs:
        warnings = []
        if seg.arrival is None:
            warnings.append("Arrival time not in this email")
        arrival = default_arrival(seg.departure, seg.arrival, warnings)
        cost = None
        if seg.price is not None and (seg.confirmation, seg.price) not in priced:
            priced.add((seg.confirmation, seg.price))
            cost = seg.price
            if len([x for x in segs if x.confirmation == seg.confirmation]) > 1:
                warnings.append("Price is the whole booking's total, put on its first flight")
        label = flight_label(seg.carrier, seg.number)
        fields = {"airline": airline_name(seg.carrier), "flight_number": label,
                  "departure_airport": seg.origin, "arrival_airport": seg.destination,
                  "departure_time": seg.departure, "arrival_time": arrival,
                  "confirmation_number": seg.confirmation, "cost": cost,
                  "currency": seg.currency or "USD", "seat": seg.seat, "cabin_class": seg.cabin,
                  "status": "Cancelled" if seg.status == "cancelled" else "Scheduled",
                  "booking_source": "email",
                  "external_id": f"email:{seg.confirmation or '-'}:{flight_key(label)}:{seg.origin}:{seg.departure:%Y-%m-%d}"}
        items.append(item("flight", fields, source="email", confidence="high" if not warnings or seg.arrival else "medium",
                          warnings=warnings, ref=source_ref,
                          summary=f"{label} {seg.origin} → {seg.destination} · {fmt_day(seg.departure)}"))
    return items


def parse_template_flights(text: str, subject: str = "", sent: Optional[datetime] = None) -> list[dict]:
    segs = airline_templates.parse_segments(text, sent or datetime.now(), subject)
    return segment_items(segs)


def parse_hotel(text: str, subject: str = "") -> list[dict]:
    head = subject + "\n" + text
    if not HOTEL_RE.search(head):
        return []
    ci = re.search(r"check[- ]?in", text, re.I)
    co = re.search(r"check[- ]?out", text, re.I)
    if not ci:
        return []
    ci_dates = find_dates(text[ci.start(): ci.start() + 120])
    co_dates = find_dates(text[co.start(): co.start() + 120]) if co else []
    if not ci_dates:
        return []
    name = None
    for rx in HOTEL_NAME_RES:
        m = rx.search(head)
        if m:
            name = m.group(1).strip()
            break
    if not name:
        m = re.search(r"^[^\n]*\b(?:hotel|inn|resort|suites|marriott|hilton|hyatt|sheraton|westin)\b[^\n]*$",
                      head, re.I | re.M)
        name = m.group(0).strip()[:70] if m else "Hotel stay"
    name = re.sub(r"^(subject:|re:|fwd?:)\s*", "", name, flags=re.I).strip()
    name = re.split(r"\s+(?:is|has been|was|are)\s+(?:confirmed|booked|reserved)\b|\s+[-–—(|]\s*", name)[0].strip() or "Hotel stay"
    check_in = ci_dates[0][1]
    check_in = _with_time(check_in, text[ci.start() + ci_dates[0][0]: ci.start() + ci_dates[0][0] + 60]) or check_in
    check_out = co_dates[0][1] if co_dates else None
    if check_out:
        check_out = _with_time(check_out, text[co.start() + co_dates[0][0]: co.start() + co_dates[0][0] + 60]) or check_out
    addr = ADDRESS_RE.search(text)
    conf = CONF_RE.search(text)
    fields = {"name": name, "address": addr.group(1).strip() if addr else None, "check_in": check_in,
              "check_out": check_out, "confirmation_number": conf.group(1).upper() if conf else None,
              "booking_source": "email"}
    nights = (check_out.date() - check_in.date()).days if check_out else None
    return [item("lodging", fields, source="email", confidence="low",
                 warnings=["Read from email text; check the hotel name and dates"],
                 summary=f"{name} · {fmt_day(check_in)}" + (f" · {nights} night(s)" if nights else ""))]


@lru_cache(maxsize=1)
def _rules() -> dict:
    return json.loads((Path(receipts_engine.__file__).parent / "rental_rules.json").read_text())


@lru_cache(maxsize=1)
def _rental_mapper():
    """Trippy's own tracker→API mapping (scripts/import_rentals.py), loaded by path."""
    path = Path(__file__).resolve().parents[2] / "scripts" / "import_rentals.py"
    spec = importlib.util.spec_from_file_location("trippy_import_rentals", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def parse_rental(data: bytes, filename: str) -> list[dict]:
    res = receipts_engine.parse_receipt(data, _rules(), filename)
    rental = res["rental"]
    if res["company"] in (None, "", "other") or not (rental.get("pickup") or {}).get("datetime"):
        return []
    if not res["template"] and len(res["found"]) < 4:
        return []
    mod = _rental_mapper()
    payload = mod.to_payload(rental, mod.Lookups(Path("/nonexistent/trippy-cache.json"), offline=True))
    if not payload:
        return []
    payload["booking_source"] = "email"
    payload["external_id"] = receipts_engine.rental_id(rental)
    warnings = []
    if res["missing"]:
        warnings.append("Not found on the receipt: " + ", ".join(res["missing"]))
    if res.get("sample"):
        warnings.append("This is a SAMPLE receipt")
    for k in ("pickup_time", "dropoff_time"):
        if payload.get(k):
            payload[k] = datetime.fromisoformat(payload[k])
    return [item("rental", payload, source="email", confidence="high" if res["template"] else "medium",
                 warnings=warnings, ref=payload["external_id"],
                 summary=f"{payload['rental_company']} · {payload.get('car_model') or 'car'} · {fmt_day(payload['pickup_time'])}")]


def parse_template_stays(text: str, subject: str, sent: Optional[datetime]) -> list[dict]:
    """Hotel / rental-home stays from known templates (Booking.com, Airbnb, Hotels.com, folios, ...)."""
    out = []
    for s in hotel_templates.parse_stays(text, sent, subject):
        f = hotel_templates.to_fields(s)
        warnings = []
        if s.status == "cancelled":
            warnings.append("This booking was cancelled")
        if f["cost"] is None and s.status != "cancelled":
            warnings.append("No total found")
        if (s.rooms or 1) > 1:
            warnings.append(f"Booking covers {s.rooms} rooms")
        when = fmt_day(s.check_in) if s.check_in else "cancelled"
        nights = f" · {s.nights} night{'s' if s.nights != 1 else ''}" if s.nights else ""
        out.append(item("lodging", f, source="email", confidence="high", warnings=warnings, ref=f["external_id"],
                        summary=f"{s.name} · {when}{nights}"))
    return out


def parse_email(data: bytes, filename: str = "pasted.txt") -> tuple[list[dict], dict]:
    if not data.strip():
        raise ImportError_("Nothing to read")
    if filename.lower().endswith(".pdf"):
        raise ImportError_("PDF receipts aren't supported here yet; forward the email or paste its text")
    items = parse_rental(data, filename)
    cands = receipts_engine.extract_candidates(data, filename)
    best = max(cands, key=lambda c: len(c["text"])) if cands else {"text": data.decode("utf-8", "replace"), "subject": ""}
    if not items:
        sent = _sent_date(data.decode("utf-8", "replace"))
        items = parse_template_flights(best["text"], best["subject"], sent)
        # Travel-agency itineraries (Concur/BCD) carry flights and a hotel in one email.
        items += parse_template_stays(best["text"], best["subject"], sent)
    if not items:
        items = parse_flights(best["text"], best["subject"])
    if not items:
        items = parse_hotel(best["text"], best["subject"])
    return items, {"subject": best.get("subject") or None}
