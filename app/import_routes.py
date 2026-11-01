"""POST /import/preview and /import/commit (see IMPORTERS.md)."""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import drives, models
from .auth import RateLimiter, get_current_user
from .database import get_db
from .importers import ics, service
from .importers.common import ImportError_

router = APIRouter(prefix="/import", tags=["import"])
Me = Depends(get_current_user)


class PreviewRequest(BaseModel):
    source: Literal["ics", "ics_url", "flighty_csv", "pkpass", "email", "csv", "google_timeline"]
    text: Optional[str] = None
    data_base64: Optional[str] = None
    url: Optional[str] = None
    filename: Optional[str] = None
    csv_kind: Literal["flight", "rental", "lodging"] = "flight"
    mapping: Optional[Dict[str, str]] = None
    timezone: Optional[str] = Field(default=None, max_length=64)  # IANA; Takeout timelines are UTC
    drives_scope: Literal["trips", "all"] = "trips"  # timeline: only drives during your trips/journeys


class CommitItem(BaseModel):
    kind: Literal["flight", "rental", "lodging", "drive"]
    fields: Dict[str, Any]


class CommitRequest(BaseModel):
    items: List[CommitItem] = Field(default_factory=list, max_length=2000)
    trip_id: Optional[int] = None
    auto_trip: bool = True


_url_limit = RateLimiter("import-url", 20, 300)


@router.get("/sources")
def sources(me: models.User = Me):
    """What the app can import, for the picker."""
    return [
        {"source": "ics", "title": "Calendar file (.ics)", "files": ["ics"]},
        {"source": "ics_url", "title": "Calendar feed link (TripIt, Google, Outlook, iCloud)", "files": []},
        {"source": "flighty_csv", "title": "Flighty export (CSV)", "files": ["csv"]},
        {"source": "pkpass", "title": "Apple Wallet boarding pass", "files": ["pkpass"]},
        {"source": "email", "title": "Confirmation email (.eml or pasted text)", "files": ["eml", "txt", "html"]},
        {"source": "csv", "title": "Any CSV (map the columns)", "files": ["csv"]},
        {"source": "google_timeline", "title": "Google Maps Timeline (drives)", "files": ["json"]},
    ]


@router.post("/preview")
def preview(body: PreviewRequest, request: Request, db: Session = Depends(get_db), me: models.User = Me,
            request_limit: None = Depends(RateLimiter("import-preview", 120, 300))):
    try:
        if body.source == "ics_url":
            _url_limit(request)  # the server fetches the URL, so these are limited separately
            if not body.url:
                raise ImportError_("Paste the calendar link")
            data = ics.fetch_feed(body.url)
        else:
            limit = service.MAX_TIMELINE_UPLOAD if body.source == "google_timeline" else service.MAX_UPLOAD
            data = service.decode_payload(body.text, body.data_base64, limit)
        result = service.run_parser(body.source, data, body.filename or "", body.csv_kind, body.mapping,
                                    body.timezone)
        del data
    except ImportError_ as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if body.source == "google_timeline":
        result["stats"].update(drives.annotate_preview(db, me, result["items"], body.drives_scope))
        if len(result["items"]) > service.MAX_DRIVES:
            result["stats"]["truncated"] = len(result["items"]) - service.MAX_DRIVES
            result["items"] = result["items"][-service.MAX_DRIVES:]  # the most recent ones
    service.mark_duplicates(db, me, result["items"])
    result["source"] = body.source
    result["new_count"] = sum(1 for i in result["items"] if not i["duplicate_of"] and i["duplicate_in_batch"] is None)
    return jsonable_encoder(result)


@router.post("/commit")
def commit(body: CommitRequest, db: Session = Depends(get_db), me: models.User = Me):
    if not body.items:
        raise HTTPException(status_code=400, detail="Nothing selected to import")
    try:
        return service.commit(db, me, [i.model_dump() for i in body.items], body.trip_id, body.auto_trip)
    except ImportError_ as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
