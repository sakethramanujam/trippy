"""Template parsers for real hotel / lodging confirmation emails and folios.

Same idea as `airline_templates`: each parser is written against a layout a sender actually uses
(anonymized copies live in tests/fixtures/emails/hotel_*), takes normalized plain text plus the
email's sent date, and returns `Stay`s. `parse_stays` tries every template and returns the first hit.

Covered: Booking.com confirmations (2022 and 2023+ layouts), receipts and cancellations; Airbnb
confirmations (three layouts), reminders and receipts; Hotels.com; Capital One Travel; Concur/BCD
itineraries with a hotel segment; folio text from Marriott (Aloft), Hilton, Wyndham (Microtel /
Super 8) and IHG.

Times are local wall clock at the property, like the rest of Trippy.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Optional

from .airline_templates import MONTHS, _date, _hm, normalize


@dataclass
class Stay:
    name: str
    check_in: Optional[datetime]
    check_out: Optional[datetime]
    confirmation: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    room_type: Optional[str] = None
    rooms: Optional[int] = None
    guests: Optional[int] = None
    guest_names: list[str] = field(default_factory=list)
    total: Optional[float] = None        # what was (or will be) paid, taxes included
    currency: Optional[str] = None
    taxes: Optional[float] = None
    source: str = "direct"               # booking.com / airbnb / hotels.com / capital_one_travel / bcd_travel / direct
    status: str = "confirmed"            # confirmed / cancelled
    property_type: str = "hotel"
    loyalty_program: Optional[str] = None
    kind: str = "confirmation"           # confirmation / receipt / folio / reminder / cancellation
    template: str = ""

    @property
    def nights(self) -> Optional[int]:
        if self.check_in and self.check_out:
            return max(0, (self.check_out.date() - self.check_in.date()).days)
        return None


# ---------------------------------------------------------------- helpers

CURRENCY_SIGNS = {"€": "EUR", "£": "GBP", "₹": "INR", "US$": "USD", "$": "USD"}


def _amount(s: Optional[str]) -> tuple[Optional[float], Optional[str]]:
    """'€ 351.56' / 'US$51.38' / 'USD 133.66' / '$1,766.15' -> (351.56, 'EUR')."""
    if not s:
        return None, None
    cur = None
    m = re.search(r"\b(USD|EUR|GBP|INR|CAD)\b", s)
    if m:
        cur = m.group(1)
    else:
        for sign, code in CURRENCY_SIGNS.items():
            if sign in s:
                cur = code
                break
    m = re.search(r"(\d[\d,]*(?:\.\d{1,2})?)", s)
    return (float(m.group(1).replace(",", "")) if m else None), cur


def _after(t: str, label: str, span: int = 1) -> Optional[str]:
    """Value printed after `label` on the same line, or on the next line when the label stands alone."""
    m = re.search(rf"(?im)^{label}[ :]*(.*)$", t)
    if not m:
        return None
    val = m.group(1).strip()
    if val:
        return val
    rest = t[m.end():].lstrip("\n").split("\n")
    return " ".join(x.strip() for x in rest[:span]).strip() or None


def _time_in(s: Optional[str], default: str, last: bool = False) -> tuple[int, int]:
    """First time in `s` (check-in windows "3:00 PM - 11:00 PM"), or the 'until'/last one for check-out."""
    s = (s or "").split("\n")[0]
    times = re.findall(r"(\d{1,2}[:.]\d{2}\s*(?:[ap]\.?\s*m\.?)?)", s, re.I)
    until = re.search(r"until\s+(\d{1,2}[:.]\d{2}\s*(?:[ap]\.?\s*m\.?)?)", s, re.I)
    pick = (until.group(1) if until else times[-1]) if last and times else (times[0] if times else None)
    try:
        return _hm(pick) if pick else _hm(default)
    except ValueError:
        return _hm(default)


def _day_time(s: Optional[str], default_time: str, ref: Optional[datetime] = None,
              last: bool = False) -> Optional[datetime]:
    """'Sunday, September 6, 2026 (from 3:00 PM)' -> datetime(2026, 9, 6, 15, 0)."""
    if not s:
        return None
    m = re.search(r"([A-Za-z]{3,9}\.? \d{1,2},? \d{4}|\d{1,2} [A-Za-z]{3,9} \d{4}|[A-Za-z]{3,9}\.? \d{1,2}\b)", s)
    if not m:
        return None
    try:
        day = _date(m.group(1), ref)
    except (ValueError, KeyError):
        return None
    h, mi = _time_in(s[m.end():], default_time, last)
    return day.replace(hour=h, minute=mi)


def _dated(t: str, label: str) -> Optional[str]:
    """Text after the first `label` line that is followed by a date (skips 'Check-in number 123')."""
    for m in re.finditer(rf"(?im)^{label}\b[ :]*\n?(.*)$", t):
        if re.search(r"[A-Za-z]{3,9}\.? \d{1,2},? \d{4}|\d{1,2} [A-Za-z]{3,9} \d{4}", m.group(1)):
            return m.group(1)
    return None


def _int(s: Optional[str]) -> Optional[int]:
    m = re.search(r"\d+", s or "")
    return int(m.group(0)) if m else None


US_STATES = set("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND "
                "OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split())


def split_address(addr: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Best-effort (city, country) from a one-line street address. Country is 'US' or the printed name."""
    if not addr:
        return None, None
    a = re.sub(r"\s*\([^)]*\)", "", addr)
    parts = [p.strip() for p in a.split(",") if p.strip()]
    country = None
    rest = []
    for p in parts:
        if re.fullmatch(r"(?i)united states(?: of america)?|usa?|united", p):
            country = "US"
        elif re.fullmatch(r"(?i)germany|deutschland|de", p):
            country = "Germany"
        elif re.fullmatch(r"(?i)belgium|france|netherlands|austria|italy|spain|india|united kingdom|uk", p):
            country = p.title()
        else:
            rest.append(p)
    if country is None and re.search(r"\b(?:%s)\b,?\s*\d{5}" % "|".join(US_STATES), a):
        country = "US"
    city = None
    for i in range(len(rest) - 1, 0, -1):
        p = rest[i]
        p2 = re.sub(r"\b[A-Z]{2}\b|\d{4,5}(?:-\d{4})?", "", p).strip(" ,")
        if p2 and not re.search(r"\d", p2):
            city = p2
            break
    return city, country


