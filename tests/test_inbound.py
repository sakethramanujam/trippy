"""Email-in with synthetic emails: routing, importing, trips, dedupe, the inbox log, IMAP and SMTP."""
import asyncio
import io
import json
import zipfile
from email.message import EmailMessage
from pathlib import Path

import pytest

from app import inbound, models
from app.inbound_smtp import Handler

FIX = Path(__file__).parent / "fixtures" / "import"
FLIGHT = (FIX / "flight_email_synthetic.txt").read_text().split("\n", 2)[2]
HOTEL_SUBJECT = (FIX / "hotel_email_synthetic.txt").read_text().split("\n", 1)[0].removeprefix("Subject: ")
HOTEL = (FIX / "hotel_email_synthetic.txt").read_text().split("\n", 2)[2]
AUTH_PASS = "mx.example.net; spf=pass smtp.mailfrom=t.local; dkim=pass header.d=t.local; dmarc=pass header.from=t.local"


@pytest.fixture()
def on(monkeypatch):
    for k, v in {"MODE": "imap", "IMAP_HOST": "imap.example.net", "IMAP_USERNAME": "trips@example.net",
                 "ADDRESS_TEMPLATE": "trips+{token}@example.net"}.items():
        monkeypatch.setenv(f"TRIPPY_INBOUND_{k}", v)
    inbound.STATUS.update(last_poll=None, last_error=None)
    yield


@pytest.fixture()
def users(db):
    ana = models.User(username="ana", email="ana@t.local", hashed_password="x", home_airport="SFO")
    ben = models.User(username="ben", email="ben@t.local", hashed_password="x")
    ghost = models.User(username="g", email="ghost@t.local", is_placeholder=True)
    db.add_all([ana, ben, ghost])
    db.commit()
    return ana, ben, ghost


def mail(body=FLIGHT, to="someone@example.net", sender="stranger@else.where", subject="Your trip", mid=None,
         auth=None, attach=(), html=None):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = sender, to, subject
    if mid:
        m["Message-ID"] = mid
    if auth:
        m["Authentication-Results"] = auth
    m.set_content(body)
    if html:
        m.add_alternative(html, subtype="html")
    for name, ctype, data in attach:
        main, sub = ctype.split("/")
        m.add_attachment(data, maintype=main, subtype=sub, filename=name)
    return m.as_bytes()


def make_pdf(lines):
    """A tiny one-page PDF with these lines of text (enough for pypdf to read back)."""
    text = "BT /F1 11 Tf 50 750 Td 14 TL " + " ".join(f"({l.replace('(', '').replace(')', '')}) '" for l in lines) + " ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(text)} >>\nstream\n{text}\nendstream", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


class Keep:
    """A session factory that hands out the test session and ignores close()."""
    def __init__(self, db):
        self.db = db

    def __call__(self):
        return self

    def __getattr__(self, name):
        return getattr(self.db, name)

    def close(self):
        pass


def addr(db, user):
    return inbound.address_for(db, user)


# --- settings and addresses ------------------------------------------------------

def test_off_by_default_and_health(client, db, users, monkeypatch):
    for k in ("MODE", "IMAP_HOST", "ADDRESS_TEMPLATE"):
        monkeypatch.delenv(f"TRIPPY_INBOUND_{k}", raising=False)
    h = client.get("/health").json()["inbound"]
    assert h == {"enabled": False, "mode": "off", "addresses": "sender-only", "last_poll": None, "ok": None}
    s = client.get("/inbound/settings").json()
    assert s["enabled"] is False and s["address"] is None and "admin" in s["message"]
    assert client.post("/inbound/address/regenerate").status_code == 400
    assert inbound.start(Keep(db)) is None  # nothing starts


def test_address_and_regenerate(client, db, users, on):
    s = client.get("/inbound/settings").json()
    assert s["enabled"] and s["mode"] == "imap"
    a1 = s["address"]
    assert a1.startswith("trips+") and a1.endswith("@example.net")
    assert client.get("/inbound/settings").json()["address"] == a1  # stable
    a2 = client.post("/inbound/address/regenerate").json()["address"]
    assert a2 != a1
    assert inbound.token_from(a2) == users[0].inbound_token
    assert client.get("/health").json()["inbound"]["addresses"] == "per-user"


