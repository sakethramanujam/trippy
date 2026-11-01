"""Template parsers for real airline / travel-agency confirmation emails.

Each parser takes normalized plain text (see `normalize`) plus the email's sent date and
returns a list of `Segment`s. They are written against the layouts these senders actually
use (checked against real messages, anonymized copies live in tests/fixtures/emails/), so
results are marked high confidence. `parse_segments` picks the first template that matches.

Times are local wall-clock times at each airport, like the rest of Trippy.
"""
from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Optional

MONTHS = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}

# City names some templates print instead of codes.
CITY_IATA = {
    "visakhapatnam": "VTZ", "vishakhapatnam": "VTZ", "delhi": "DEL", "new delhi": "DEL", "chennai": "MAA",
    "bengaluru": "BLR", "bangalore": "BLR", "hyderabad": "HYD", "mumbai": "BOM", "kolkata": "CCU",
    "pune": "PNQ", "goa": "GOI", "vijayawada": "VGA", "tirupati": "TIR", "kochi": "COK",
    "san francisco": "SFO", "san jose": "SJC", "oakland": "OAK", "los angeles": "LAX", "austin": "AUS",
    "phoenix": "PHX", "denver": "DEN", "seattle": "SEA", "las vegas": "LAS", "chicago": "ORD",
    "new york": "JFK", "anchorage": "ANC", "salt lake city": "SLC",
}


@dataclass
class Segment:
    carrier: str                    # IATA airline code, e.g. "F9"
    number: str                     # digits only, e.g. "2791"
    origin: str                     # IATA airport
    destination: str
    departure: datetime             # local wall clock at origin
    arrival: Optional[datetime]     # local wall clock at destination
    confirmation: Optional[str] = None
    cabin: Optional[str] = None     # economy / premium_economy / business / first
    seat: Optional[str] = None
    passengers: list[str] = field(default_factory=list)
    price: Optional[float] = None   # whole-booking price as printed; see price_note
    currency: Optional[str] = None
    status: str = "confirmed"       # confirmed / cancelled
    template: str = ""
    operated_by: Optional[str] = None

    @property
    def flight(self) -> str:
        return f"{self.carrier} {self.number}"


# ---------------------------------------------------------------- text helpers

MAX_EMAIL_TEXT = 256 * 1024


def normalize(body: str) -> str:
    """HTML or text email body -> plain text, one visual line per line, no URLs."""
    if len(body) > MAX_EMAIL_TEXT:
        body = body[:MAX_EMAIL_TEXT]
    if re.search(r"<(?:html|body|table|div|td|p|br)\b", body, re.I):
        body = re.sub(r"(?is)<(style|script|head)\b.*?</\1>", " ", body)
        body = re.sub(r"(?i)<br\s*/?>|</(?:p|div|tr|td|th|li|h\d|table)>", "\n", body)
        body = re.sub(r"<[^>]+>", " ", body)
    body = _html.unescape(_html.unescape(body))
    body = body.replace("\u200b", "").replace("\u200c", "").replace("\xa0", " ").replace("\r", "")
    body = re.sub(r"https?://\S+", "", body)
    body = re.sub(r"[ \t]+", " ", body)
    body = re.sub(r" *\n[ \n]*", "\n", body)
    return body.strip()


def _hm(s: str) -> tuple[int, int]:
    m = re.match(r"\s*(\d{1,2})[:.](\d{2})\s*([ap])?\.?\s*m?\.?", s, re.I)
    if not m:
        raise ValueError(s)
    h, mi, ap = int(m.group(1)), int(m.group(2)), (m.group(3) or "").lower()
    if ap == "p" and h < 12:
        h += 12
    if ap == "a" and h == 12:
        h = 0
    return h, mi


def _at(day: datetime, time_s: str) -> datetime:
    h, mi = _hm(time_s)
    return day.replace(hour=h, minute=mi, second=0, microsecond=0)


def _date(s: str, ref: Optional[datetime] = None) -> datetime:
    """Many date shapes; with no year, pick the one nearest after `ref` (the email date)."""
    s = s.strip().replace(",", " ")
    s = re.sub(r"\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?\b", " ", s, flags=re.I)
    s = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", s)
    s = re.sub(r"\s+", " ", s).strip()
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", s)
    if m:
        y = int(m.group(3))
        return datetime(y + 2000 if y < 100 else y, int(m.group(1)), int(m.group(2)))
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.fullmatch(r"(\d{1,2}) ?([A-Za-z]{3})[a-z]* ?(\d{2,4})?", s)          # 02 Apr 19 / 18OCT / 8 Sep 2023
    if m:
        d, mon, y = int(m.group(1)), MONTHS[m.group(2).lower()], m.group(3)
    else:
        m = re.fullmatch(r"([A-Za-z]{3})[a-z]* (\d{1,2})(?: (\d{4}))?", s)      # September 18 2022 / Apr 13
        if not m:
            raise ValueError(f"date? {s!r}")
        mon, d, y = MONTHS[m.group(1).lower()], int(m.group(2)), m.group(3)
    if y:
        y = int(y)
        return datetime(y + 2000 if y < 100 else y, mon, d)
    if ref is None:
        raise ValueError(f"no year in {s!r}")
    cand = datetime(ref.year, mon, d)
    if cand < ref - timedelta(days=60):
        cand = datetime(ref.year + 1, mon, d)
    return cand