# ---------------------------------------------------------------- Booking.com

def booking_confirmation(t: str, sent: datetime, subject: str = "") -> list[Stay]:
    if "Booking.com" not in t and "booking.com" not in subject.lower():
        return []
    m = re.search(r"booking is confirmed at (.+)$", subject) or re.search(r"(?m)^(.+?) is expecting you on", t)
    if not m or not re.search(r"(?im)^Check-in\b", t):
        return []
    name = m.group(1).strip()
    conf = re.search(r"(?:Confirmation|Booking number)[: ]+(\d{6,})", t)
    ci = _day_time(_dated(t, "Check-in"), "15:00", sent)
    co = _day_time(_dated(t, "Check-out"), "11:00", sent, last=True)
    res = _after(t, "Your reservation") or _after(t, "Booking details") or ""
    rooms = re.search(r"(\d+) rooms?", res)
    room_type = None
    if not rooms:
        rt = re.search(r"nights?,\s*(.+?)(?:\s+Change)?$", res)
        room_type = rt.group(1).strip() if rt else None
    rt = re.search(r"(?m)^(?:Room 1: |Room type )(.+)$", t)
    room_type = room_type or (rt.group(1).strip() if rt else None)
    guests = _int(_after(t, "You booked for"))
    if guests is None:
        g = re.search(r"booked guests\s*\((\d+) adults?", t)
        guests = int(g.group(1)) if g else None
    addr = _after(t, "Location", span=2)
    if addr and not re.search(r"\d", addr):
        addr = None
    if addr:
        addr = re.split(r"\s+(?:Show directions|Getting there|Phone|Price details|Image of)", addr)[0]
        addr = re.sub(r",?\s*United States(?: of(?: America)?)?\b.*$|,?\s*United$", ", United States", addr)
    if not addr:
        am = re.search(rf"(?m)^{re.escape(name)}\n(\d[^\n]+)$", t)
        addr = am.group(1).strip() if am else None
    if not addr or len(addr) < 8:
        am = re.search(rf"(?m)^{re.escape(name)}\n(.+?)(?: - Show directions|\nPhone)", t, re.S)
        addr = re.sub(r"\s+", " ", am.group(1)).strip() if am else None
    tot = re.search(r"(?m)^Total Price\s*\n?\s*(.+)$", t) or re.search(r"You(?:’|')ve paid (\S+)", t) \
        or re.search(r"You paid (\S+)", t)
    total, cur = _amount(tot.group(1)) if tot else (None, None)
    tax = re.search(r"(?m)^(?:\d+ ?% )?(?:VAT|TAX|Other tax|Tax)\b[^\n]*\n?\s*((?:€|\$|US\$|USD|EUR)\s?[\d.,]+)", t)
    taxes = _amount(tax.group(1))[0] if tax else None
    names = re.findall(r"(?m)^Guest name\s*\n?\s*(.+?)(?:\s+Edit guest name)?$", t)
    canceled = bool(re.search(r"booking has been canceled|Booking canceled", t + subject, re.I))
    city, country = split_address(addr)
    return [Stay(name=name, check_in=ci, check_out=co, confirmation=conf.group(1) if conf else None,
                 address=addr, city=city, country=country, room_type=room_type,
                 rooms=int(rooms.group(1)) if rooms else 1, guests=guests, guest_names=[n.strip() for n in names],
                 total=total, currency=cur, taxes=taxes, source="booking.com",
                 status="cancelled" if canceled else "confirmed", template="booking_confirmation")]


