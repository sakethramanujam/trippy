"""Shared bits for importers: the item shape, dates, airline/airport hints."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional

KINDS = ("flight", "rental", "lodging")


class ImportError_(ValueError):
    """Input we can't read; the API turns it into a 400."""


def item(kind: str, fields: dict, *, source: str, summary: str, confidence: str = "high",
         warnings: Optional[list[str]] = None, ref: Optional[str] = None) -> dict:
    """One thing found in the input. `fields` matches FlightCreate / RentalCarCreate / Lodging."""
    return {"kind": kind, "fields": fields, "source": source, "summary": summary,
            "confidence": confidence, "warnings": warnings or [], "ref": ref, "duplicate_of": None}


def naive_local(dt) -> Optional[datetime]:
    """Trippy stores wall-clock times without a zone (like the rest of the app)."""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.replace(tzinfo=None)
    if isinstance(dt, date):
        return datetime(dt.year, dt.month, dt.day)
    return None


def to_utc_naive(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def parse_dt(text: Optional[str]) -> Optional[datetime]:
    """ISO-ish timestamps: 2026-03-04, 2026-03-04T08:15, 2026-03-04 08:15:00, with or without zone."""
    if not text:
        return None
    t = text.strip()
    if not t:
        return None
    t = t.replace("Z", "+00:00")
    for candidate in (t, t.replace(" ", "T", 1)):
        try:
            dt = datetime.fromisoformat(candidate)
            return dt.replace(tzinfo=None)  # keep the local wall-clock time as written
        except ValueError:
            continue
    for fmt in ("%m/%d/%Y %H:%M", "%m/%d/%Y %I:%M %p", "%m/%d/%Y", "%d %b %Y", "%b %d, %Y", "%B %d, %Y",
                "%d %B %Y", "%a, %b %d, %Y", "%A, %B %d, %Y", "%b %d %Y"):
        try:
            return datetime.strptime(t, fmt)
        except ValueError:
            continue
    return None


def fmt_day(dt: Optional[datetime]) -> str:
    return dt.strftime("%b %-d, %Y") if dt else "date unknown"


# ICAO -> (IATA, name) for common carriers. Flighty exports ICAO codes.
AIRLINES_ICAO = {
    "AAL": ("AA", "American Airlines"), "UAL": ("UA", "United Airlines"), "DAL": ("DL", "Delta Air Lines"),
    "SWA": ("WN", "Southwest Airlines"), "ASA": ("AS", "Alaska Airlines"), "JBU": ("B6", "JetBlue"),
    "NKS": ("NK", "Spirit Airlines"), "FFT": ("F9", "Frontier Airlines"), "HAL": ("HA", "Hawaiian Airlines"),
    "SKW": ("OO", "SkyWest Airlines"), "ACA": ("AC", "Air Canada"), "WJA": ("WS", "WestJet"),
    "BAW": ("BA", "British Airways"), "VIR": ("VS", "Virgin Atlantic"), "AFR": ("AF", "Air France"),
    "KLM": ("KL", "KLM"), "DLH": ("LH", "Lufthansa"), "SWR": ("LX", "SWISS"), "AUA": ("OS", "Austrian"),
    "IBE": ("IB", "Iberia"), "EIN": ("EI", "Aer Lingus"), "SAS": ("SK", "SAS"), "FIN": ("AY", "Finnair"),
    "TAP": ("TP", "TAP Air Portugal"), "THY": ("TK", "Turkish Airlines"), "UAE": ("EK", "Emirates"),
    "QTR": ("QR", "Qatar Airways"), "ETD": ("EY", "Etihad Airways"), "SIA": ("SQ", "Singapore Airlines"),
    "CPA": ("CX", "Cathay Pacific"), "JAL": ("JL", "Japan Airlines"), "ANA": ("NH", "All Nippon Airways"),
    "KAL": ("KE", "Korean Air"), "AAR": ("OZ", "Asiana Airlines"), "EVA": ("BR", "EVA Air"),
    "CAL": ("CI", "China Airlines"), "QFA": ("QF", "Qantas"), "ANZ": ("NZ", "Air New Zealand"),
    "AMX": ("AM", "Aeromexico"), "VOI": ("Y4", "Volaris"), "AVA": ("AV", "Avianca"), "LAN": ("LA", "LATAM"),
    "AIC": ("AI", "Air India"), "IGO": ("6E", "IndiGo"), "RYR": ("FR", "Ryanair"), "EZY": ("U2", "easyJet"),
    "WZZ": ("W6", "Wizz Air"), "VLG": ("VY", "Vueling"), "EJU": ("EC", "easyJet Europe"),
}
AIRLINES_IATA = {iata: name for iata, name in AIRLINES_ICAO.values()}
AIRLINES_IATA.update({"WN": "Southwest Airlines", "B6": "JetBlue", "G4": "Allegiant Air", "SY": "Sun Country"})
# Words in confirmation emails -> IATA code.
AIRLINE_WORDS = {
    "united": "UA", "american airlines": "AA", "delta": "DL", "southwest": "WN", "alaska airlines": "AS",
    "jetblue": "B6", "spirit": "NK", "frontier": "F9", "hawaiian": "HA", "air canada": "AC",
    "british airways": "BA", "lufthansa": "LH", "air france": "AF", "klm": "KL", "emirates": "EK",
    "qatar": "QR", "singapore airlines": "SQ", "japan airlines": "JL", "ana ": "NH", "virgin atlantic": "VS",
    "aer lingus": "EI", "iberia": "IB", "turkish airlines": "TK", "cathay": "CX", "qantas": "QF",
}


def airline_name(code: Optional[str]) -> str:
    code = (code or "").strip().upper()
    if code in AIRLINES_ICAO:
        return AIRLINES_ICAO[code][1]
    return AIRLINES_IATA.get(code, code or "Unknown airline")


def iata_carrier(code: Optional[str]) -> str:
    code = (code or "").strip().upper()
    if len(code) == 3 and code in AIRLINES_ICAO:
        return AIRLINES_ICAO[code][0]
    return code


def flight_label(carrier: str, number: str) -> str:
    number = (number or "").lstrip("0") or number
    return f"{carrier} {number}".strip()


def flight_key(flight_number: str) -> str:
    return re.sub(r"\s+", "", flight_number or "").upper()


def default_arrival(dep: datetime, arr: Optional[datetime], warnings: list[str]) -> datetime:
    if arr is not None and arr >= dep - timedelta(hours=26):
        return arr
    warnings.append("Arrival time unknown; set to departure time")
    return dep