def test_catch_all_template(db, users, monkeypatch, on):
    monkeypatch.setenv("TRIPPY_INBOUND_ADDRESS_TEMPLATE", "{token}@trips.example.com")
    a = addr(db, users[0])
    assert a.endswith("@trips.example.com") and inbound.token_from(a.upper()) == users[0].inbound_token
    assert inbound.accepts_recipient("anything@trips.example.com") and not inbound.accepts_recipient("x@gmail.com")


# --- routing -----------------------------------------------------------------------

def test_token_routing_imports_and_makes_a_trip(client, db, users, on):
    ana = users[0]
    row = inbound.receive(db, mail(to=f"Ana <{addr(db, ana)}>", mid="<f1@x>"))
    assert row.user_id == ana.id and row.routed_by == "token" and row.status == "imported"
    out = inbound.summary(row)
    (c,) = out["created"]
    fl = db.get(models.Flight, c["id"])
    assert fl.flight_number == "TP 236" and fl.owner_id == ana.id
    trip = db.get(models.Trip, fl.trip_id)
    assert out["new_trip_ids"] == [trip.id] and trip.title == "Lisbon (email)"
    # Same Message-ID again: nothing new.
    again = inbound.receive(db, mail(to=addr(db, ana), mid="<f1@x>"))
    assert again.id == row.id and db.query(models.Flight).count() == 1
    # Same booking in a different email: logged as a duplicate.
    dup = inbound.receive(db, mail(to=addr(db, ana), mid="<f2@x>"))
    assert dup.status == "duplicate" and db.query(models.Flight).count() == 1
    # The hotel next day lands on the trip the flight made.
    h = inbound.receive(db, mail(body=HOTEL, subject=HOTEL_SUBJECT, to=addr(db, ana), mid="<h1@x>"))
    assert h.status == "imported"
    stay = db.query(models.Lodging).one()
    assert stay.trip_id == trip.id
    db.refresh(trip)
    assert trip.end_date.date().isoformat() == "2026-05-07"  # widened


def test_attaches_to_an_existing_trip_by_date_and_place(db, users, on):
    from datetime import datetime
    ana = users[0]
    paris = models.Trip(title="Paris", owner_id=ana.id, start_date=datetime(2026, 5, 1), end_date=datetime(2026, 5, 10))
    lisbon = models.Trip(title="Lisbon", owner_id=ana.id, start_date=datetime(2026, 5, 2), end_date=datetime(2026, 5, 8))
    db.add_all([paris, lisbon])
    db.flush()
    db.add(models.Lodging(trip_id=lisbon.id, owner_id=ana.id, name="Other", city="Lisbon",
                          check_in=datetime(2026, 5, 2), check_out=datetime(2026, 5, 3)))
    db.commit()
    inbound.receive(db, mail(to=addr(db, ana), mid="<a@x>"))
    assert db.query(models.Flight).one().trip_id == lisbon.id


def test_sender_fallback_needs_auth_and_a_real_account(db, users, on, monkeypatch):
    ana, ben, ghost = users
    assert inbound.receive(db, mail(sender="ben@t.local", mid="<s0@x>")) is None  # no Authentication-Results
    row = inbound.receive(db, mail(sender="Ben <BEN@t.local>", mid="<s1@x>", auth=AUTH_PASS))
    assert row.user_id == ben.id and row.routed_by == "sender"
    bad = AUTH_PASS.replace("dmarc=pass", "dmarc=fail")
    assert inbound.receive(db, mail(sender="ana@t.local", mid="<s2@x>", auth=bad)) is None
    assert inbound.receive(db, mail(sender="ghost@t.local", mid="<s3@x>", auth=AUTH_PASS)) is None  # placeholder
    assert inbound.receive(db, mail(sender="nobody@t.local", mid="<s4@x>", auth=AUTH_PASS)) is None
    monkeypatch.setenv("TRIPPY_INBOUND_REQUIRE_AUTH", "off")
    assert inbound.receive(db, mail(sender="ana@t.local", mid="<s5@x>")).user_id == ana.id
    monkeypatch.setenv("TRIPPY_INBOUND_SENDER_MATCH", "off")
    assert inbound.receive(db, mail(sender="ana@t.local", mid="<s6@x>")) is None
    assert db.query(models.InboundEmail).count() == 2  # ignored mail leaves no trace


def test_unknown_token_and_strangers_are_ignored(db, users, on):
    assert inbound.receive(db, mail(to="trips+zzzzzzzzzzzz@example.net", mid="<u1@x>")) is None
    assert inbound.receive(db, mail(to="trips@example.net", mid="<u2@x>")) is None
    assert db.query(models.InboundEmail).count() == 0


