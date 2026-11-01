"""Email-in: forward a booking to your own Trippy server and it lands on the right trip.

Off unless the server's admin turns it on. Nothing here talks to a central service: the host
points Trippy at a mailbox they already have (IMAP polling, the default) or, optionally, lets
Trippy receive mail itself on an SMTP port. See SELF_HOSTING.md → "Email-in".

Environment (all optional; read at call time so tests can change them):
  TRIPPY_INBOUND_MODE              off (default) | imap | smtp
  TRIPPY_INBOUND_ADDRESS_TEMPLATE  per-user address, {token} is replaced, e.g.
                                     trips+{token}@example.com    (plus-addressing)
                                     {token}@trips.example.com    (catch-all domain)
                                   Empty: no per-user addresses; mail is matched by sender only.
  TRIPPY_INBOUND_SENDER_MATCH      on (default) | off   accept mail From a user's account email
  TRIPPY_INBOUND_REQUIRE_AUTH      on (default) | off   for sender matching, need SPF/DKIM/DMARC pass
                                                        in the mailbox provider's Authentication-Results
  TRIPPY_INBOUND_IMAP_HOST, _PORT (993), _SECURITY ssl (default) | starttls | none,
  TRIPPY_INBOUND_IMAP_USERNAME, _PASSWORD, _FOLDER (INBOX),
  TRIPPY_INBOUND_IMAP_PROCESSED_FOLDER (Trippy-Processed; empty = only mark as read),
  TRIPPY_INBOUND_IMAP_INTERVAL     seconds between polls (default 300, minimum 30)
  TRIPPY_INBOUND_SMTP_HOST (0.0.0.0), TRIPPY_INBOUND_SMTP_PORT (2525)
  TRIPPY_INBOUND_MAX_BYTES         largest message accepted (default 15 MB)
  TRIPPY_INBOUND_MAX_PER_HOUR      per user (default 60)
"""
from __future__ import annotations

import email
import email.policy
import email.utils
import hashlib
import imaplib
import io
import json
import logging
import os
import re
import secrets
import ssl
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from . import access, airports, models
from .importers import emails as email_parser, ics, pkpass, service
from .importers.common import ImportError_

log = logging.getLogger("trippy.inbound")

ATTACHMENT_TYPES = {  # extension -> parser kind; everything else is ignored, never opened
    ".ics": "ics", ".ical": "ics", ".pkpass": "pkpass", ".pdf": "pdf", ".eml": "eml",
    ".txt": "text", ".html": "text", ".htm": "text",
}
CONTENT_TYPES = {"text/calendar": "ics", "application/ics": "ics", "application/vnd.apple.pkpass": "pkpass",
                 "application/pdf": "pdf", "message/rfc822": "eml"}
MAX_ATTACHMENT = 5 * 1024 * 1024
MAX_ATTACHMENTS = 10
MAX_PDF_PAGES = 20
RAW_KEEP_DAYS = 30  # raw messages are dropped after this; the log row stays


# --- settings ------------------------------------------------------------------

def _env(name: str, default: str = "") -> str:
    return os.getenv(f"TRIPPY_INBOUND_{name}", default).strip()


def _on(name: str, default: bool) -> bool:
    v = _env(name).lower()
    return default if not v else v in ("1", "on", "yes", "true")


def mode() -> str:
    m = _env("MODE", "off").lower()
    return m if m in ("imap", "smtp") else "off"


def enabled() -> bool:
    if mode() == "imap":
        return bool(_env("IMAP_HOST") and _env("IMAP_USERNAME"))
    return mode() == "smtp"


def template() -> str:
    t = _env("ADDRESS_TEMPLATE")
    return t if "{token}" in t and "@" in t else ""


def max_bytes() -> int:
    try:
        return max(64 * 1024, int(_env("MAX_BYTES") or 15 * 1024 * 1024))
    except ValueError:
        return 15 * 1024 * 1024


def max_per_hour() -> int:
    try:
        return max(1, int(_env("MAX_PER_HOUR") or 60))
    except ValueError:
        return 60