def booking_receipt(t: str, sent: datetime, subject: str = "") -> list[Stay]:
    if not (re.search(r"This is your receipt", t + subject) and "Booking number" in t and "Property name" in t):
        return []
    name = _after(t, "Property name")
    addr_m = re.search(r"(?m)^Property address\n(.+?)\nCheck-in", t, re.S)
    addr = re.sub(r"\s*\n\s*", ", ", addr_m.group(1).strip()) if addr_m else None
    paid = re.search(r"(?m)^Amount paid[^\n]*\n(.+)$", t)
    total, cur = _amount(paid.group(1)) if paid else (None, None)
    city, country = split_address(addr)
    return [Stay(name=name, check_in=_day_time(_dated(t, "Check-in"), "15:00"),
                 check_out=_day_time(_dated(t, "Check-out"), "11:00", last=True),
                 confirmation=_after(t, "Booking number"), address=addr, city=city, country=country,
                 total=total, currency=cur, source="booking.com", kind="receipt", template="booking_receipt",
                 guest_names=[_after(t, "Name") or ""])]


def booking_cancellation(t: str, sent: datetime, subject: str = "") -> list[Stay]:
    m = re.search(r"Booking canceled for (.+)$", subject)
    if not m and not re.search(r"Your booking has been canceled", t):
        return []
    conf = re.search(r"Confirmation Number:? (\d{6,})", t)
    return [Stay(name=(m.group(1) if m else "Booking.com stay").strip(), check_in=None, check_out=None,
                 confirmation=conf.group(1) if conf else None, source="booking.com", status="cancelled",
                 kind="cancellation", template="booking_cancellation")]


# ---------------------------------------------------------------- Airbnb

def _airbnb_pair(t: str, sent: datetime) -> tuple[Optional[datetime], Optional[datetime]]:
    # 2024+: "Check-in Checkout\nSAT, AUG 31 MON, SEP 2\n3:00 PM 11:00 AM"
    m = re.search(r"Check-in Checkout\n(\w{3}, \w{3} \d{1,2}) (\w{3}, \w{3} \d{1,2})\n(.+)", t, re.I)
    if m:
        times = re.findall(r"\d{1,2}:\d{2}\s*[AP]M", m.group(3), re.I)
        ci = _date(m.group(1).title(), sent)
        co = _date(m.group(2).title(), ci)
        h1 = _hm(times[0]) if times else (15, 0)
        h2 = _hm(times[1]) if len(times) > 1 else (11, 0)
        return ci.replace(hour=h1[0], minute=h1[1]), co.replace(hour=h2[0], minute=h2[1])
    # 2022-23: "CHECK IN\nThursday, April 14, 2022\nCheck-in is anytime after 4:00 PM"
    a = re.search(r"CHECK IN\n(.+)\n(.+)", t)
    b = re.search(r"CHECK OUT\n(.+)\n(.+)", t)
    if a and b:
        return _day_time(a.group(1) + " " + a.group(2), "15:00"), _day_time(b.group(1) + " " + b.group(2), "11:00")
    return None, None