def test_auth_results_forgery_and_substring_domain_rejected(db, users, on, monkeypatch):
    ana, ben, _ = users
    # 1. Substring domain attack: sender is user@t.local, but spf=pass is for nott.local -> must be rejected
    spoof_sub = "mx.example.net; spf=pass smtp.mailfrom=evil@nott.local"
    assert inbound.receive(db, mail(sender="ben@t.local", mid="<f-sub@x>", auth=spoof_sub)) is None

    # 2. Forged bottom Authentication-Results header when topmost MX header says spf=fail / none
    raw_two_headers = (
        b"Authentication-Results: mx.example.net; spf=fail smtp.mailfrom=t.local\r\n"
        b"Authentication-Results: attacker.evil; dmarc=pass header.from=t.local\r\n"
        + mail(sender="ben@t.local", mid="<f-two@x>")
    )
    assert inbound.receive(db, raw_two_headers) is None

    # 3. dmarc=pass for a different header.from domain must not authenticate ben@t.local
    wrong_dmarc = "mx.example.net; dmarc=pass header.from=other.org"
    assert inbound.receive(db, mail(sender="ben@t.local", mid="<f-dmarc@x>", auth=wrong_dmarc)) is None

    # 4. In direct SMTP mode, sender-match is disabled by default even if attacker supplies Authentication-Results
    monkeypatch.setenv("TRIPPY_INBOUND_MODE", "smtp")
    assert inbound.receive(db, mail(sender="ben@t.local", mid="<f-smtp@x>", auth=AUTH_PASS)) is None


def test_delivered_to_header_routes(db, users, on):
    raw = mail(to="list@example.org", mid="<d1@x>")
    raw = f"Delivered-To: {addr(db, users[1])}\r\n".encode() + raw
    assert inbound.receive(db, raw).user_id == users[1].id


# --- attachments and limits -------------------------------------------------------------

def make_pkpass():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("pass.json", json.dumps({
            "formatVersion": 1, "passTypeIdentifier": "pass.test", "serialNumber": "SN1",
            "organizationName": "Air Canada", "relevantDate": "2026-11-22T15:30-05:00",
            "boardingPass": {"transitType": "PKTransitTypeAir"},
            "barcode": {"message": "M1DESMARAIS/LUC       EABC123 YULFRAAC 0834 326J001A0025 100",
                        "format": "PKBarcodeFormatPDF417"}}))
        z.writestr("manifest.json", "{}")
    return buf.getvalue()


def test_ics_pkpass_pdf_attachments_and_ignored_types(db, users, on):
    pdf = make_pdf([HOTEL_SUBJECT] + HOTEL.splitlines())
    raw = mail(body="Fwd: see attached", to=addr(db, users[0]), mid="<att@x>", attach=[
        ("trip.ics", "text/calendar", (FIX / "synthetic_calendar.ics").read_bytes()),
        ("boarding.pkpass", "application/vnd.apple.pkpass", make_pkpass()),
        ("folio.pdf", "application/pdf", pdf),
        ("evil.exe", "application/octet-stream", b"MZ" + b"\0" * 100),
        ("page.svg", "image/svg+xml", b"<svg onload=alert(1)>"),
    ])
    row = inbound.receive(db, raw)
    out = inbound.summary(row)
    parts = {p["part"]: p["found"] for p in out["parts"]}
    assert parts["trip.ics"] == 4 and parts["boarding.pkpass"] == 1 and parts["folio.pdf"] == 1
    assert "evil.exe" not in parts and "page.svg" not in parts
    assert row.status == "imported"
    assert db.query(models.Lodging).filter(models.Lodging.name == "Hotel Alfama Test").count() == 1
    assert db.query(models.Flight).filter(models.Flight.departure_airport == "YUL").count() == 1
    # Tokyo (April), LAX car, Seattle (May 1) and YUL (Nov) are far apart: separate new trips.
    assert len(out["new_trip_ids"]) >= 3


def test_html_only_email_is_read_as_text(db, users, on):
    html = "<html><script>alert(1)</script><body><p>" + FLIGHT.replace("\n", "<br>") + "</p></body></html>"
    m = EmailMessage()
    m["From"], m["To"], m["Message-ID"] = "x@y.z", addr(db, users[0]), "<html@x>"
    m.set_content(html, subtype="html")
    row = inbound.receive(db, m.as_bytes())
    assert row.status == "imported" and db.query(models.Flight).one().flight_number == "TP 236"


