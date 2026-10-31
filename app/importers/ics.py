"""iCalendar (.ics) files and feeds: TripIt's calendar feed, Google/Outlook/Apple calendars.

Events are classified from their text (summary, location, description):
  flight  - a flight number (e.g. "UA 837", "DL1234") plus two airport codes ("SFO to NRT")
  rental  - a car-rental company or "car rental"/"rental car"
  lodging - hotel words, "Stay at …", or a known hotel brand
Anything else is skipped and counted. This is heuristic: calendar events have no
structured travel fields, so check the preview.
"""
from __future__ import annotations

import http.client
import ipaddress
import re
import socket
import ssl
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from typing import Optional

from .common import ImportError_, airline_name, default_arrival, flight_label, fmt_day, item

MAX_BYTES = 5 * 1024 * 1024
FLIGHT_RE = re.compile(r"\b([A-Z][A-Z0-9]|[A-Z0-9][A-Z])\s?(\d{1,4})\b")
ROUTE_RE = re.compile(r"\b([A-Z]{3})\b\s*(?:to|→|->|–|—|-|>|✈)\s*\b([A-Z]{3})\b")
PAREN_CODES_RE = re.compile(r"\(([A-Z]{3})\)")
RENTAL_COMPANIES = ["hertz", "avis", "enterprise", "national", "budget", "alamo", "sixt", "thrifty",
                    "dollar", "turo", "fox rent", "payless", "zipcar"]
RENTAL_WORDS = re.compile(r"\b(car rental|rental car|rent a car|pick ?up car|drop ?off car)\b", re.I)
HOTEL_WORDS = re.compile(r"\b(hotel|inn|resort|motel|hostel|lodge|suites?|airbnb|vrbo|check-?in|stay at|"
                         r"marriott|hilton|hyatt|sheraton|westin|holiday inn|hampton|courtyard|"
                         r"four seasons|ritz|ihg|accor|novotel|ibis|booking\.com)\b", re.I)
NOT_AIRPORT = {"THE", "AND", "FOR", "YOU", "ARE", "PDT", "PST", "EST", "EDT", "UTC", "GMT", "CST", "CDT",
               "MST", "MDT", "USD", "EUR", "GBP", "NEW", "ALL", "DAY", "TRIP", "VIA"}


MAX_REDIRECTS = 3