def airbnb(t: str, sent: datetime, subject: str = "") -> list[Stay]:
    if "airbnb" not in (t + subject).lower() and not re.search(r"RESERVATION CODE\n?HM[A-Z0-9]{8}", t):
        return []
    if re.search(r"Your receipt from Airbnb", t + subject) and "Confirmation code" in t:
        return airbnb_receipt(t, sent)
    if not re.search(r"Reservation confirmed|YOUR RESERVATION IS CONFIRMED|Reservation reminder|"
                     r"Confirmed: Your|PACK YOUR BAGS|all set for", subject + "\n" + t, re.I):
        return []
    ci, co = _airbnb_pair(t, sent)
    m = re.search(r"Confirmed: Your (\w{3}) (\d{1,2}) [–-] (?:(\w{3}) )?(\d{1,2}) trip", subject)
    if ci is None and m:
        ci = _date(f"{m.group(1)} {m.group(2)}", sent).replace(hour=15)
        co = _date(f"{m.group(3) or m.group(1)} {m.group(4)}", ci).replace(hour=11)
    if ci is None:
        return []
    lines = t.split("\n")
    listing = None
    for i, line in enumerate(lines):
        if re.search(r"hosted by", line, re.I) and i:
            listing = lines[i - 1].strip()
            break
    addr = re.search(r"(?m)^ADDRESS\n(.+)\n(.+)$", t)
    if addr and re.match(r"\d", addr.group(1)):
        addr = addr.group(1).strip() + (" " + addr.group(2).strip() if addr.group(1).rstrip().endswith(",") else "")
    else:
        addr = None
    code = re.search(r"(?:Reservation code|RESERVATION CODE|Confirmation code)[:\s]+([A-Z0-9]{8,12})", t)
    paid = re.search(r"AMOUNT PAID \((\w{3})\) \$([\d,.]+)", t) or re.search(r"Total \((\w{3})\)\s*\$([\d,.]+)", t)
    guests = re.search(r"(?m)^GUESTS\n(\d+)", t)
    city, country = split_address(addr)
    if not city:
        cm = re.search(r"(?:going to|all set for|trip to) ([A-Z][\w .'-]+?)(?:, [A-Z]{2})?[!.\n]", t, re.I)
        city = cm.group(1).strip().title() if cm else None
    return [Stay(name=(listing or f"Airbnb in {city or 'stay'}").title() if listing and listing.isupper() else (listing or f"Airbnb in {city}"),
                 check_in=ci, check_out=co, confirmation=code.group(1) if code else None,
                 address=addr, city=city, country=country or ("US" if addr and "USA" in addr else None),
                 guests=int(guests.group(1)) if guests else None,
                 total=float(paid.group(2).replace(",", "")) if paid else None, currency=paid.group(1) if paid else None,
                 source="airbnb", property_type="rental",
                 kind="reminder" if "reminder" in (subject + t).lower()[:400] or "PACK YOUR BAGS" in t else "confirmation",
                 template="airbnb")]


def airbnb_receipt(t: str, sent: datetime) -> list[Stay]:
    code = re.search(r"Confirmation code: ([A-Z0-9]+)", t)
    d = re.search(r"\d+ nights? in (.+)\n(\w{3}, \w{3} \d{1,2}, \d{4})(?:\n| -> )(\w{3}, \w{3} \d{1,2}, \d{4})", t)
    total = re.search(r"(?:New total|Total) \((\w{3})\)\n\$([\d,.]+)", t)
    taxes = re.findall(r"(?m)^(?:Taxes|Occupancy taxes and fees)\n\$([\d,.]+)", t)
    guests = re.search(r"· (\d+) guests?", t)
    ptype = re.search(r"(?m)^(Entire home/apt|Private room|Shared room)", t)
    ci = _day_time(d.group(2), "15:00") if d else None
    co = _day_time(d.group(3), "11:00") if d else None
    city = d.group(1).strip() if d else None
    return [Stay(name=f"Airbnb in {city}" if city else "Airbnb stay", check_in=ci, check_out=co,
                 confirmation=code.group(1) if code else None, city=city,
                 room_type=ptype.group(1) if ptype else None, guests=int(guests.group(1)) if guests else None,
                 total=float(total.group(2).replace(",", "")) if total else None,
                 currency=total.group(1) if total else None,
                 taxes=sum(float(x.replace(",", "")) for x in taxes) if taxes else None,
                 source="airbnb", property_type="rental", kind="receipt", template="airbnb_receipt")]


# ---------------------------------------------------------------- Hotels.com / Capital One / Concur