def test_size_and_rate_limits(db, users, on, monkeypatch):
    monkeypatch.setenv("TRIPPY_INBOUND_MAX_BYTES", str(100 * 1024))
    big = mail(body="x" * 200_000, to=addr(db, users[0]), mid="<big@x>")
    assert inbound.receive(db, big) is None
    monkeypatch.setenv("TRIPPY_INBOUND_MAX_PER_HOUR", "2")
    a = addr(db, users[0])
    rows = [inbound.receive(db, mail(body="hello", to=a, mid=f"<r{i}@x>")) for i in range(3)]
    assert [r.status for r in rows] == ["nothing_found", "nothing_found", "failed"]
    assert "Too many" in rows[2].error and rows[2].raw is not None  # can be retried later


# --- the inbox log API ---------------------------------------------------------------------

def test_log_badge_retry_delete_and_privacy(client, db, users, on):
    ana, ben, _ = users
    good = inbound.receive(db, mail(to=addr(db, ana), mid="<l1@x>"))
    nothing = inbound.receive(db, mail(body="Lunch Friday?", to=addr(db, ana), mid="<l2@x>"))
    client.acting_as = ana.id
    assert client.get("/inbound/emails/unread").json() == {"unread": 2, "failed": 0, "enabled": True}
    lst = client.get("/inbound/emails").json()
    assert [e["id"] for e in lst] == [nothing.id, good.id]
    assert lst[1]["created"][0]["kind"] == "flight" and "raw" not in lst[1]
    assert client.post("/inbound/emails/seen").json() == {"marked": 2}
    assert client.get("/inbound/emails/unread").json()["unread"] == 0
    # Retry re-reads the stored message (e.g. after fixing a parser): still nothing here.
    r = client.post(f"/inbound/emails/{nothing.id}/retry").json()
    assert r["status"] == "nothing_found" and r["attempts"] == 2
    # Retry on an imported one reports duplicates instead of importing twice.
    assert client.post(f"/inbound/emails/{good.id}/retry").json()["status"] == "duplicate"
    assert db.query(models.Flight).count() == 1
    # Ben can't see or touch Ana's mail.
    client.acting_as = ben.id
    assert client.get("/inbound/emails").json() == []
    assert client.get(f"/inbound/emails/{good.id}").status_code == 404
    assert client.post(f"/inbound/emails/{good.id}/retry").status_code == 404
    assert client.delete(f"/inbound/emails/{good.id}").status_code == 404
    client.acting_as = ana.id
    assert client.delete(f"/inbound/emails/{good.id}").status_code == 204
    assert db.query(models.Flight).count() == 1  # the booking stays
    # Raw messages are dropped after the keep window; the row stays but can't be retried.
    from datetime import datetime, timedelta
    nothing.received_at = datetime.utcnow() - timedelta(days=inbound.RAW_KEEP_DAYS + 1)
    db.commit()
    inbound.prune(db)
    assert client.get(f"/inbound/emails/{nothing.id}").json()["can_retry"] is False
    assert client.post(f"/inbound/emails/{nothing.id}/retry").status_code == 400