def _fix_overnight(dep: datetime, arr: Optional[datetime]) -> Optional[datetime]:
    if arr is not None and arr < dep - timedelta(hours=14):
        return arr + timedelta(days=1)
    return arr


def _money(s: str) -> Optional[float]:
    m = re.search(r"([\d,]+(?:\.\d{1,2})?)", s or "")
    return float(m.group(1).replace(",", "")) if m else None


AIRLINE_CODES = {
    "frontier": "F9", "american": "AA", "united": "UA", "delta": "DL", "alaska": "AS", "southwest": "WN",
    "jetblue": "B6", "spirit": "NK", "lufthansa": "LH", "singapore": "SQ", "air india": "AI", "indigo": "6E",
    "qatar": "QR", "emirates": "EK", "british airways": "BA", "air canada": "AC", "hawaiian": "HA",
    "skywest": "OO", "airasia": "I5", "vistara": "UK", "turkish": "TK", "ita airways": "AZ", "klm": "KL",
    "air france": "AF", "swiss": "LX", "austrian": "OS", "condor": "DE", "eurowings": "EW",
}


def _carrier_code(name: str) -> Optional[str]:
    low = name.lower().strip()
    if re.fullmatch(r"[a-z0-9]{2}", low):
        return low.upper()
    for k, v in AIRLINE_CODES.items():
        if low.startswith(k):
            return v
    return None