def hotels_com(t: str, sent: datetime, subject: str = "") -> list[Stay]:
    it = re.search(r"Hotels\.com itinerary: (\d+)", t)
    if not it:
        return []
    m = re.search(r"Hotels\.com itinerary: \d+\nCheck-in\n(.+)\n(.+)\nCheck-out\n(.+)\n(.+)\n(.+)\n(.+)\n", t)
    name = t[:it.start()].strip().split("\n")[-1].strip()
    ci = co = None
    nights = rooms = guests = None
    room_type = None
    if m:
        ci = _date(m.group(2), sent).replace(hour=_hm(m.group(1))[0], minute=_hm(m.group(1))[1])
        co = _date(m.group(4), ci).replace(hour=_hm(m.group(3))[0], minute=_hm(m.group(3))[1])
        g = re.search(r"(\d+) adults?", m.group(5))
        r = re.search(r"(\d+) rooms?", m.group(5))
        guests, rooms = (int(g.group(1)) if g else None), (int(r.group(1)) if r else None)
        room_type = m.group(6).strip()
    addr = re.search(r"(?m)^(\d+ [^\n]+, [A-Z]{2}, \d{5}[^\n]*)$", t)
    addr = addr.group(1).replace(" United States of America", ", United States") if addr else None
    total = re.search(r"(?m)^Total\n(.+)$", t)
    taxes = re.search(r"(?m)^Taxes\n(.+)$", t)
    amt, cur = _amount(total.group(1)) if total else (None, None)
    city, country = split_address(addr)
    return [Stay(name=name, check_in=ci, check_out=co, confirmation=it.group(1), address=addr, city=city,
                 country=country, room_type=room_type, rooms=rooms, guests=guests, total=amt, currency=cur,
                 taxes=_amount(taxes.group(1))[0] if taxes else None, source="hotels.com", template="hotels_com")]


def capital_one_hotel(t: str, sent: datetime, subject: str = "") -> list[Stay]:
    if "Capital One Travel" not in t or "Hotel Confirmation" not in t:
        return []
    c1 = re.search(r"Capital One Travel\n(H-[A-Z0-9]+)", t)
    hc = re.search(r"Hotel Confirmation\n(\S+)", t)
    m = re.search(r"Manage Your Trip <?\n(.+)\n(.+)\n", t) or re.search(r"Hotel Confirmation\n\S+\n(.+)\n(.+)\n", t)
    ci = _day_time(_after(t, "Check-in"), "15:00")
    co = _day_time(_after(t, "Checkout"), "12:00", last=True)
    stay = _after(t, "Your Stay") or ""
    paid = re.search(r"Card Payment from Card ending in \d+ (\S+)", t) or re.search(r"Due Today (\S+)", t)
    taxes = re.search(r"Taxes & Fees: (\S+)", t)
    room = _after(t, "Room Type")
    addr = m.group(2).strip() if m else None
    city, country = split_address(addr)
    amt, cur = _amount(paid.group(1)) if paid else (None, None)
    return [Stay(name=m.group(1).strip() if m else "Hotel", check_in=ci, check_out=co,
                 confirmation=hc.group(1) if hc else (c1.group(1) if c1 else None), address=addr, city=city,
                 country=country, room_type=room.title() if room else None, rooms=_int(re.search(r"(\d+) rooms?", stay).group(0)) if re.search(r"(\d+) rooms?", stay) else None,
                 guest_names=[_after(t, "Guest Name") or ""], total=amt, currency=cur,
                 taxes=_amount(taxes.group(1))[0] if taxes else None, source="capital_one_travel",
                 template="capital_one_hotel")]


def concur_hotel(t: str, sent: datetime, subject: str = "") -> list[Stay]:
    if not re.search(r"Concur|BCD", t + subject) or "Checking In:" not in t:
        return []
    out = []
    for m in re.finditer(r"(?m)^(.+)\n(.+)\n(.+?), (\d{4,5})\n([A-Z]{2})\n[^\n]*\nChecking In: (.+)\n(.+)\nChecking Out: (.+)\n"
                         r"Confirmation: (\S+)", t):
        ci = _date(m.group(6), sent).replace(hour=15)
        co = _date(m.group(8), ci).replace(hour=11)
        rg = re.search(r"Room (\d+), Days (\d+), Guests (\d+)", m.group(7))
        tail = t[m.end():m.end() + 600]
        total = re.search(r"Total Rate: (\S+ ?[\d.,]+)", tail)
        amt, cur = _amount(total.group(1)) if total else (None, None)
        name = re.sub(r"Gardenn", "Garden", m.group(1).strip())
        out.append(Stay(name=name, check_in=ci, check_out=co, confirmation=m.group(9),
                        address=f"{m.group(2).strip()}, {m.group(4)} {m.group(3).strip()}, {m.group(5)}",
                        city=m.group(3).strip(), country=m.group(5), rooms=1,
                        guests=int(rg.group(3)) if rg else None, total=amt, currency=cur,
                        status="cancelled" if re.search(r"Status:\s*Cancel", tail) else "confirmed",
                        source="bcd_travel", template="concur_hotel"))
    return out