def test_failed_processing_is_logged(db, users, on, monkeypatch):
    monkeypatch.setattr(inbound, "file_items", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    row = inbound.receive(db, mail(to=addr(db, users[0]), mid="<boom@x>"))
    assert row.status == "failed" and row.error == "boom"


# --- IMAP ------------------------------------------------------------------------------------

class FakeIMAP:
    def __init__(self, messages, caps=("IMAP4REV1", "MOVE")):
        self.messages = dict(messages)  # uid -> raw
        self.capabilities = caps
        self.flags = {u: set() for u in self.messages}
        self.folders = {"INBOX"}
        self.moved = []
        self.logged_out = False

    def create(self, name):
        self.folders.add(name.strip('"'))
        return "OK", [b""]

    def select(self, name):
        return ("OK", [b"1"]) if name.strip('"') in self.folders else ("NO", [b""])

    def uid(self, cmd, *args):
        if cmd == "SEARCH":
            return "OK", [b" ".join(u for u in self.messages if "\\Seen" not in self.flags[u])]
        uid = args[0]
        if cmd == "FETCH":
            return "OK", [(b"1 (BODY[] {n}", self.messages[uid]), b")"]
        if cmd == "STORE":
            self.flags[uid].add(args[2].strip("()"))
            return "OK", []
        if cmd in ("MOVE", "COPY"):
            self.moved.append((cmd, uid, args[1].strip('"')))
            return "OK", []
        raise AssertionError(cmd)

    def expunge(self):
        return "OK", []

    def logout(self):
        self.logged_out = True


def test_imap_poll_files_marks_seen_and_moves(db, users, on):
    a = addr(db, users[0])
    fake = FakeIMAP({b"1": mail(to=a, mid="<i1@x>"), b"2": mail(to="nobody@else", mid="<i2@x>"),
                     b"3": mail(to=a, mid="<i1@x>")})  # 3 is a re-delivery of 1
    assert inbound.poll_once(Keep(db), connect=lambda: fake) == 3
    assert all("\\Seen" in f for f in fake.flags.values())
    assert [m[2] for m in fake.moved] == ["Trippy-Processed"] * 3 and fake.logged_out
    assert db.query(models.InboundEmail).count() == 1 and db.query(models.Flight).count() == 1
    st = inbound.status()
    assert st["last_poll"] and st["ok"] is True and st["mode"] == "imap"
    # Next poll: nothing unread.
    assert inbound.poll_once(Keep(db), connect=lambda: fake) == 0


def test_imap_without_move_copies_and_deletes(db, users, on, monkeypatch):
    fake = FakeIMAP({b"9": mail(to=addr(db, users[0]), mid="<c@x>")}, caps=("IMAP4REV1",))
    inbound.poll_once(Keep(db), connect=lambda: fake)
    assert fake.moved == [("COPY", b"9", "Trippy-Processed")] and "\\Deleted" in fake.flags[b"9"]
    monkeypatch.setenv("TRIPPY_INBOUND_IMAP_PROCESSED_FOLDER", "")
    fake2 = FakeIMAP({b"1": mail(to=addr(db, users[0]), mid="<c2@x>")})
    inbound.poll_once(Keep(db), connect=lambda: fake2)
    assert fake2.moved == [] and "\\Seen" in fake2.flags[b"1"]


def test_imap_errors_show_in_status_without_details(db, users, on):
    def boom():
        raise OSError("connection refused to imap.example.net:993")
    assert inbound.poll_once(Keep(db), connect=boom) == 0
    st = inbound.status()
    assert st["ok"] is False and "imap.example.net" not in json.dumps(st)


# --- SMTP ------------------------------------------------------------------------------------

class Env:
    def __init__(self, raw):
        self.rcpt_tos, self.original_content, self.content = [], raw, raw


def test_smtp_handler_accepts_only_our_addresses(db, users, on, monkeypatch):
    monkeypatch.setenv("TRIPPY_INBOUND_MODE", "smtp")
    a = addr(db, users[0])
    h = Handler(Keep(db))
    env = Env(mail(to=a, mid="<smtp@x>"))
    run = asyncio.run
    assert run(h.handle_RCPT(None, None, env, "victim@gmail.com", [])).startswith("550")
    assert run(h.handle_RCPT(None, None, env, a, [])) == "250 OK"
    assert run(h.handle_DATA(None, None, env)) == "250 OK"
    assert db.query(models.InboundEmail).one().routed_by == "token"
    monkeypatch.setenv("TRIPPY_INBOUND_MAX_BYTES", str(64 * 1024))
    assert run(h.handle_DATA(None, None, Env(b"x" * 70_000))).startswith("552")


def test_smtp_receiver_end_to_end(db, users, on, monkeypatch):
    """Real aiosmtpd on a local port; smtplib delivers one message."""
    import smtplib
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    monkeypatch.setenv("TRIPPY_INBOUND_MODE", "smtp")
    monkeypatch.setenv("TRIPPY_INBOUND_SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("TRIPPY_INBOUND_SMTP_PORT", str(port))
    from app import inbound_smtp
    ctl = inbound_smtp.start(Keep(db))
    try:
        a = addr(db, users[0])
        with smtplib.SMTP("127.0.0.1", port, timeout=10) as c:
            c.sendmail("x@y.z", [a], mail(to=a, mid="<e2e@x>"))
            with pytest.raises(smtplib.SMTPRecipientsRefused):
                c.sendmail("x@y.z", ["someone@gmail.com"], b"Subject: hi\r\n\r\nhi")
    finally:
        ctl.stop()
    assert db.query(models.Flight).one().flight_number == "TP 236"
