"""GET /flights/{id}/status: live status from the configured provider, or a 'not configured' answer."""
from __future__ import annotations

from datetime import date as date_type, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from . import access, flight_status, models
from .auth import RateLimiter, get_current_user
from .database import get_db

router = APIRouter(tags=["flight status"])
_limit = RateLimiter("flight-status", 60, 300)

# Providers only know flights from about a day before departure; asking earlier wastes free quota.
WINDOW_BEFORE = timedelta(days=2)
WINDOW_AFTER = timedelta(days=1)


def _iso_local(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.strip().replace("Z", "+00:00").replace(" ", "T")).replace(tzinfo=None).isoformat()
    except ValueError:
        return raw


@router.get("/flights/lookup")
def lookup_flight_schedule(flight_number: str = "", date: str = "",
                           user: models.User = Depends(get_current_user), _rl: None = Depends(_limit)):
    """Look up a flight's schedule/airports/times by number and date (YYYY-MM-DD) without persisting a Flight row."""
    provider = flight_status.configured()
    if not provider:
        raise HTTPException(status_code=503, detail="Live flight status isn't configured on this server.")
    parts = flight_status.split_flight_number(flight_number or "")
    if not parts:
        raise HTTPException(status_code=400, detail="Enter a flight number like UA 123.")
    try:
        day = date_type.fromisoformat((date or "").strip()[:10])
    except ValueError:
        raise HTTPException(status_code=400, detail="Enter a date as YYYY-MM-DD.") from None
    try:
        st = flight_status.lookup(parts[0], parts[1], day)
    except flight_status.StatusError as e:
        raise HTTPException(status_code=502, detail=str(e)) from None
    if st is None:
        raise HTTPException(status_code=404, detail="No schedule found for that flight and date.")
    d = st.to_dict()
    return {
        "configured": True,
        "provider": provider,
        "flight_number": f"{parts[0]} {parts[1]}",
        "date": day.isoformat(),
        "departure_time": _iso_local(st.departure_estimated or st.departure_scheduled),
        "arrival_time": _iso_local(st.arrival_estimated or st.arrival_scheduled),
        "terminal": st.departure_terminal,
        "gate": st.departure_gate,
        "status": d,
        **d,
    }



@router.get("/flights/{flight_id}/status")
def flight_live_status(flight_id: int, db: Session = Depends(get_db),
                       user: models.User = Depends(get_current_user), _rl: None = Depends(_limit)):
    flight = access.flights(db, user).filter(models.Flight.id == flight_id).first()
    if not flight:
        raise HTTPException(status_code=404, detail="Flight not found")
    provider = flight_status.configured()
    base = {"configured": provider is not None, "provider": provider, "status": None}
    if not provider:
        return {**base, "message": "Live flight status isn't configured on this server."}
    parts = flight_status.split_flight_number(flight.flight_number or "")
    if not parts or not flight.departure_time:
        return {**base, "message": "This flight needs a flight number like UA 123 and a departure date."}
    now = datetime.utcnow()
    dep = flight.departure_time.replace(tzinfo=None)
    if dep - now > WINDOW_BEFORE:
        return {**base, "message": "Live status appears about two days before departure."}
    if now - dep > WINDOW_AFTER + timedelta(days=1):
        return {**base, "message": "This flight is in the past."}
    try:
        st = flight_status.lookup(parts[0], parts[1], dep.date())
    except flight_status.StatusError as e:
        raise HTTPException(status_code=502, detail=str(e)) from None
    if st is None:
        return {**base, "message": "The provider has no status for this flight yet."}
    return {**base, "status": st.to_dict(), "message": None}