def _cabin(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    low = s.lower()
    if "premium" in low:
        return "premium_economy"
    if "business" in low or "polaris" in low:
        return "business"
    if "first" in low:
        return "first"
    if any(w in low for w in ("economy", "coach", "main", "basic", "standard")):
        return "economy"
    return None


# ---------------------------------------------------------------- templates

def frontier(t: str, sent: datetime) -> list[Segment]:
    """Frontier 'Your Flight Confirmation Code XXXXXX' purchase/itinerary emails (2022-2026 layouts)."""
    m = re.search(r"confirmation code is:\s*([A-Z0-9]{6})", t)
    if not m or "FRONTIER" not in t.upper():
        return []
    conf = m.group(1)
    paid = re.search(r"AMOUNT PAID:\s*\$?([\d,.]+)", t)
    pax_part = re.split(r"\nPASSENGERS\n", t, maxsplit=1)
    pax = []
    if len(pax_part) > 1:
        pax = re.findall(r"^\d+ ?- ([A-Za-z][A-Za-z .'-]+)$", re.split(r"\n(?:SERVICES|BUNDLES|BUNDLE IT)\n", pax_part[1])[0], re.M)
    seats: dict[tuple[str, str], str] = {}
    for sm in re.finditer(r"SEATS - ([A-Z]{3}) to ([A-Z]{3})\n1 ?- [^\n]+\nSeat Assignment: (\w+)", t):
        seats[(sm.group(1), sm.group(2))] = sm.group(3)
    out = []
    for jm in re.finditer(r"(?:DEPARTING|RETURNING) FLIGHT ([\d\s&]+?)\n[^\n]*\(([A-Z]{3})\) to [^\n]*\(([A-Z]{3})\)\n"
                          r"Depart: ([\d/]+) ([\d:]+ [AP]M) \| Arrive: ([\d/]+) ([\d:]+ [AP]M)", t, re.I):
        numbers = re.findall(r"\d+", jm.group(1))
        block = t[jm.end(): jm.end() + 900]
        block = re.split(r"(?i)(?:DEPARTING|RETURNING) FLIGHT|PASSENGERS|PURCHASE SUMMARY", block)[0]
        legs = re.findall(r"^([A-Z]{3}) to ([A-Z]{3})\nDepart: ([\d/]+) ([\d:]+ [AP]M) \| Arrive: ([\d/]+) ([\d:]+ [AP]M)", block, re.M)
        if not legs:
            legs = [(jm.group(2), jm.group(3), jm.group(4), jm.group(5), jm.group(6), jm.group(7))]
        for i, (o, d, dd, dt, ad, at) in enumerate(legs):
            num = numbers[i] if i < len(numbers) else numbers[-1]
            out.append(Segment("F9", num, o, d, _at(_date(dd), dt), _at(_date(ad), at), conf, "economy",
                               seats.get((o, d)), pax, _money(paid.group(1)) if paid else None, "USD",
                               template="frontier"))
    return out


def frontier_checkin(t: str, sent: datetime) -> list[Segment]:
    """Frontier 'It's time to check in' emails: the only record for some bookings."""
    m = re.search(r"Your confirmation code: ([A-Z0-9]{6})", t)
    if not m or "Frontier" not in t:
        return []
    out = []
    for fm in re.finditer(r"(?:Departing|Returning) Flight (\d{1,4})\n([A-Z][a-z]{2})\.? (\d{1,2}), (\d{4})\n([A-Z]{3})\n"
                          r"(\d{1,2}:\d{2} [AP]M)\n([A-Z]{3})\n(\d{1,2}:\d{2} [AP]M)", t):
        day = _date(f"{fm.group(3)} {fm.group(2)} {fm.group(4)}")
        dep = _at(day, fm.group(6))
        out.append(Segment("F9", fm.group(1), fm.group(5), fm.group(7), dep, _fix_overnight(dep, _at(day, fm.group(8))),
                           m.group(1), "economy", template="frontier_checkin"))
    return out


def american(t: str, sent: datetime) -> list[Segment]:
    """American Airlines 'Your trip confirmation (XXX - YYY)' receipts (2021-2026 layouts)."""
    m = re.search(r"(?:Record Locator|Confirmation code):\s*([A-Z0-9]{6})", t, re.I)
    if not m or "American" not in t:
        return []
    conf = m.group(1).upper()
    paid = re.search(r"Total (?:cost|paid)\s*\$([\d,.]+)", t)
    out = []
    # Date line, then ORIG / DEST / dep time / AM|PM / arr time / AM|PM / city / city / AA nnnn
    rx = re.compile(r"(?:^|\n)(?:[A-Z][a-z]+day, )?([A-Z][a-z]+ \d{1,2}, \d{4})\n([A-Z]{3})\n([A-Z]{3})\n"
                    r"(\d{1,2}:\d{2})\n?\s*([AP]M)\n(\d{1,2}:\d{2})\n?\s*([AP]M)\n[^\n]+\n[^\n]+\n(AA|[A-Z0-9]{2}) (\d{1,4})")
    for fm in rx.finditer(t):
        day = _date(fm.group(1))
        dep = _at(day, f"{fm.group(4)} {fm.group(5)}")
        arr = _fix_overnight(dep, _at(day, f"{fm.group(6)} {fm.group(7)}"))
        tail = t[fm.end(): fm.end() + 300]
        seat = re.search(r"Seat:\s*\n?(\d{1,2}[A-K])\b", tail)
        cls = re.search(r"Class:\s*\n?([A-Za-z ]+)", tail)
        out.append(Segment(fm.group(8), fm.group(9), fm.group(2), fm.group(3), dep, arr, conf,
                           _cabin(cls.group(1)) if cls else None, seat.group(1) if seat else None, [],
                           _money(paid.group(1)) if paid else None, "USD", template="american"))
    # 2024+ layout: date / ORIG / city / time / AA nnn / DEST / city / time
    rx2 = re.compile(r"\n(?:[A-Z][a-z]+day, )?([A-Z][a-z]+ \d{1,2}, \d{4})\n([A-Z]{3})\n[^\n]+\n(\d{1,2}:\d{2} [AP]M)\n"
                     r"([A-Z0-9]{2}) (\d{1,4})\n(?:(?:Terminal|Gate):[^\n]*\n)*([A-Z]{3})\n[^\n]+\n(\d{1,2}:\d{2} [AP]M)")
    for fm in ([] if out else rx2.finditer(t)):
        day = _date(fm.group(1))
        dep = _at(day, fm.group(3))
        arr = _fix_overnight(dep, _at(day, fm.group(7)))
        tail = t[fm.end(): fm.end() + 300]
        seat = re.search(r"Seat:\s*\n?(\d{1,2}[A-K])\b", tail)
        cls = re.search(r"Class:\s*\n?([A-Za-z ]+)", tail)
        out.append(Segment(fm.group(4), fm.group(5), fm.group(2), fm.group(6), dep, arr, conf,
                           _cabin(cls.group(1)) if cls else None, seat.group(1) if seat else None, [],
                           _money(paid.group(1)) if paid else None, "USD", template="american"))
    return out


def aa_calendar(t: str, sent: datetime) -> list[Segment]:
    """The calendar.ics American attaches to 'trip details' emails."""
    m = re.search(r"Record Locator: ([A-Z0-9]{6})", t)
    if not m:
        return []
    out = []
    for fm in re.finditer(r"Flight (\d{1,4})[\s\\n]*Depart: ([A-Z]{3}) - [^\n]*? on \w{3} (\d{1,2} \w{3} \d{4}) at (\d{1,2}:\d{2}[AP]M)"
                          r"[\s\\n]*Arrive: ([A-Z]{3}) - [^\n]*? on \w{3} (\d{1,2} \w{3} \d{4}) at (\d{1,2}:\d{2}[AP]M)", t):
        tail = t[fm.end(): fm.end() + 250]
        trav = re.search(r"Traveler Information: ([A-Z ,.'-]+?) - (\w+) - (\d{1,2}[A-K])", tail)
        out.append(Segment("AA", fm.group(1), fm.group(2), fm.group(5), _at(_date(fm.group(3)), fm.group(4)),
                           _at(_date(fm.group(6)), fm.group(7)), m.group(1), _cabin(trav.group(2)) if trav else None,
                           trav.group(3) if trav else None, [trav.group(1).title()] if trav else [], template="aa_calendar"))
    return out


def sabre_reservation(t: str, sent: datetime) -> list[Segment]:
    """Agency 'Travel Reservation to CITY' emails (StudentUniverse; Sabre Virtually There layout)."""
    if "Reservation code:" not in t or "Flight Number" not in t:
        return []
    conf = re.search(r"Reservation code:\s*([A-Z0-9]{6})", t).group(1)
    pax = re.search(r"Passenger\(s\):\s*\n?([A-Z/ ]+)", t)
    names = []
    if pax:
        last, _, first = pax.group(1).partition("/")
        names = [f"{first.strip().title()} {last.strip().title()}".strip()]
    out = []
    for fm in re.finditer(r"\n([A-Z][A-Z .]+?) ([A-Z0-9]{2})\s*\n?Flight Number (\d{1,4})", t):
        blk = t[fm.end(): fm.end() + 1200]
        blk = blk.split("Flight Number")[0]
        days = re.findall(r"(?:[A-Z][a-z]+day), (\d{1,2} [A-Z][a-z]+)", blk)
        dep = re.search(r"Departure:\s*\n?([A-Z]{3}) [^\n]*\n(\d{1,2}:\d{2}[AP]M)", blk)
        arr = re.search(r"Arrival:\s*\n?([A-Z]{3}) [^\n]*\n(\d{1,2}:\d{2}[AP]M)(\s*\+1 day)?", blk)
        if not (days and dep and arr):
            continue
        d0 = _date(days[0], sent)
        d1 = _date(days[1], sent) if len(days) > 1 else (d0 + timedelta(days=1) if arr.group(3) else d0)
        cabin = re.search(r"Cabin:\s*\n?([^\n]+)", blk)
        seat = re.search(r"Seat\(s\):\s*\n(\d{1,2}[A-K])\b", blk)
        airline_conf = re.search(r"Confirmation# ([A-Z0-9]{6})", blk)
        op = re.search(r"Operated by: /?([^\n]+)", blk)
        out.append(Segment(fm.group(2), fm.group(3), dep.group(1), arr.group(1), _at(d0, dep.group(2)), _at(d1, arr.group(2)),
                           airline_conf.group(1) if airline_conf else conf, _cabin(cabin.group(1)) if cabin else None,
                           seat.group(1) if seat else None, names, template="sabre",
                           operated_by=op.group(1).strip() if op else None))
    return out


def indigo(t: str, sent: datetime) -> list[Segment]:
    """IndiGo 'Your IndiGo Itinerary - PNR' emails (one-line and one-cell-per-line layouts)."""
    m = re.search(r"(?:Booking Reference|PNR/Booking Ref\.):\s*\n?\s*([A-Z0-9]{6})", t)
    if not m or "IndiGo" not in t:
        return []
    flat = re.sub(r"\s*\n\s*", " ", t)
    pax = re.findall(r"\d\. (M(?:r|s|rs)\. [A-Za-z ]+?)(?= \d\. | IndiGo| Check-in| Flight)", flat)
    total = re.search(r"Total Fare (?:INR )?([\d,.]+)", flat)
    out = []
    rx = re.compile(r"(\d{2} [A-Z][a-z]{2} \d{2}) ([A-Za-z ]+?)(?: \(T ?\d\))? (\d{2}:\d{2}) (6E \d{1,4}) \( ?[A-Z0-9]+\) "
                    r"(\d{2}:\d{2}) ([A-Za-z ]+?)(?: \(T ?\d\))? (\d{2}:\d{2})")
    for fm in rx.finditer(flat):
        day = _date(fm.group(1))
        o, d = CITY_IATA.get(fm.group(2).strip().lower()), CITY_IATA.get(fm.group(6).strip().lower())
        if not (o and d):
            continue
        dep = _at(day, fm.group(3))
        out.append(Segment("6E", fm.group(4).split()[1], o, d, dep, _fix_overnight(dep, _at(day, fm.group(7))), m.group(1),
                           "economy", None, [p.split(". ", 1)[1].title() for p in pax], _money(total.group(1)) if total else None,
                           "INR", template="indigo"))
    return out


def cleartrip(t: str, sent: datetime) -> list[Segment]:
    """Cleartrip 'Ticket for X - Y flight -- Trip ID n' emails."""
    trip = re.search(r"Trip ID (?:is\s*\n)?(\d{9,})", t)
    if not trip or "cleartrip" not in t.lower():
        return []
    pnrs = re.findall(r"PNR: ([A-Z0-9]{6})", t)
    total = re.search(r"Total charge\s*\nRs\. ([\d,]+)", t)
    out = []
    for i, fm in enumerate(re.finditer(r"\n([A-Z0-9]{2}) (\d{1,4})\n([A-Za-z ]+?) → ([A-Za-z ]+?)(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun), (\d{1,2} \w{3} \d{4})\n"
                                       r"(\d{2}:\d{2}) — (\d{2}:\d{2})", t)):
        day = _date(fm.group(5))
        dep = _at(day, fm.group(6))
        out.append(Segment(fm.group(1), fm.group(2), CITY_IATA.get(fm.group(3).lower(), fm.group(3)),
                           CITY_IATA.get(fm.group(4).lower(), fm.group(4)), dep, _fix_overnight(dep, _at(day, fm.group(7))),
                           pnrs[i] if i < len(pnrs) else trip.group(1), "economy", None, [],
                           _money(total.group(1)) if total else None, "INR", template="cleartrip"))
    return out


def cheapoair(t: str, sent: datetime) -> list[Segment]:
    """CheapOair 'AIR TICKET NUMBER & AIRLINE CONFIRMATION' emails."""
    if "CheapOair" not in t:
        return []
    total = re.search(r"Total Booking Charges\s*\n\$ ?([\d,.]+)", t)
    names = re.findall(r"\n\d\n[A-Z0-9]{2}-[A-Z0-9]{6}\n([A-Za-z ]+)\n([A-Za-z ]+)\n(?:Male|Female)", t)
    out = []
    rx = re.compile(r"\n([A-Z][A-Za-z ]+?)\nFlight (\d{1,4})\n.*?\n(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun), (\w{3} \d{1,2}, \d{4})\n[^\n]+\n"
                    r"([A-Z]{3}) - (\d{1,2}:\d{2} [ap]m)\n[^\n]+\n([A-Z]{3}) - (\d{1,2}:\d{2} [ap]m)\n(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun), (\w{3} \d{1,2}, \d{4})", re.S)
    for fm in rx.finditer(t):
        if fm.group(0).count("\nFlight ") > 1:
            continue
        conf = re.search(r"Airline Confirmation:\s*\n([A-Z0-9]{6})", t[fm.end(): fm.end() + 200])
        code = {"frontier airlines": "F9", "american airlines": "AA", "united airlines": "UA", "delta air lines": "DL",
                "alaska airlines": "AS", "southwest airlines": "WN", "jetblue airways": "B6", "spirit airlines": "NK"}.get(fm.group(1).lower())
        if not code:
            continue
        out.append(Segment(code, fm.group(2), fm.group(4), fm.group(6), _at(_date(fm.group(3)), fm.group(5)),
                           _at(_date(fm.group(8)), fm.group(7)), conf.group(1) if conf else None, "economy", None,
                           [f"{a} {b}".strip() for a, b in names], _money(total.group(1)) if total else None, "USD",
                           template="cheapoair"))
    return out


def concur(t: str, sent: datetime) -> list[Segment]:
    """SAP Concur 'Concur Itinerary' / trip-approval emails."""
    if "Concur" not in t and "Agency Record Locator" not in t:
        return []
    out = []
    for fm in re.finditer(r"Flight [^\n]*\(([A-Z]{3})\) to [^\n]*\(([A-Z]{3})\)\n", t):
        blk = t[fm.end(): fm.end() + 900].split("\nFlight ")[0]
        nm = re.match(r"([A-Za-z][A-Za-z .]+?) (\d{1,4})\n", blk)
        num = (_carrier_code(nm.group(1)), nm.group(2).lstrip("0")) if nm else None
        op = re.search(r"Operated by: ([^\n]+)", blk)
        when = re.search(r"leaves on (\w{3} \d{1,2})(?: and arrives on (\w{3} \d{1,2}))?", blk)
        dep = re.search(r"Departure: (\d{1,2}:\d{2} [AP]M)", blk)
        arr = re.search(r"Arrival: (\d{1,2}:\d{2} [AP]M)", blk)
        if not (dep and arr):
            continue
        hdr = t[max(0, fm.start() - 300): fm.start()]
        day = re.findall(r"(\w+day, \w+ \d{1,2}, \d{4}|\d{2}/\d{2}/\d{4})", hdr)
        if when:
            d0 = _date(when.group(1), sent)
            d1 = _date(when.group(2), sent) if when.group(2) else d0
        elif day:
            d0 = d1 = _date(day[-1].split(", ", 1)[-1])
        else:
            continue
        conf = re.search(r"Confirmation: ([A-Z0-9]{6})", blk)
        cabin = re.search(r"Cabin: (\w+)", blk)
        seat = re.search(r"Seat:\s*(\d{1,2}[A-K])\b", blk)
        if not num or not num[0]:
            continue
        out.append(Segment(num[0], num[1], fm.group(1), fm.group(2),
                           _at(d0, dep.group(1)), _at(d1, arr.group(1)), conf.group(1) if conf else None,
                           _cabin(cabin.group(1)) if cabin else None, seat.group(1) if seat else None, [],
                           template="concur", operated_by=op.group(1).strip() if op else None))
    return out



def united_receipt(t: str, sent: datetime) -> list[Segment]:
    """United 'eTicket Itinerary and Receipt for Confirmation XXXXXX'."""
    m = re.search(r"Confirmation Number:\s*([A-Z0-9]{6})", t)
    if not m or "United" not in t:
        return []
    total = re.search(r"\nTotal:\s*(?:[\d,]+ miles \+ )?([\d,.]+) ([A-Z]{3})", t)
    seats = dict(((a, b), c) for a, b, c in re.findall(r"([A-Z]{3})-([A-Z]{3}) (\d{1,2}[A-K])\b", t))
    pax = [n.replace("/", " ").title() for n in re.findall(r"Traveler Details\n([A-Z]+/[A-Z ]+)", t)]
    out = []
    for fm in re.finditer(r"Flight \d+ of \d+ ([A-Z0-9]{2})(\d{1,4}) Class: ([^\n(]+)(?:\([A-Z]\))?\n"
                          r"\w{3}, (\w{3} \d{1,2}, \d{4}) \w{3}, (\w{3} \d{1,2}, \d{4})\n"
                          r"(\d{1,2}:\d{2} [AP]M)(?: -->)? (\d{1,2}:\d{2} [AP]M)[^\n]*\n.*?\(([A-Z]{3})\).*?\(([A-Z]{3})\)", t):
        o, d = fm.group(8), fm.group(9)
        out.append(Segment(fm.group(1), fm.group(2), o, d, _at(_date(fm.group(4)), fm.group(6)),
                           _at(_date(fm.group(5)), fm.group(7)), m.group(1), _cabin(fm.group(3)),
                           seats.get((o, d)), pax, _money(total.group(1)) if total else None,
                           total.group(2) if total else None, template="united_receipt"))
    return out


def ly_itinerary(t: str, sent: datetime) -> list[Segment]:
    """LY.com (Tongcheng) English ITINERARY emails."""
    m = re.search(r"AIRLINE BOOKING REFERENCE : ([A-Z0-9]{5,8})", t)
    if not m:
        return []
    total = re.search(r"TOTAL : ([A-Z]{3})([\d,.]+)", t)
    name = re.search(r"SURNAME : ([A-Z ]+)\nGIVEN NAME : ([A-Z ]+)", t)
    out = []
    for fm in re.finditer(r"-([A-Z]{3})/[^\n]*-([A-Z]{3})\n([A-Z0-9]{2})(\d{1,4})\n(?:\(Operated by:\s*([A-Z0-9]{2})\)\n)?"
                          r"([A-Za-z ]+)\n(\w{3} \d{1,2}, \d{4})\n(\d{1,2}:\d{2})\n(\d{1,2}:\d{2})\n(\w+)", t):
        day = _date(fm.group(7))
        dep = _at(day, fm.group(8))
        out.append(Segment(fm.group(3), fm.group(4), fm.group(1), fm.group(2), dep, _fix_overnight(dep, _at(day, fm.group(9))),
                           m.group(1), _cabin(fm.group(6)), None,
                           [f"{name.group(2).title()} {name.group(1).title()}"] if name else [],
                           _money(total.group(2)) if total else None, total.group(1) if total else None,
                           "cancelled" if fm.group(10).upper() in ("XX", "CANCELLED") else "confirmed",
                           template="ly_itinerary", operated_by=fm.group(5)))
    return out

def bcd_travel(t: str, sent: datetime) -> list[Segment]:
    """BCD Travel 'Travel Receipt / Travel Itinerary' emails (corporate agency)."""
    if "BCD" not in t or "Travel Summary" not in t:
        return []
    loc = re.search(r"Agency Record Locator\n(.+?) ([A-Z0-9]{6})\n", t)
    total = re.search(r"Total Amount: ([\d,.]+) ([A-Z]{3})", t)
    names = [loc.group(1).title()] if loc else []
    out = []
    rx = re.compile(r"(\d{2}/\d{2}/\d{4}) ([A-Z]{3})-([A-Z]{3}) ([A-Z0-9]{2}) (\d{1,4}) (\w+) "
                    r"(\d{1,2}:\d{2} [AP]M)/(\d{1,2}:\d{2} [AP]M) ([A-Za-z ]+)/")
    for m in rx.finditer(t):
        day = _date(m.group(1))
        dep = _at(day, m.group(7))
        airline_loc = re.search(rf"{m.group(4)}{m.group(5)} Airline Record Locator ([A-Z0-9]{{6}})", t)
        out.append(Segment(m.group(4), m.group(5), m.group(2), m.group(3), dep, _fix_overnight(dep, _at(day, m.group(8))),
                           airline_loc.group(1) if airline_loc else (loc.group(2) if loc else None),
                           _cabin(m.group(9)), None, names,
                           _money(total.group(1)) if total else None, total.group(2) if total else None,
                           "cancelled" if m.group(6).lower().startswith("cancel") else "confirmed", template="bcd"))
    return out


def capital_one(t: str, sent: datetime) -> list[Segment]:
    """Capital One Travel 'View your Capital One Travel Confirmation' flight emails."""
    if "Capital One Travel confirmation code" not in t:
        return []
    out = []
    conf = None
    m = re.search(r"Here.s your [A-Za-z .]+ confirmation code: ([A-Z0-9]{6})\b", t)
    if m:
        conf = m.group(1)
    for leg in re.finditer(r"\n(?:Outbound|Return) to [^\n]+\n([^\n]+)\n([A-Z][a-z]+ \d{1,2}, \d{4})\n(.*?)(?=\n(?:Outbound|Return) to |\nItinerary Within|\Z)", t, re.S):
        cabin, day = leg.group(1), _date(leg.group(2))
        cursor = None
        for f in re.finditer(r"([A-Za-z .]+) - ([A-Z0-9]{2})(\d{1,4})\n[^\n]+\n([A-Z]{3})\n(\d{1,2}:\d{2} [ap]\.m\.)\n\[?\n?[^\n]*\n[^\n]+\n([A-Z]{3})\n(\d{1,2}:\d{2} [ap]\.m\.)", leg.group(3)):
            dep = _at(day, f.group(5))
            if cursor and dep < cursor:
                dep += timedelta(days=1)
            arr = _at(dep, f.group(7))
            if arr < dep:
                arr += timedelta(days=1)
            cursor = arr
            out.append(Segment(f.group(2), f.group(3), f.group(4), f.group(6), dep, arr, conf, _cabin(cabin), None, [],
                               template="capital_one"))
    return out


def frontier_2026(t: str, sent: datetime) -> list[Segment]:
    """Frontier booking confirmation, 2026 layout ('Departing Flight: September 22, 2026 / Flight / #3439')."""
    if "Frontier" not in t or "Confirmation Code" not in t:
        return []
    conf = re.search(r"Confirmation Code\n([A-Z0-9]{6})", t)
    total = re.search(r"\nTotal \$?([\d,.]+)", t)
    pax = re.search(r"Passenger Details\n([^\n]+)", t)
    out = []
    for m in re.finditer(r"(?:Departing|Returning) Flight: ([A-Z][a-z]+ \d{1,2}, \d{4})\n(.*?)(?=(?:Departing|Returning) Flight: |Passenger Details|\Z)", t, re.S):
        day = _date(m.group(1))
        cursor = None
        for f in re.finditer(r"Flight\n#(\d{1,4})\nDeparts\n([A-Z]{3})\n(\d{1,2}:\d{2} [AP]M)\n[^\n]+\n\[?\n?Arrives\n([A-Z]{3})\n(\d{1,2}:\d{2} [AP]M)", m.group(2)):
            dep = _at(day, f.group(3))
            if cursor and dep < cursor:
                dep += timedelta(days=1)
            arr = _at(dep, f.group(5))
            if arr < dep:
                arr += timedelta(days=1)
            cursor = arr
            out.append(Segment("F9", f.group(1), f.group(2), f.group(4), dep, arr, conf.group(1) if conf else None, "economy",
                               None, [pax.group(1).strip().title()] if pax else [],
                               _money(total.group(1)) if total else None, "USD" if total else None, template="frontier_2026"))
    return out


def alaska_receipt(t: str, sent: datetime) -> list[Segment]:
    """Alaska Airlines 'Your confirmation receipt: XXXXXX' emails."""
    m = re.search(r"Confirmation code:\n([A-Z]{6})", t)
    if not m or "Alaska" not in t:
        return []
    total = re.search(r"Total charges for air travel \$([\d,.]+)", t)
    out = []
    for f in re.finditer(r"\n([A-Z][A-Za-z ]+Airlines)\nFlight (\d{1,4})\n[^\n]*\nTraveler\(s\)\n([^\n]+)\nSeat: ?([0-9]{1,2}[A-K])? ?Class: ([^\n]+)\n"
                         r"[A-Z][a-z]{2}, ([A-Z][a-z]{2} \d{1,2})\n(\d{1,2}:\d{2} [AP]M)\n([A-Z]{3})\n[^\n]+\n(?:\[\n)*"
                         r"[A-Z][a-z]{2}, ([A-Z][a-z]{2} \d{1,2})\n(\d{1,2}:\d{2} [AP]M)\n([A-Z]{3})", t):
        dep = _at(_date(f.group(6), sent), f.group(7))
        arr = _at(_date(f.group(9), sent), f.group(10))
        out.append(Segment(_carrier_code(f.group(1)) or "AS", f.group(2), f.group(8), f.group(11), dep, arr, m.group(1),
                           _cabin(f.group(5)), f.group(4), [f.group(3).strip()],
                           _money(total.group(1)) if total else None, "USD" if total else None, template="alaska_receipt"))
    return out


def alaska_schedule_change(t: str, sent: datetime) -> list[Segment]:
    """Alaska 'Schedule Change Alert': only the new flights (above 'Previous Flight Information')."""
    if "Schedule" not in t and "schedule" not in t:
        return []
    conf = re.search(r"confirmation code ([A-Z]{6})", t)
    if not conf or "Alaska" not in t:
        return []
    cur = t.split("Previous Flight Information")[0]
    out = []
    for f in re.finditer(r"([A-Z][A-Za-z ]+Airlines), Flight (\d{1,4}), operated by ([^\n]+)\nDeparting [^\n]*\(([A-Z]{3})\)\n"
                         r"[A-Z][a-z]+, ([A-Z][a-z]+ \d{1,2}), (\d{1,2}:\d{2} [ap]m)\nArriving [^\n]*\(([A-Z]{3})\)\n"
                         r"[A-Z][a-z]+, ([A-Z][a-z]+ \d{1,2}), (\d{1,2}:\d{2} [ap]m)", cur):
        out.append(Segment(_carrier_code(f.group(1)) or "AS", f.group(2), f.group(4), f.group(7),
                           _at(_date(f.group(5), sent), f.group(6)), _at(_date(f.group(8), sent), f.group(9)),
                           conf.group(1), None, None, [], template="alaska_change", operated_by=f.group(3).strip()))
    return out


def delta_change(t: str, sent: datetime) -> list[Segment]:
    """Delta 'Flight Time Change' emails: 'Your New Flight Info' FLIGHT/DATE DEPART ARRIVE rows."""
    conf = re.search(r"Trip Confirmation #([A-Z0-9]{6})", t)
    if not conf or "Your New Flight Info" not in t:
        return []
    blk = t.split("Your New Flight Info", 1)[1].split("\nFLIGHT SEAT", 1)[0]
    out = []
    for f in re.finditer(r"\n([A-Z][A-Za-z ]+?) (\d{1,4})\n[A-Z][a-z]{2}, ([A-Z][a-z]+ \d{1,2})\n[^\n]+\n(\d{1,2}:\d{2} [ap]m)\s*"
                         r"\n?([^\n]+?)\n(\d{1,2}:\d{2} [ap]m)", blk):
        o, d = CITY_IATA.get(t_city(f.group(0).split("\n")[3])), CITY_IATA.get(t_city(f.group(5)))
        if not (o and d):
            continue
        day = _date(f.group(3), sent)
        dep = _at(day, f.group(4))
        out.append(Segment(_carrier_code(f.group(1)) or "DL", f.group(2), o, d, dep, _fix_overnight(dep, _at(day, f.group(6))),
                           conf.group(1), None, None, [], template="delta_change"))
    return out


def t_city(s: str) -> str:
    return s.split(",")[0].strip().lower()


def lufthansa_baggage(t: str, sent: datetime) -> list[Segment]:
    """Lufthansa digital baggage receipt: itinerary rows give departure date/time only (arrival unknown)."""
    if "Lufthansa" not in t or "baggage" not in t.lower():
        return []
    out = []
    for f in re.finditer(r"(\d{2})\.(\d{2})\.(\d{4}) - (\d{2}:\d{2})\n(?:\[[^\]]*\] ?)?([A-Z0-9]{2})0*(\d{1,4})\n([A-Z]{3})\n[^\n]+\n(?:\[[^\]]*\] ?)?([A-Z]{3})", t):
        dep = datetime(int(f.group(3)), int(f.group(2)), int(f.group(1)))
        out.append(Segment(f.group(5), f.group(6), f.group(7), f.group(8), _at(dep, f.group(4)), None, None, None, None, [],
                           template="lufthansa_baggage"))
    return out


TEMPLATES: list[Callable[[str, datetime], list[Segment]]] = [
    frontier, frontier_checkin, frontier_2026, american, aa_calendar, united_receipt, ly_itinerary, sabre_reservation, indigo, cleartrip,
    cheapoair, concur, bcd_travel, capital_one, alaska_receipt, alaska_schedule_change, delta_change, lufthansa_baggage,
]


def parse_segments(body: str, sent: datetime, subject: str = "") -> list[Segment]:
    t = normalize(body)
    for fn in TEMPLATES:
        try:
            segs = fn(t, sent)
        except (ValueError, KeyError, AttributeError, IndexError):
            segs = []
        if segs:
            return segs
    return []