def _public_ip(host: str, port: int) -> str:
    """Resolve host and return one address, refusing anything that isn't globally routable.
    is_global also rejects 100.64.0.0/10 (Tailscale/CGNAT), which is_private misses."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise ImportError_(f"Couldn't find {host}")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if getattr(ip, "ipv4_mapped", None):
            ip = ip.ipv4_mapped
        if not ip.is_global or ip.is_multicast:
            raise ImportError_("That address is on a private network; the server won't fetch it")
    return infos[0][4][0]


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """Connect to the address that was checked, not a second DNS answer (DNS rebinding)."""
    def __init__(self, host, pinned_ip, **kw):
        super().__init__(host, **kw)
        self._pinned_ip = pinned_ip

    def connect(self):
        self.sock = socket.create_connection((self._pinned_ip, self.port), self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, pinned_ip, **kw):
        super().__init__(host, context=ssl.create_default_context(), **kw)
        self._pinned_ip = pinned_ip

    def connect(self):
        raw = socket.create_connection((self._pinned_ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)  # SNI + cert check on the name


def fetch_feed(url: str) -> bytes:
    """Download a calendar feed. webcal:// becomes https://; private/LAN/tailnet addresses are
    refused, every redirect hop is re-checked, and the connection goes to the checked IP."""
    url = url.strip()
    if url.lower().startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    for _hop in range(MAX_REDIRECTS + 1):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ImportError_("Use an https:// or webcal:// calendar link")
        port = parts.port or (443 if parts.scheme == "https" else 80)
        pinned = _public_ip(parts.hostname, port)
        cls = _PinnedHTTPSConnection if parts.scheme == "https" else _PinnedHTTPConnection
        conn = cls(parts.hostname, pinned, port=port, timeout=15)
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        try:
            conn.request("GET", path, headers={"User-Agent": "Trippy/0.2 (calendar import)",
                                               "Accept": "text/calendar, */*", "Host": parts.netloc})
            resp = conn.getresponse()
            if resp.status in (301, 302, 303, 307, 308):
                loc = resp.getheader("Location")
                if not loc:
                    raise ImportError_("The calendar link redirected nowhere")
                url = urllib.parse.urljoin(url, loc)
                continue
            if resp.status != 200:
                raise ImportError_(f"The calendar server answered HTTP {resp.status}")
            data = resp.read(MAX_BYTES + 1)
            break
        except ImportError_:
            raise
        except Exception:  # don't echo low-level errors (they describe internal hosts/ports)
            raise ImportError_("Couldn't download the calendar")
        finally:
            conn.close()
    else:
        raise ImportError_("The calendar link redirected too many times")
    if len(data) > MAX_BYTES:
        raise ImportError_("That calendar is larger than 5 MB")
    return data


def _when(prop) -> tuple[Optional[datetime], bool, bool]:
    """(wall-clock datetime, all_day, was_utc)"""
    if prop is None:
        return None, False, False
    v = prop.dt
    if isinstance(v, datetime):
        utc = v.tzinfo is not None and v.utcoffset() == timedelta(0)
        return v.replace(tzinfo=None), False, utc
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day), True, False
    return None, False, False


# Usual check-in / check-out hours by brand, for stays that only carry dates.
STAY_HOURS = {"marriott": (16, 12), "westin": (16, 12), "sheraton": (16, 12), "hyatt": (16, 12),
              "hilton": (15, 12), "hampton": (15, 11), "doubletree": (15, 12), "embassy suites": (16, 12),
              "holiday inn": (15, 12), "ihg": (15, 12), "intercontinental": (15, 12), "best western": (15, 11),
              "airbnb": (15, 11), "vrbo": (16, 10)}
DEFAULT_STAY_HOURS = (15, 11)


def stay_hours(name: str) -> tuple[int, int]:
    low = (name or "").lower()
    return next((h for k, h in STAY_HOURS.items() if k in low), DEFAULT_STAY_HOURS)


def _airports(text: str) -> tuple[Optional[str], Optional[str]]:
    m = ROUTE_RE.search(text)
    if m and m.group(1) not in NOT_AIRPORT and m.group(2) not in NOT_AIRPORT:
        return m.group(1), m.group(2)
    codes = [c for c in PAREN_CODES_RE.findall(text) if c not in NOT_AIRPORT]
    if len(codes) >= 2:
        return codes[0], codes[1]
    return None, None


def classify(summary: str, location: str, description: str) -> str:
    text = " ".join((summary, location, description))
    head = " ".join((summary, location))
    dep, arr = _airports(text)
    if FLIGHT_RE.search(summary) and dep:
        return "flight"
    if re.search(r"\bflight\b", summary, re.I) and dep:
        return "flight"
    low = head.lower()
    if RENTAL_WORDS.search(head) or (any(c in low for c in RENTAL_COMPANIES) and re.search(r"\b(car|rental|pick ?up|return)\b", head, re.I)):
        return "rental"
    if HOTEL_WORDS.search(head):
        return "lodging"
    return "other"


def _clean_hotel_name(summary: str) -> str:
    s = re.sub(r"^\s*(stay at|hotel:|lodging:|check-?in:?|check-?out:?|hotel stay:?)\s*", "", summary, flags=re.I)
    return s.strip(" -–—:") or summary.strip()


def parse_ics(data: bytes, source: str = "ics") -> tuple[list[dict], dict]:
    from icalendar import Calendar  # optional dependency, only needed here

    try:
        cal = Calendar.from_ical(data)
    except Exception as exc:
        raise ImportError_(f"That isn't a readable .ics calendar ({exc})")
    items: list[dict] = []
    stats = {"events": 0, "skipped": 0}
    for ev in cal.walk("VEVENT"):
        stats["events"] += 1
        summary = str(ev.get("SUMMARY", "") or "").strip()
        location = str(ev.get("LOCATION", "") or "").strip()
        description = str(ev.get("DESCRIPTION", "") or "").strip()
        uid = str(ev.get("UID", "") or "").strip() or None
        start, all_day, utc = _when(ev.get("DTSTART"))
        end, _, _ = _when(ev.get("DTEND"))
        if start is None:
            stats["skipped"] += 1
            continue
        warnings = ["Times were in UTC in the calendar; check them"] if utc else []
        kind = classify(summary, location, description)
        ext = f"ics:{uid}" if uid else None
        text = " ".join((summary, location, description))
        if kind == "flight":
            m = FLIGHT_RE.search(summary) or FLIGHT_RE.search(text)
            dep, arr = _airports(text)
            carrier, number = (m.group(1), m.group(2)) if m else ("", "")
            label = flight_label(carrier, number) if m else "Flight"
            if not m:
                warnings.append("No flight number found")
            fields = {"airline": airline_name(carrier) if carrier else "Unknown airline",
                      "flight_number": label, "departure_airport": dep, "arrival_airport": arr,
                      "departure_time": start, "arrival_time": default_arrival(start, end, warnings),
                      "booking_source": source, "external_id": ext}
            conf = re.search(r"(?:confirmation|record locator|pnr)[^A-Z0-9]{0,20}([A-Z0-9]{6})\b", text, re.I)
            if conf:
                fields["confirmation_number"] = conf.group(1).upper()
            items.append(item("flight", fields, source=source, ref=uid,
                              summary=f"{label} {dep} → {arr} · {fmt_day(start)}",
                              confidence="high" if m else "medium", warnings=warnings))
        elif kind == "rental":
            low = (summary + " " + location).lower()
            company = next((c.title() for c in RENTAL_COMPANIES if c in low), "Rental car")
            fields = {"rental_company": company, "pickup_location": location or summary,
                      "dropoff_location": location or summary, "pickup_time": start,
                      "dropoff_time": end, "booking_source": source, "external_id": ext,
                      "date_approx": all_day}
            items.append(item("rental", fields, source=source, ref=uid, confidence="medium",
                              summary=f"{company} · {fmt_day(start)}", warnings=warnings))
        elif kind == "lodging":
            name = _clean_hotel_name(summary)
            check_in, check_out = start, end
            if all_day:  # a date-only stay: use the brand's usual hours, flagged as approximate
                cin, cout = stay_hours(name)
                check_in = start.replace(hour=cin)
                check_out = end.replace(hour=cout) if end else None
            fields = {"name": name, "address": location or None, "check_in": check_in, "check_out": check_out,
                      "booking_source": source, "external_id": ext, "time_approx": all_day}
            nights = (end - start).days if end else None
            items.append(item("lodging", fields, source=source, ref=uid, confidence="medium",
                              summary=f"{name} · {fmt_day(start)}" + (f" · {nights} night(s)" if nights else ""),
                              warnings=warnings))
        else:
            stats["skipped"] += 1
    return items, stats
