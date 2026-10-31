"""Live flight status from a third-party provider. Off unless TRIPPY_FLIGHT_STATUS_PROVIDER is set.

  TRIPPY_FLIGHT_STATUS_PROVIDER   aerodatabox | aviationstack | aeroapi   (empty = off)
  TRIPPY_FLIGHT_STATUS_API_KEY    the provider key (never logged or returned)
  TRIPPY_FLIGHT_STATUS_BASE_URL   optional override (e.g. AeroDataBox via API.market instead of RapidAPI)
  TRIPPY_FLIGHT_STATUS_CACHE_SECONDS  how long one answer is reused (default 900) — free tiers are small

OpenSky is not offered: it has no schedules, gates or delays, only live positions by transponder.
Requests only ever go to the configured provider host; nothing user-supplied becomes a URL.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Callable, Dict, Optional, Tuple

FLIGHT_RE = re.compile(r"^([A-Z0-9]{2}|[A-Z]{3})\s*0*(\d{1,4})[A-Z]?$")


class StatusError(Exception):
    """The provider failed or returned nothing usable; the message is safe to show."""


@dataclass
class FlightStatus:
    provider: str
    status: str  # scheduled / delayed / departed / en_route / landed / cancelled / diverted / unknown
    departure_scheduled: Optional[str] = None
    departure_estimated: Optional[str] = None
    departure_actual: Optional[str] = None
    departure_terminal: Optional[str] = None
    departure_gate: Optional[str] = None
    arrival_scheduled: Optional[str] = None
    arrival_estimated: Optional[str] = None
    arrival_actual: Optional[str] = None
    arrival_terminal: Optional[str] = None
    arrival_gate: Optional[str] = None
    baggage_claim: Optional[str] = None
    delay_minutes: Optional[int] = None
    fetched_at: str = field(default_factory=lambda: datetime.utcnow().replace(microsecond=0).isoformat() + "Z")

    def to_dict(self) -> dict:
        return asdict(self)


def split_flight_number(text: str) -> Optional[Tuple[str, str]]:
    m = FLIGHT_RE.match(re.sub(r"\s+", " ", (text or "").strip().upper()))
    return (m.group(1), m.group(2)) if m else None


def _norm_status(raw: Optional[str]) -> str:
    s = (raw or "").strip().lower().replace("-", " ").replace("_", " ")
    for key, words in (("cancelled", ("cancel",)), ("diverted", ("divert",)), ("landed", ("landed", "arrived")),
                       ("en_route", ("en route", "enroute", "active", "airborne")),
                       ("departed", ("departed", "boarding closed", "gate closed")),
                       ("delayed", ("delay",)), ("scheduled", ("scheduled", "expected", "on time", "check in",
                                                              "boarding", "gate"))):
        if any(w in s for w in words):
            return key
    return "unknown"


def _minutes(a: Optional[str], b: Optional[str]) -> Optional[int]:
    try:
        x = datetime.fromisoformat(a.replace("Z", "+00:00").replace(" ", "T"))
        y = datetime.fromisoformat(b.replace("Z", "+00:00").replace(" ", "T"))
        return int((y - x).total_seconds() // 60)
    except Exception:
        return None


Fetch = Callable[[str, Dict[str, str]], object]


def _http_get(url: str, headers: Dict[str, str]) -> object:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "trippy", **headers})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 - fixed provider host
            body = resp.read(2_000_000)
    except urllib.error.HTTPError as e:
        if e.code == 204:
            return None
        if e.code in (401, 403):
            raise StatusError("The flight status provider rejected the API key.") from None
        if e.code == 402:
            raise StatusError("The flight status provider says the plan has no API units left (402). "
                              "Renew the plan or add credits.") from None
        if e.code == 429:
            raise StatusError("The flight status provider's quota is used up for now.") from None
        raise StatusError(f"The flight status provider answered {e.code}.") from None
    except Exception:
        raise StatusError("Couldn't reach the flight status provider.") from None
    return json.loads(body) if body.strip() else None


# --- providers ---------------------------------------------------------------------------------

def _t(d: dict, *path):
    for p in path:
        if not isinstance(d, dict):
            return None
        d = d.get(p)
    return d if isinstance(d, str) and d else None


def _aerodatabox_headers(host: str, key: str) -> Dict[str, str]:
    """Each AeroDataBox channel has its own gateway and key header (aerodatabox.com/api-spec)."""
    if "rapidapi" in host:
        return {"X-RapidAPI-Key": key, "X-RapidAPI-Host": host}
    if "api.market" in host:
        return {"x-api-market-key": key}
    return {"X-Api-Key": key}  # direct: https://api.aerodatabox.com


def aerodatabox(carrier: str, number: str, day: date, key: str, base: str, fetch: Fetch) -> Optional[FlightStatus]:
    base = base or "https://aerodatabox.p.rapidapi.com"
    host = urllib.parse.urlparse(base).hostname or ""
    headers = _aerodatabox_headers(host, key)
    url = f"{base.rstrip('/')}/flights/number/{carrier}{number}/{day.isoformat()}?withAircraftImage=false&withLocation=false"
    data = fetch(url, headers)
    rows = data if isinstance(data, list) else []
    if not rows:
        return None
    f = rows[0]
    dep, arr = f.get("departure") or {}, f.get("arrival") or {}
    ds = _t(dep, "scheduledTime", "local") or _t(dep, "scheduledTimeLocal")
    de = _t(dep, "revisedTime", "local") or _t(dep, "predictedTime", "local")
    da = _t(dep, "runwayTime", "local")
    st = FlightStatus(
        provider="aerodatabox", status=_norm_status(f.get("status")),
        departure_scheduled=ds, departure_estimated=de, departure_actual=da,
        departure_terminal=dep.get("terminal"), departure_gate=dep.get("gate"),
        arrival_scheduled=_t(arr, "scheduledTime", "local") or _t(arr, "scheduledTimeLocal"),
        arrival_estimated=_t(arr, "revisedTime", "local") or _t(arr, "predictedTime", "local"),
        arrival_actual=_t(arr, "runwayTime", "local"),
        arrival_terminal=arr.get("terminal"), arrival_gate=arr.get("gate"), baggage_claim=arr.get("baggageBelt"))
    st.delay_minutes = _minutes(ds, de or da)
    return st


def aviationstack(carrier: str, number: str, day: date, key: str, base: str, fetch: Fetch) -> Optional[FlightStatus]:
    # The free plan is HTTP-only; set TRIPPY_FLIGHT_STATUS_BASE_URL=https://... on a paid plan.
    base = base or "http://api.aviationstack.com/v1"
    q = urllib.parse.urlencode({"access_key": key, "flight_iata": f"{carrier}{number}"})
    data = fetch(f"{base.rstrip('/')}/flights?{q}", {})
    rows = (data or {}).get("data") if isinstance(data, dict) else None
    if isinstance(data, dict) and data.get("error"):
        raise StatusError("The flight status provider refused the request (check the key or plan).")
    rows = [r for r in rows or [] if r.get("flight_date") == day.isoformat()]
    if not rows:
        return None
    f = rows[0]
    dep, arr = f.get("departure") or {}, f.get("arrival") or {}
    return FlightStatus(
        provider="aviationstack", status=_norm_status(f.get("flight_status")),
        departure_scheduled=dep.get("scheduled"), departure_estimated=dep.get("estimated"),
        departure_actual=dep.get("actual"), departure_terminal=dep.get("terminal"), departure_gate=dep.get("gate"),
        arrival_scheduled=arr.get("scheduled"), arrival_estimated=arr.get("estimated"),
        arrival_actual=arr.get("actual"), arrival_terminal=arr.get("terminal"), arrival_gate=arr.get("gate"),
        baggage_claim=arr.get("baggage"), delay_minutes=dep.get("delay"))


def aeroapi(carrier: str, number: str, day: date, key: str, base: str, fetch: Fetch) -> Optional[FlightStatus]:
    base = base or "https://aeroapi.flightaware.com/aeroapi"
    q = urllib.parse.urlencode({"ident_type": "designator", "start": day.isoformat(),
                                "end": date.fromordinal(day.toordinal() + 1).isoformat()})
    data = fetch(f"{base.rstrip('/')}/flights/{carrier}{number}?{q}", {"x-apikey": key})
    rows = (data or {}).get("flights") if isinstance(data, dict) else None
    if not rows:
        return None
    f = rows[0]
    raw = "cancelled" if f.get("cancelled") else "diverted" if f.get("diverted") else f.get("status")
    delay = f.get("departure_delay")
    return FlightStatus(
        provider="aeroapi", status=_norm_status(raw),
        departure_scheduled=f.get("scheduled_out"), departure_estimated=f.get("estimated_out"),
        departure_actual=f.get("actual_out"), departure_terminal=f.get("terminal_origin"),
        departure_gate=f.get("gate_origin"), arrival_scheduled=f.get("scheduled_in"),
        arrival_estimated=f.get("estimated_in"), arrival_actual=f.get("actual_in"),
        arrival_terminal=f.get("terminal_destination"), arrival_gate=f.get("gate_destination"),
        baggage_claim=f.get("baggage_claim"), delay_minutes=int(delay // 60) if isinstance(delay, (int, float)) else None)


PROVIDERS = {"aerodatabox": aerodatabox, "aviationstack": aviationstack, "aeroapi": aeroapi}


def configured() -> Optional[str]:
    name = os.getenv("TRIPPY_FLIGHT_STATUS_PROVIDER", "").strip().lower()
    if name in PROVIDERS and os.getenv("TRIPPY_FLIGHT_STATUS_API_KEY", "").strip():
        return name
    return None


_cache: Dict[Tuple[str, str, str, str], Tuple[float, Optional[FlightStatus]]] = {}
_lock = threading.Lock()


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def lookup(carrier: str, number: str, day: date, fetch: Fetch = _http_get) -> Optional[FlightStatus]:
    name = configured()
    if not name:
        raise LookupError("not configured")
    ttl = int(os.getenv("TRIPPY_FLIGHT_STATUS_CACHE_SECONDS", "900") or 900)
    key = (name, carrier, number, day.isoformat())
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    result = PROVIDERS[name](carrier, number, day, os.environ["TRIPPY_FLIGHT_STATUS_API_KEY"].strip(),
                             os.getenv("TRIPPY_FLIGHT_STATUS_BASE_URL", "").strip(), fetch)
    with _lock:
        _cache[key] = (now, result)
    return result