def sender_match() -> bool:
    if mode() == "smtp" and not _on("SMTP_TRUST_AUTH_HEADERS", False):
        return False
    return _on("SENDER_MATCH", True)


def require_auth() -> bool:
    return _on("REQUIRE_AUTH", True)


STATUS = {"last_poll": None, "last_ok": None, "last_error": None, "processed": 0, "running": False}


def status() -> dict:
    """For /health: safe to show anyone (no hostnames, addresses or error text)."""
    return {"enabled": enabled(), "mode": mode() if enabled() else "off",
            "addresses": "per-user" if template() else "sender-only",
            "last_poll": STATUS["last_poll"].isoformat() + "Z" if STATUS["last_poll"] else None,
            "ok": STATUS["last_error"] is None if STATUS["last_poll"] else None}


# --- per-user addresses --------------------------------------------------------

_ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"  # lower case only: mail servers fold local parts


def new_token() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(12))


def address_for(db: Session, user: models.User, regenerate: bool = False) -> Optional[str]:
    if not template():
        return None
    if regenerate or not user.inbound_token:
        while True:
            tok = new_token()
            if not db.query(models.User).filter(models.User.inbound_token == tok).first():
                break
        user.inbound_token = tok
        db.commit()
    return template().replace("{token}", user.inbound_token)


def _token_pattern() -> Optional[re.Pattern]:
    t = template()
    if not t:
        return None
    local, domain = t.lower().rsplit("@", 1)
    return re.compile("^" + re.escape(local).replace(re.escape("{token}"), "([a-z0-9]{8,40})") + "@" +
                      re.escape(domain).replace(re.escape("{token}"), "([a-z0-9]{8,40})") + "$")


def token_from(address: str) -> Optional[str]:
    pat = _token_pattern()
    m = pat.match(address.strip().lower()) if pat else None
    return next((g for g in m.groups() if g), None) if m else None


def accepts_recipient(address: str) -> bool:
    """SMTP mode: only take mail for addresses that look like ours (no open relay, no backscatter)."""
    if token_from(address):
        return True
    t = template()
    domain = (t.rsplit("@", 1)[1] if t else _env("SMTP_DOMAIN")).lower()
    return bool(domain and "{token}" not in domain and address.strip().lower().endswith("@" + domain))


# --- routing -------------------------------------------------------------------

def _addresses(msg, *headers: str) -> list[str]:
    vals = []
    for h in headers:
        vals += [str(v) for v in (msg.get_all(h) or [])]
    return [a.lower() for _, a in email.utils.getaddresses(vals) if a]


def _authenticated(msg, sender: str) -> bool:
    """The receiving provider vouches for the From domain (SPF, DKIM or DMARC pass)."""
    headers = msg.get_all("Authentication-Results") or []
    if not headers:
        return False
    # Only trust the topmost Authentication-Results header (added by our immediate MX / IMAP provider).
    results = str(headers[0]).lower()
    if not results:
        return False
    if re.search(r"\bdmarc=(fail|reject|quarantine)", results):
        return False
    domain = sender.rsplit("@", 1)[-1].lower()
    if not domain:
        return False
    dom_pat = r"(?:^|[=@.\s])" + re.escape(domain) + r"(?:$|[;\s)])"
    for m in re.finditer(r"\bdmarc=pass\b([^;]*)", results):
        clause = m.group(1)
        if "header.from=" in clause:
            if re.search(r"header\.from=(?:[^;\s]*@)?" + re.escape(domain) + r"(?:$|[;\s)])", clause):
                return True
        elif re.search(dom_pat, results):
            return True
    for m in re.finditer(r"\b(spf|dkim)=pass\b([^;]*)", results):
        if re.search(dom_pat, m.group(2)):
            return True
    return False