# ---------------------------------------------------------------- folios (PDF text)

def _dmy(s: str) -> datetime:
    """07-APR-26 / 10/09/2023 / 05-24-25 / Aug 24, 2025 / Sep 04, 2026."""
    s = s.strip()
    m = re.fullmatch(r"(\d{2})-([A-Z]{3})-(\d{2})", s)
    if m:
        return datetime(2000 + int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", s)
    if m:  # European day/month
        return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    m = re.fullmatch(r"(\d{2})-(\d{2})-(\d{2})", s)
    if m:  # US month-day-year
        return datetime(2000 + int(m.group(3)), int(m.group(1)), int(m.group(2)))
    return _date(s)


def folio(t: str, sent: Optional[datetime] = None, subject: str = "") -> list[Stay]:
    t = re.sub(r"\A(?:(?:From|Subject|Date|To|Content-Type):.*\n|[ \t]*\n)+", "", t)
    lines = [x.strip() for x in t.split("\n") if x.strip()]
    if not lines:
        return []
    # Marriott (Aloft etc.)
    m = re.search(r"Arrive Date\s*:\s*(\S+)\s+(\d{2}:\d{2})?.*?Depart Date\s*:\s*(\S+)", t, re.S)
    if m:
        ci = _dmy(m.group(1))
        if m.group(2):
            ci = ci.replace(hour=int(m.group(2)[:2]), minute=int(m.group(2)[3:]))
        co = _dmy(m.group(3)).replace(hour=11)
        total = re.search(r"Total\s+([\d,]+\.\d{2})", t) or re.search(r"Balance\s+([\d,]+\.\d{2})", t)
        g = re.search(r"No\. Of Guest\s*:\s*(\d+)", t)
        addr = ", ".join(lines[1:3])
        city, country = split_address(addr)
        taxes = sum(float(x) for x in re.findall(r"(?:State Tax|City/Local Tax|Tourism Fee)\s+([\d.]+)", t))
        return [Stay(name=lines[0], check_in=ci, check_out=co, address=addr, city=city, country=country or "US",
                     guests=int(g.group(1)) if g else None, guest_names=[lines[4].split("  ")[0]],
                     total=float(total.group(1).replace(",", "")) if total else None, currency="USD",
                     taxes=round(taxes, 2) or None, loyalty_program="Marriott Bonvoy" if "Bonvoy" in t else None,
                     kind="folio", template="folio_marriott")]
    # Hilton
    m = re.search(r"Arrival Date\s+(\d{2}/\d{2}/\d{4}) (\d{2}):(\d{2}).*?Departure Date\s+(\d{2}/\d{2}/\d{4}) (\d{2}):(\d{2})", t, re.S)
    if m:
        ci = _dmy(m.group(1)).replace(hour=int(m.group(2)), minute=int(m.group(3)))
        co = _dmy(m.group(4)).replace(hour=int(m.group(5)), minute=int(m.group(6)))
        conf = re.search(r"Confirmation Number: (\d+)", t)
        tot = re.search(r"TOTAL AMOUNT\s+(\S+)", t)
        amt, cur = _amount(tot.group(1)) if tot else (None, None)
        guest = re.search(r"\n\s*(\S.+?)\s{3,}Room Number", t)
        g = re.search(r"Adult/Child\s+(\d+)/", t)
        return [Stay(name=lines[0].title().replace("Munich Messe", "Munich Messe"), check_in=ci, check_out=co,
                     confirmation=conf.group(1) if conf else None, address=re.sub(r"([A-Za-z])(\d{5})\b", r"\1 \2", f"{lines[1].title()}, {lines[2].title()}, {lines[3]}"),
                     guests=int(g.group(1)) if g else None, guest_names=[guest.group(1).strip()] if guest else [],
                     total=amt, currency=cur, loyalty_program="Hilton Honors", kind="folio", template="folio_hilton")]
    # IHG
    m = re.search(r"Check In Date\s+(\w{3} \d{2}, \d{4}).*?Check Out Date\s+(\w{3} \d{2}, \d{4})", t, re.S)
    if m:
        ci, co = _dmy(m.group(1)), _dmy(m.group(2))
        cin = re.search(r"Check In Time\s+(\d{1,2}:\d{2} [AP]M)", t)
        cout = re.search(r"Check Out Time\s+(\d{1,2}:\d{2} [AP]M)", t)
        if cout:
            co = co.replace(hour=_hm(cout.group(1))[0], minute=_hm(cout.group(1))[1])
        if cin:
            ci = ci.replace(hour=_hm(cin.group(1))[0], minute=_hm(cin.group(1))[1])
        conf = re.search(r"Confirmation Number - (\d+)", t)
        name = re.split(r"\s{3,}", lines[0])[0]
        g = re.search(r"Guests\s+(\d+)/", t)
        agent = re.search(r"Name\s+(HOTELS\.COM|EXPEDIA|BOOKING\.COM)", t)
        return [Stay(name=name, check_in=ci, check_out=co, confirmation=conf.group(1) if conf else None,
                     address=re.split(r"\s{3,}", lines[1])[0], guests=int(g.group(1)) if g else None,
                     loyalty_program="IHG One Rewards" if "IHG One Rewards" in t else None,
                     source=agent.group(1).lower() if agent else "direct", kind="folio", template="folio_ihg")]
    # Wyndham: Microtel layout
    m = re.search(r"Arrival\s*:\s*(\d{2}-\d{2}-\d{2}).*?Departure\s*:\s*(\d{2}-\d{2}-\d{2})", t, re.S)
    if m:
        conf = re.search(r"Conf\. No\.\s*:\s*(\d+)", t)
        tot = re.search(r"(?m)^\s*Total\s+([\d,]+\.\d{2})", t)
        return [Stay(name=lines[0], check_in=_dmy(m.group(1)).replace(hour=15), check_out=_dmy(m.group(2)).replace(hour=11),
                     confirmation=conf.group(1) if conf else None, total=float(tot.group(1).replace(",", "")) if tot else None,
                     currency="USD", guest_names=[re.split(r"\s{3,}", lines[4])[0]], loyalty_program="Wyndham Rewards",
                     kind="folio", template="folio_wyndham")]
    # Wyndham: Super 8 "Folio" layout
    m = re.search(r"Arrival:\s+(\w{3} \d{1,2}, \d{4}).*?Departure:\s+(\w{3} \d{1,2}, \d{4})", t, re.S)
    if m:
        conf = re.search(r"Confirmation\s+(\w+)", t)
        tot = re.search(r"Total Estimated Stay Amount: USD ([\d.,]+) \+ USD ([\d.,]+) Taxes and Fees = USD ([\d.,]+)", t)
        g = re.search(r"Guests:\s*(\d+)/", t)
        n = re.search(r"Nights:\s*(\d+)", t)
        rt = re.search(r"Room\s+(\w+)\s+Nights", t)
        name = " ".join(x for x in re.split(r"\n", t[:400]) if x.strip())[:200]
        nm = re.search(r"(Super 8[^\n]*?)(?:\s{2,}|\n)", t)
        return [Stay(name=(nm.group(1).strip() if nm else name), check_in=_dmy(m.group(1)).replace(hour=15),
                     check_out=_dmy(m.group(2)).replace(hour=11), confirmation=conf.group(1) if conf else None,
                     guests=int(g.group(1)) if g else None, room_type=rt.group(1) if rt else None,
                     total=float(tot.group(3)) if tot else None, taxes=float(tot.group(2)) if tot else None,
                     currency="USD", loyalty_program="Wyndham Rewards" if "Loyalty" in t else None,
                     kind="folio", template="folio_wyndham_folio")]
    return []


# ---------------------------------------------------------------- dispatch

TEMPLATES: list[Callable[[str, datetime, str], list[Stay]]] = [
    booking_cancellation, booking_receipt, booking_confirmation, airbnb, hotels_com, capital_one_hotel, concur_hotel,
    folio,
]

BRANDS = [
    (r"hilton|hampton inn|doubletree|embassy suites|homewood|home2", "Hilton"),
    (r"aloft|moxy|marriott|courtyard|residence inn|fairfield|springhill|sheraton|westin|four points|w hotel", "Marriott"),
    (r"holiday inn|crowne plaza|candlewood|staybridge|intercontinental|\bihg\b|avid hotel", "IHG"),
    (r"super 8|microtel|days inn|ramada|wyndham|la quinta|baymont|travelodge|howard johnson|wingate", "Wyndham"),
    (r"comfort (?:inn|suites)|quality inn|sleep inn|clarion|econo lodge|rodeway|cambria|mainstay", "Choice"),
    (r"best western|surestay", "Best Western"),
    (r"\bibis\b|mercure|novotel|sofitel|pullman", "Accor"),
    (r"motel 6|studio 6", "Motel 6"),
    (r"red roof", "Red Roof"),
    (r"red lion", "Sonesta"),
    (r"extended stay america", "Extended Stay America"),
    (r"campanile", "Louvre Hotels"),
    (r"hyatt", "Hyatt"),
]


def brand_of(name: str, source: str = "") -> Optional[str]:
    low = (name or "").lower()
    for rx, brand in BRANDS:
        if re.search(rx, low):
            return brand
    return None


SOURCE_LABEL = {"booking.com": "Booking.com", "airbnb": "Airbnb", "hotels.com": "Hotels.com",
                "capital_one_travel": "Capital One Travel", "bcd_travel": "BCD Travel", "direct": "direct"}

COUNTRY_CODE = {"us": "US", "germany": "DE", "belgium": "BE", "france": "FR", "netherlands": "NL", "austria": "AT",
                "italy": "IT", "spain": "ES", "india": "IN", "united kingdom": "GB", "uk": "GB"}
STATE_TZ = {**{s: "America/Los_Angeles" for s in "CA NV OR WA".split()},
            **{s: "America/Denver" for s in "UT CO NM ID MT WY".split()},
            "AZ": "America/Phoenix",
            **{s: "America/Chicago" for s in "TX OK KS NE SD ND MN IA MO AR LA MS AL TN WI IL".split()},
            **{s: "America/New_York" for s in "FL GA SC NC VA WV MD DE PA NJ NY CT RI MA VT NH ME OH MI IN KY DC".split()}}
COUNTRY_TZ = {"DE": "Europe/Berlin", "BE": "Europe/Brussels", "FR": "Europe/Paris", "NL": "Europe/Amsterdam",
              "AT": "Europe/Vienna", "IT": "Europe/Rome", "ES": "Europe/Madrid", "IN": "Asia/Kolkata", "GB": "Europe/London"}


def country_code(country: Optional[str]) -> Optional[str]:
    if not country:
        return None
    return COUNTRY_CODE.get(country.strip().lower(), country.strip()[:2].upper() if len(country.strip()) == 2 else country)


def guess_tz(address: Optional[str], country: Optional[str]) -> Optional[str]:
    """IANA zone from a US state abbreviation in the address, or the country. None when unsure."""
    cc = country_code(country)
    if cc == "US" or cc is None:
        m = re.findall(r"\b([A-Z]{2})\b,?\s*(?:\d{5}|US\b|USA\b|United States)", address or "")
        if m and m[-1] in STATE_TZ:
            return STATE_TZ[m[-1]]
        return None
    return COUNTRY_TZ.get(cc)


def to_fields(s: Stay, ref: Optional[str] = None) -> dict:
    """A parsed Stay as Lodging fields (schemas.LodgingCreate + external_id)."""
    city, country = split_address(s.address)
    city = s.city or city
    cc = country_code(s.country or country)
    tz = guess_tz(s.address, cc)
    key = s.confirmation or re.sub(r"[^a-z0-9]+", "-", s.name.lower()).strip("-")[:40]
    day = s.check_in.date().isoformat() if s.check_in else "unknown"
    status = "cancelled" if s.status == "cancelled" else None
    return {
        "name": s.name, "address": s.address, "check_in": s.check_in, "check_out": s.check_out,
        "confirmation_number": s.confirmation, "cost": s.total, "currency": s.currency or "USD",
        "booking_source": SOURCE_LABEL.get(s.source, s.source), "brand": brand_of(s.name, s.source),
        "property_type": s.property_type, "city": city, "country": cc,
        "check_in_tz": tz, "check_out_tz": tz, "nights": s.nights, "room_type": s.room_type,
        "rooms": s.rooms, "guests": s.guests, "taxes_fees": s.taxes, "loyalty_program": s.loyalty_program,
        "status": status, "source_email_ref": ref,
        "external_id": f"email:hotel:{key}:{day}",
    }


def parse_stays(body: str, sent: Optional[datetime] = None, subject: str = "") -> list[Stay]:
    t = normalize(body)
    sent = sent or datetime.now()
    for fn in TEMPLATES:
        try:
            stays = fn(t, sent, subject)
        except (ValueError, KeyError, AttributeError, IndexError):
            stays = []
        stays = [s for s in stays if s.check_in or s.status == "cancelled"]
        if stays:
            return stays
    return []
