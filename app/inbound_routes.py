"""/inbound: your forwarding address and the log of emails the server received for you."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from . import inbound, models
from .auth import get_current_user
from .database import get_db

router = APIRouter(prefix="/inbound", tags=["email-in"])
Me = Depends(get_current_user)


def _settings(db: Session, me: models.User, regenerate: bool = False) -> dict:
    on = inbound.enabled()
    address = inbound.address_for(db, me, regenerate) if on else None
    if not on:
        message = "Your server's admin hasn't set up email forwarding. SELF_HOSTING.md → Email-in explains how."
    elif address:
        message = "Forward booking confirmations, calendar invites, boarding passes or PDF receipts here."
    else:
        message = f"Forward bookings from {me.email} to your server's Trippy mailbox; your admin has the address."
    return {"enabled": on, "mode": inbound.mode() if on else "off", "address": address,
            "sender_match": on and inbound.sender_match(), "account_email": me.email, "message": message}


@router.get("/settings")
def settings(db: Session = Depends(get_db), me: models.User = Me):
    return _settings(db, me)


@router.post("/address/regenerate")
def regenerate(db: Session = Depends(get_db), me: models.User = Me):
    """New address; the old one stops working at once."""
    if not inbound.enabled() or not inbound.template():
        raise HTTPException(status_code=400, detail="This server doesn't give out forwarding addresses")
    return _settings(db, me, regenerate=True)


def _rows(db: Session, me: models.User):
    return db.query(models.InboundEmail).filter(models.InboundEmail.user_id == me.id)


def _row(db: Session, me: models.User, email_id: int) -> models.InboundEmail:
    row = _rows(db, me).filter(models.InboundEmail.id == email_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Email not found")
    return row


@router.get("/emails")
def list_emails(limit: int = 100, before_id: Optional[int] = None, db: Session = Depends(get_db), me: models.User = Me):
    q = _rows(db, me)
    if before_id:
        q = q.filter(models.InboundEmail.id < before_id)
    return [inbound.summary(r) for r in q.order_by(models.InboundEmail.id.desc()).limit(max(1, min(limit, 200)))]


@router.get("/emails/unread")
def unread(db: Session = Depends(get_db), me: models.User = Me):
    q = _rows(db, me).filter(models.InboundEmail.seen.is_(False))
    return {"unread": q.count(), "failed": q.filter(models.InboundEmail.status == "failed").count(),
            "enabled": inbound.enabled()}


@router.post("/emails/seen")
def mark_seen(db: Session = Depends(get_db), me: models.User = Me):
    n = _rows(db, me).filter(models.InboundEmail.seen.is_(False)).update({"seen": True})
    db.commit()
    return {"marked": n}


@router.get("/emails/{email_id}")
def get_email(email_id: int, db: Session = Depends(get_db), me: models.User = Me):
    return inbound.summary(_row(db, me, email_id))


@router.post("/emails/{email_id}/retry")
def retry(email_id: int, db: Session = Depends(get_db), me: models.User = Me):
    row = _row(db, me, email_id)
    if row.raw is None:
        raise HTTPException(status_code=400, detail="The original email is no longer kept; forward it again")
    return inbound.summary(inbound.process(row, db, me))


@router.delete("/emails/{email_id}", status_code=204)
def delete_email(email_id: int, db: Session = Depends(get_db), me: models.User = Me):
    """Removes the log entry and the stored message. Imported bookings stay."""
    db.delete(_row(db, me, email_id))
    db.commit()