def route(db: Session, msg, envelope_to: tuple[str, ...] = ()) -> tuple[Optional[models.User], Optional[str]]:
    """(user, "token" | "sender") or (None, None) to ignore."""
    for a in list(envelope_to) + _addresses(msg, "Delivered-To", "X-Original-To", "Envelope-To", "To", "Cc"):
        tok = token_from(a)
        if tok:
            u = db.query(models.User).filter(models.User.inbound_token == tok).first()
            if u and not u.is_placeholder:
                return u, "token"
    if not sender_match():
        return None, None
    froms = _addresses(msg, "From")
    if len(froms) != 1:
        return None, None
    sender = froms[0]
    if require_auth() and not _authenticated(msg, sender):
        return None, None
    u = db.query(models.User).filter(models.User.email.ilike(sender)).first()
    if u and not u.is_placeholder and u.hashed_password:
        return u, "sender"
    return None, None


# --- reading a message ---------------------------------------------------------

def message_id(msg, raw: bytes) -> str:
    mid = (msg.get("Message-ID") or "").strip()
    return mid[:250] if mid else "sha256:" + hashlib.sha256(raw).hexdigest()


MAX_PDF_TEXT = 256 * 1024


def _pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:  # optional dependency
        return ""
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            return ""
        chunks: list[str] = []
        total = 0
        for p in reader.pages[:MAX_PDF_PAGES]:
            t = p.extract_text() or ""
            chunks.append(t)
            total += len(t)
            if total >= MAX_PDF_TEXT:
                break
        return "\n".join(chunks)[:MAX_PDF_TEXT]
    except Exception:
        return ""


def attachments(msg) -> list[tuple[str, str, bytes]]:
    """(kind, filename, bytes) for parts we know how to read. Never renders or runs anything."""
    out = []
    for part in msg.walk():
        if part.is_multipart() and part.get_content_type() != "message/rfc822":
            continue
        name = (part.get_filename() or "").strip()
        ext = os.path.splitext(name.lower())[1]
        ctype = part.get_content_type()
        disp = (part.get_content_disposition() or "")
        kind = ATTACHMENT_TYPES.get(ext) or CONTENT_TYPES.get(ctype)
        if not kind or (kind == "text" and disp != "attachment"):
            continue  # inline bodies are read as the email itself
        if ctype == "message/rfc822":
            inner = part.get_payload()
            data = (inner[0] if isinstance(inner, list) and inner else inner)
            data = data.as_bytes() if hasattr(data, "as_bytes") else b""
        else:
            data = part.get_payload(decode=True) or b""
        if data and len(data) <= MAX_ATTACHMENT:
            out.append((kind, name or ctype, data))
        if len(out) >= MAX_ATTACHMENTS:
            break
    return out


def extract(raw: bytes) -> tuple[list[dict], list[dict]]:
    """Every booking found in the message and its attachments, plus a note per part."""
    items: list[dict] = []
    parts: list[dict] = []
    msg = email.message_from_bytes(raw, policy=email.policy.default)

    def run(label: str, fn):
        try:
            got, _ = fn()
        except ImportError_ as exc:
            parts.append({"part": label, "found": 0, "note": str(exc)})
            return
        except Exception as exc:  # a broken attachment shouldn't sink the rest
            log.warning("inbound: couldn't read %s: %s", label, exc)
            parts.append({"part": label, "found": 0, "note": "couldn't read"})
            return
        items.extend(got)
        parts.append({"part": label, "found": len(got)})

    run("email", lambda: email_parser.parse_email(raw, "message.eml"))
    for kind, name, data in attachments(msg):
        if kind == "ics":
            run(name, lambda d=data: ics.parse_ics(d, source="ics"))
        elif kind == "pkpass":
            run(name, lambda d=data: pkpass.parse_pkpass(d))
        elif kind == "pdf":
            text = _pdf_text(data)
            if text.strip():
                run(name, lambda t=text: email_parser.parse_email(t.encode(), "receipt.txt"))
            else:
                parts.append({"part": name, "found": 0, "note": "no text in this PDF"})
        else:
            run(name, lambda d=data, n=name: email_parser.parse_email(d, n if kind != "eml" else "forwarded.eml"))
    return items, parts


# --- putting items on trips ----------------------------------------------------

def _place(kind: str, f: dict) -> Optional[str]:
    if kind == "flight":
        return f.get("arrival_airport")
    if kind == "rental":
        return f.get("pickup_code") or f.get("pickup_location")
    return f.get("city")


def _end(kind: str, f: dict) -> Optional[datetime]:
    return f.get({"flight": "arrival_time", "rental": "dropoff_time", "lodging": "check_out"}[kind]) or service._start(kind, f)


def _city_of(code_or_city: Optional[str]) -> Optional[str]:
    if not code_or_city:
        return None
    a = airports.lookup(code_or_city) if len(code_or_city) == 3 else None
    return a[0] if a else code_or_city


def _trip_for(db: Session, user: models.User, kind: str, f: dict) -> Optional[models.Trip]:
    """An owned trip covering the item's dates (a day of slack), preferring one at the same place."""
    when = service._start(kind, f)
    if not when:
        return None
    hits = [t for t in access.trips(db, user).filter(models.Trip.owner_id == user.id).all()
            if t.start_date and t.end_date and
            t.start_date.date() - timedelta(days=1) <= when.date() <= t.end_date.date() + timedelta(days=1)]
    if len(hits) <= 1:
        return hits[0] if hits else None
    place = (_city_of(_place(kind, f)) or "").lower()

    def places(t):
        out = {(l.city or "").lower() for l in t.lodgings}
        out |= {(_city_of(x.arrival_airport) or "").lower() for x in t.flights}
        out |= {(_city_of(x.departure_airport) or "").lower() for x in t.flights}
        return out
    return next((t for t in hits if place and place in places(t)), hits[0])


def _cluster(rows: list[tuple[str, dict, int]]) -> list[list[tuple[str, dict, int]]]:
    """Unattached items whose dates are within 3 days of each other become one new trip."""
    rows = sorted(rows, key=lambda r: service._start(r[0], r[1]) or datetime.max)
    groups: list[list] = []
    last_end = None
    for r in rows:
        s = service._start(r[0], r[1])
        if groups and s and last_end and s - last_end <= timedelta(days=3):
            groups[-1].append(r)
        else:
            groups.append([r])
        e = _end(r[0], r[1])
        last_end = max(filter(None, [last_end, e])) if (last_end or e) else None
    return groups


def _new_trip_title(group: list[tuple[str, dict, int]], home: Optional[str]) -> str:
    names = []
    for kind, f, _ in group:
        c = _city_of(_place(kind, f))
        if c and c not in names and (not home or c != _city_of(home)):
            names.append(c)
    return (" → ".join(names[:3]) if names else "Trip") + " (email)"


def file_items(db: Session, user: models.User, items: list[dict]) -> dict:
    """Validate, skip duplicates, attach to a trip by date and place or make a new trip."""
    created, skipped, new_trips = [], [], []
    seen: set = set()
    pending: list[tuple[str, dict, int]] = []
    for i, it in enumerate(items):
        kind = it["kind"]
        try:
            data = service.validate(kind, it.get("fields") or {})
        except ImportError_ as exc:
            skipped.append({"kind": kind, "reason": str(exc), "summary": it.get("summary")})
            continue
        key = service._batch_key(kind, data)
        dup = service.find_duplicate(db, user, kind, data)
        if dup or key in seen:
            skipped.append({"kind": kind, "reason": service.dup_reason(db, kind, dup) if dup else "duplicate",
                            "duplicate_of": dup, "summary": it.get("summary")})
            continue
        seen.add(key)
        pending.append((kind, data, i))
    unattached = []
    placed: list[tuple[str, dict, int, Optional[models.Trip]]] = []
    for kind, data, i in pending:
        t = _trip_for(db, user, kind, data)
        if t:
            placed.append((kind, data, i, t))
        else:
            unattached.append((kind, data, i))
    for group in _cluster(unattached):
        starts = [s for s in (service._start(k, f) for k, f, _ in group) if s]
        ends = [e for e in (_end(k, f) for k, f, _ in group) if e]
        if not starts:
            placed += [(k, f, i, None) for k, f, i in group]
            continue
        t = models.Trip(title=_new_trip_title(group, user.home_airport), owner_id=user.id, title_auto=True,
                        start_date=min(starts), end_date=max(ends or starts),
                        description="Created from a forwarded email")
        db.add(t)
        db.flush()
        new_trips.append(t.id)
        placed += [(k, f, i, t) for k, f, i in group]
    model = {"flight": models.Flight, "rental": models.RentalCar, "lodging": models.Lodging}
    for kind, data, i, t in placed:
        row = model[kind](**data, owner_id=user.id, trip_id=t.id if t else None)
        db.add(row)
        db.flush()
        if t:  # widen the trip if the booking runs past it
            s, e = service._start(kind, data), _end(kind, data)
            if s and t.start_date and s < t.start_date:
                t.start_date = s
            if e and t.end_date and e > t.end_date:
                t.end_date = e
        created.append({"kind": kind, "id": row.id, "trip_id": row.trip_id, "summary": items[i].get("summary")})
    return {"created": created, "skipped": skipped, "new_trip_ids": new_trips}


# --- the inbox log ---------------------------------------------------------------

def _recent_count(db: Session, user: models.User) -> int:
    since = datetime.utcnow() - timedelta(hours=1)
    return db.query(models.InboundEmail).filter(models.InboundEmail.user_id == user.id,
                                                models.InboundEmail.received_at >= since).count()


def process(row: models.InboundEmail, db: Session, user: models.User) -> models.InboundEmail:
    """(Re)read row.raw and file what it finds. Commits."""
    row.attempts = (row.attempts or 0) + 1
    row.error = None
    try:
        items, parts = extract(row.raw or b"")
        if not items:
            row.status, result = "nothing_found", {"created": [], "skipped": [], "new_trip_ids": []}
        else:
            result = file_items(db, user, items)
            row.status = "imported" if result["created"] else "duplicate"
        result["parts"] = parts
        row.result_json = json.dumps(result, default=str)
    except Exception as exc:
        db.rollback()
        log.exception("inbound: processing message %s failed", row.id)
        row = db.merge(row)
        row.status, row.error = "failed", str(exc)[:300] or exc.__class__.__name__
    row.seen = False
    db.commit()
    return row


def receive(db: Session, raw: bytes, envelope_to: tuple[str, ...] = ()) -> Optional[models.InboundEmail]:
    """Take one message from the mailbox or SMTP. Idempotent by Message-ID. None = ignored."""
    if len(raw) > max_bytes():
        log.info("inbound: ignored a %d-byte message (limit %d)", len(raw), max_bytes())
        return None
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    mid = message_id(msg, raw)
    user, how = route(db, msg, envelope_to)
    if not user:
        log.info("inbound: ignored a message nobody on this server is addressed by")
        return None
    existing = db.query(models.InboundEmail).filter(models.InboundEmail.user_id == user.id,
                                                    models.InboundEmail.message_id == mid).first()
    if existing:
        return existing
    sender = (_addresses(msg, "From") or [""])[0][:200]
    subject = str(msg.get("Subject") or "")[:300]
    row = models.InboundEmail(user_id=user.id, message_id=mid, sender=sender, subject=subject,
                              received_at=datetime.utcnow(), routed_by=how, raw=raw, seen=False, attempts=0,
                              status="pending")
    if _recent_count(db, user) >= max_per_hour():
        row.status, row.error = "failed", "Too many forwarded emails this hour; retry later"
        db.add(row)
        db.commit()
        return row
    db.add(row)
    db.commit()
    STATUS["processed"] += 1
    return process(row, db, user)


def prune(db: Session) -> None:
    cutoff = datetime.utcnow() - timedelta(days=RAW_KEEP_DAYS)
    db.query(models.InboundEmail).filter(models.InboundEmail.received_at < cutoff,
                                         models.InboundEmail.raw.isnot(None)).update({"raw": None})
    db.commit()


def summary(row: models.InboundEmail) -> dict:
    result = json.loads(row.result_json) if row.result_json else {}
    return {"id": row.id, "subject": row.subject, "sender": row.sender, "received_at": (row.received_at.replace(microsecond=0).isoformat() + "Z") if row.received_at else None,
            "status": row.status, "routed_by": row.routed_by, "error": row.error, "seen": bool(row.seen),
            "attempts": row.attempts or 0, "can_retry": row.raw is not None,
            "created": result.get("created", []), "skipped": result.get("skipped", []),
            "new_trip_ids": result.get("new_trip_ids", []), "parts": result.get("parts", [])}


# --- IMAP polling ----------------------------------------------------------------

def _imap() -> imaplib.IMAP4:
    host, security = _env("IMAP_HOST"), (_env("IMAP_SECURITY", "ssl") or "ssl").lower()
    port = int(_env("IMAP_PORT") or (993 if security == "ssl" else 143))
    ctx = ssl.create_default_context()
    if security == "ssl":
        conn = imaplib.IMAP4_SSL(host, port, ssl_context=ctx, timeout=30)
    else:
        conn = imaplib.IMAP4(host, port, timeout=30)
        if security == "starttls":
            conn.starttls(ssl_context=ctx)
    conn.login(_env("IMAP_USERNAME"), os.getenv("TRIPPY_INBOUND_IMAP_PASSWORD", ""))
    return conn


def _quote(folder: str) -> str:
    return '"' + folder.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _file_away(conn, uid: bytes, processed: str) -> None:
    conn.uid("STORE", uid, "+FLAGS", "(\\Seen)")
    if not processed:
        return
    caps = {c.decode().upper() if isinstance(c, bytes) else str(c).upper() for c in conn.capabilities}
    if "MOVE" in caps:
        conn.uid("MOVE", uid, _quote(processed))
    else:
        typ, _ = conn.uid("COPY", uid, _quote(processed))
        if typ == "OK":
            conn.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
            conn.expunge()


def poll_once(session_factory, connect=_imap) -> int:
    """Read every unread message in the folder, file it, mark it read and move it. Returns the count."""
    STATUS["last_poll"] = datetime.utcnow()
    n = 0
    try:
        conn = connect()
        try:
            processed = _env("IMAP_PROCESSED_FOLDER", "Trippy-Processed") if os.getenv(
                "TRIPPY_INBOUND_IMAP_PROCESSED_FOLDER") is None else _env("IMAP_PROCESSED_FOLDER")
            if processed:
                conn.create(_quote(processed))  # NO if it exists; that's fine
            typ, _ = conn.select(_quote(_env("IMAP_FOLDER", "INBOX") or "INBOX"))
            if typ != "OK":
                raise RuntimeError("couldn't open the mail folder")
            typ, data = conn.uid("SEARCH", None, "UNSEEN")
            uids = (data[0] or b"").split() if typ == "OK" else []
            for uid in uids[:200]:
                typ, parts = conn.uid("FETCH", uid, "(RFC822.SIZE BODY.PEEK[])")
                raw = next((p[1] for p in parts or [] if isinstance(p, tuple) and len(p) > 1), None)
                if typ != "OK" or raw is None:
                    continue
                db = session_factory()
                try:
                    receive(db, raw)
                    prune(db)
                finally:
                    db.close()
                _file_away(conn, uid, processed)
                n += 1
        finally:
            try:
                conn.logout()
            except Exception:
                pass
        STATUS["last_ok"], STATUS["last_error"] = datetime.utcnow(), None
    except Exception as exc:
        STATUS["last_error"] = str(exc)[:200] or exc.__class__.__name__
        log.warning("inbound: IMAP poll failed: %s", STATUS["last_error"])
    return n


def _interval() -> int:
    try:
        return max(30, int(_env("IMAP_INTERVAL") or 300))
    except ValueError:
        return 300


def start(session_factory) -> Optional[object]:
    """Called once at app startup. Starts the IMAP poller or SMTP receiver if configured."""
    if not enabled() or STATUS["running"]:
        return None
    STATUS["running"] = True
    if mode() == "imap":
        def loop():
            while True:
                poll_once(session_factory)
                time.sleep(_interval())
        t = threading.Thread(target=loop, name="trippy-inbound-imap", daemon=True)
        t.start()
        log.info("inbound: polling IMAP every %ss", _interval())
        return t
    from . import inbound_smtp
    return inbound_smtp.start(session_factory)
