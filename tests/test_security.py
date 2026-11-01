"""Security review fixes: SSRF guard, zip bombs, CORS/headers/body limit, login timing,
consent for linking accounts, one-time invite codes for claiming travelers, pdf temp path."""
import io
import socket
import zipfile
from datetime import datetime, timedelta

import pytest

from app import auth, models
from app.importers import ics, pkpass
from app.importers.common import ImportError_
from app.importers.vendor import receipts_engine
from tests.test_auth import add_and_redeem, bearer, signup


def _resolve_to(monkeypatch, table):
    def fake(host, port, *a, **k):
        return [(socket.AF_INET6 if ":" in table[host] else socket.AF_INET, socket.SOCK_STREAM, 6, "",
                 (table[host], port))]
    monkeypatch.setattr(ics.socket, "getaddrinfo", fake)


@pytest.mark.parametrize("ip", ["100.64.0.10", "100.100.100.100", "127.0.0.1", "192.168.1.20",
                                "169.254.169.254", "10.0.0.1", "::ffff:127.0.0.1", "::1"])
def test_ics_fetch_refuses_private_tailnet_and_loopback(monkeypatch, ip):
    _resolve_to(monkeypatch, {"cal.example.com": ip})
    with pytest.raises(ImportError_, match="private network"):
        ics.fetch_feed("https://cal.example.com/feed.ics")


def test_ics_redirect_to_private_address_is_rechecked(monkeypatch):
    _resolve_to(monkeypatch, {"cal.example.com": "93.184.216.34", "internal.example.com": "192.168.1.1"})
    hops = []

    class FakeResp:
        def __init__(self, status, loc=None, body=b""):
            self.status, self._loc, self._body = status, loc, body

        def getheader(self, name):
            return self._loc

        def read(self, n):
            return self._body

    class FakeConn:
        def __init__(self, host, pinned, port, timeout):
            self.host, self.pinned = host, pinned

        def request(self, method, path, headers):
            hops.append((self.host, self.pinned, path))

        def getresponse(self):
            return FakeResp(302, "http://internal.example.com/admin")

        def close(self):
            pass

    monkeypatch.setattr(ics, "_PinnedHTTPSConnection", FakeConn)
    monkeypatch.setattr(ics, "_PinnedHTTPConnection", FakeConn)
    with pytest.raises(ImportError_, match="private network"):
        ics.fetch_feed("webcal://cal.example.com/feed.ics")
    assert hops == [("cal.example.com", "93.184.216.34", "/feed.ics")]  # connected to the checked IP


def test_ics_errors_do_not_echo_internal_details(monkeypatch):
    _resolve_to(monkeypatch, {"cal.example.com": "93.184.216.34"})

    class Boom:
        def __init__(self, *a, **k):
            pass

        def request(self, *a, **k):
            raise ConnectionRefusedError("[Errno 111] secret-host:6379 refused")

        def close(self):
            pass

    monkeypatch.setattr(ics, "_PinnedHTTPSConnection", Boom)
    with pytest.raises(ImportError_) as e:
        ics.fetch_feed("https://cal.example.com/x.ics")
    assert "6379" not in str(e.value) and str(e.value) == "Couldn't download the calendar"


def test_pkpass_zip_bomb_is_rejected():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("pass.json", b"{" + b" " * (20 * 1024 * 1024) + b"}")
    assert len(buf.getvalue()) < 200_000
    with pytest.raises(ImportError_, match="too large"):
        pkpass.read_pass_json(buf.getvalue())


def test_cors_rejects_unknown_origins_and_security_headers_are_set(api):
    r = api.options("/trips/", headers={"Origin": "http://evil.example",
                                        "Access-Control-Request-Method": "GET",
                                        "Access-Control-Request-Headers": "authorization"})
    assert "access-control-allow-origin" not in r.headers
    h = api.get("/health").headers
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"
    assert h["referrer-policy"] == "no-referrer" and h["cache-control"] == "no-store"


def test_oversized_body_gets_413_before_auth(api):
    r = api.post("/auth/login", content=b"x" * (9 * 1024 * 1024), headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_login_runs_argon2_for_unknown_accounts(api, monkeypatch):
    calls = []
    real = auth.verify_password
    monkeypatch.setattr(auth, "verify_password", lambda h, p: calls.append(h) or real(h, p))
    assert api.post("/auth/login", json={"email": "nobody@example.com", "password": "whatever 1"}).status_code == 401
    assert len(calls) == 1


def test_adding_an_unrelated_account_by_email_does_not_link_or_reveal_it(api):
    ana, ben_t = bearer(signup(api)), signup(api, email="ben@example.com", name="Ben")
    trip = api.post("/trips/", json={"title": "Spam"}, headers=ana).json()
    r = api.post(f"/trips/{trip['id']}/travelers", json={"name": "Ben", "email": "ben@example.com"}, headers=ana)
    assert ben_t["user"]["id"] not in {p["id"] for p in r.json()["participants"]}
    assert api.get("/trips/", headers=bearer(ben_t)).json() == []


def _placeholder_trip(api, ana, email="cy@example.com"):
    trip = api.post("/trips/", json={"title": "Oaxaca"}, headers=ana).json()
    r = api.post(f"/trips/{trip['id']}/travelers", json={"name": "Cy", "email": email}, headers=ana).json()
    cy = next(p for p in r["participants"] if p["username"].startswith("Cy"))
    return trip, cy


def test_allowlisted_email_can_claim_a_placeholder_without_a_code(api, monkeypatch):
    ana = bearer(signup(api))
    _placeholder_trip(api, ana)
    monkeypatch.setenv("TRIPPY_SIGNUP_MODE", "invite")
    monkeypatch.setenv("TRIPPY_SIGNUP_ALLOWLIST", "cy@example.com")
    assert signup(api, email="cy@example.com", name="Cy")["claimed"]


def test_expired_code_and_closed_mode(api, db, monkeypatch):
    ana = bearer(signup(api))
    trip, cy = _placeholder_trip(api, ana)
    code = api.post(f"/trips/{trip['id']}/travelers/{cy['id']}/invite-code", headers=ana).json()["code"]
    body = {"email": "cy@example.com", "password": "long enough 1", "name": "Cy", "invite_code": code}
    monkeypatch.setenv("TRIPPY_SIGNUP_MODE", "closed")
    assert api.post("/auth/signup", json=body).status_code == 403
    monkeypatch.setenv("TRIPPY_SIGNUP_MODE", "invite")
    inv = db.query(models.TripInvite).one()
    inv.code_expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()
    assert api.post("/auth/signup", json=body).status_code == 403
    # A new code replaces the old one.
    code2 = api.post(f"/trips/{trip['id']}/travelers/{cy['id']}/invite-code", headers=ana).json()["code"]
    assert code2 != code
    assert api.post("/auth/signup", json={**body, "invite_code": code2}).status_code == 201


def test_invite_code_rules(api):
    ana_t = signup(api)
    ana, ben = bearer(ana_t), bearer(signup(api, email="ben@example.com", name="Ben"))
    trip, cy = _placeholder_trip(api, ana)
    # Not for real accounts, not for people off the trip, not for outsiders.
    assert api.post(f"/trips/{trip['id']}/travelers/{ana_t['user']['id']}/invite-code", headers=ana).status_code == 400
    other = api.post("/trips/", json={"title": "Other"}, headers=ana).json()
    assert api.post(f"/trips/{other['id']}/travelers/{cy['id']}/invite-code", headers=ana).status_code == 404
    assert api.post(f"/trips/{trip['id']}/travelers/{cy['id']}/invite-code", headers=ben).status_code == 404
    assert api.post("/invites/redeem", json={"code": "ABCDE-FGHJK"}, headers=ben).status_code == 404
    # The code itself is never stored.
    code = api.post(f"/trips/{trip['id']}/travelers/{cy['id']}/invite-code", headers=ana).json()["code"]
    invites = api.get(f"/trips/{trip['id']}/invites", headers=ana).json()
    assert code not in str(invites) and invites[0]["code_expires_at"]


def test_redeem_moves_expenses_and_refuses_overlaps(api):
    ana_t = signup(api)
    ana = bearer(ana_t)
    ben_t = signup(api, email="ben@example.com", name="Ben")
    ben = bearer(ben_t)
    trip, cy = _placeholder_trip(api, ana)
    r = api.post(f"/trips/{trip['id']}/expenses/split", headers=ana, json={
        "amount": 30, "description": "Taxi", "payer_id": cy["id"], "split_among": [ana_t["user"]["id"], cy["id"]]})
    assert r.status_code == 200, r.text
    code = api.post(f"/trips/{trip['id']}/travelers/{cy['id']}/invite-code", headers=ana).json()["code"]
    assert api.post("/invites/redeem", json={"code": code}, headers=ben).json()["joined"] == 1
    bal = api.get(f"/trips/{trip['id']}/balances", headers=ben)
    assert bal.status_code == 200 and str(ben_t["user"]["id"]) in bal.text
    # Two travelers on the same expense can't be folded into one account.
    trip2 = api.post("/trips/", json={"title": "Two"}, headers=ana).json()
    api.post(f"/trips/{trip2['id']}/participants/{ben_t['user']['id']}", headers=ana)
    r = api.post(f"/trips/{trip2['id']}/travelers", json={"name": "Dee"}, headers=ana).json()
    dee = next(p for p in r["participants"] if p["username"].startswith("Dee"))
    api.post(f"/trips/{trip2['id']}/expenses/split", headers=ana, json={
        "amount": 10, "description": "Tea", "payer_id": ana_t["user"]["id"],
        "split_among": [ben_t["user"]["id"], dee["id"]]})
    code = api.post(f"/trips/{trip2['id']}/travelers/{dee['id']}/invite-code", headers=ana).json()["code"]
    assert api.post("/invites/redeem", json={"code": code}, headers=ben).status_code == 409


def test_pdf_receipts_never_use_the_client_filename_as_a_path(monkeypatch):
    seen = []
    monkeypatch.setattr(receipts_engine, "pdf_to_text", lambda path: seen.append(path) or "")
    receipts_engine.extract_candidates(b"%PDF-1.4", filename="/etc/passwd.pdf")
    assert seen and seen[0] != "/etc/passwd.pdf" and seen[0].endswith(".pdf")


def test_stats_do_not_leak_across_users(api):
    ana = bearer(signup(api, email="ana-stats@example.com", name="Ana"))
    ben = bearer(signup(api, email="ben-stats@example.com", name="Ben"))

    trip = api.post("/trips/", json={
        "title": "Ana Secret Trip",
        "start_date": "2026-05-01T00:00:00",
        "end_date": "2026-05-05T00:00:00",
    }, headers=ana).json()
    api.post(f"/trips/{trip['id']}/flights/", json={
        "airline": "United Airlines",
        "flight_number": "UA 100",
        "departure_airport": "SFO",
        "arrival_airport": "NRT",
        "departure_time": "2026-05-01T10:00:00",
        "arrival_time": "2026-05-02T14:00:00",
        "aircraft_model": "Boeing 777-300ER",
    }, headers=ana)
    api.post("/rental_cars/", json={
        "rental_company": "Hertz",
        "car_model": "Porsche 911",
        "vehicle_class": "Luxury",
        "pickup_location": "NRT",
        "dropoff_location": "NRT",
        "pickup_time": "2026-05-02T15:00:00",
        "dropoff_time": "2026-05-05T10:00:00",
        "trip_id": trip["id"],
    }, headers=ana)

    ben_stats = api.get("/stats/", headers=ben).json()
    assert ben_stats["total_trips"] == 0
    assert ben_stats["top_airlines"] == []
    assert ben_stats["top_aircraft"] == []
    assert ben_stats["top_cars"] == []
    assert ben_stats["top_rental_companies"] == []
    assert ben_stats["flights"]["top_airlines"] == []
    assert ben_stats["flights"]["top_aircraft"] == []
    assert ben_stats["rentals"]["top_cars"] == []
    assert ben_stats["rentals"]["top_rental_companies"] == []
    assert ben_stats["rentals"]["top_vehicle_classes"] == []

    ben_2026 = api.get("/stats/?year=2026", headers=ben).json()
    assert ben_2026["total_trips"] == 0

    ana_stats = api.get("/stats/", headers=ana).json()
    assert ana_stats["total_trips"] == 1
    assert ana_stats["top_airlines"] == [{"name": "United Airlines", "count": 1}]
    assert ana_stats["top_aircraft"] == [{"name": "Boeing 777-300ER", "count": 1}]
    assert ana_stats["top_cars"] == [{"name": "Porsche 911", "count": 1}]
    assert ana_stats["top_rental_companies"] == [{"name": "Hertz", "count": 1}]
    assert ana_stats["rentals"]["top_vehicle_classes"] == [{"name": "Luxury", "count": 1}]


def test_external_id_is_unique_per_owner_not_globally(api, db):
    from sqlalchemy.exc import IntegrityError

    ana_t = signup(api, email="ana-ext@example.com", name="Ana")
    ben_t = signup(api, email="ben-ext@example.com", name="Ben")
    ana, ben = bearer(ana_t), bearer(ben_t)

    rental_payload = {
        "rental_company": "Hertz",
        "pickup_location": "SFO",
        "dropoff_location": "SFO",
        "pickup_time": "2026-06-01T10:00:00",
        "dropoff_time": "2026-06-03T10:00:00",
    }
    r1 = api.put("/rental_cars/external/shared-ext-1", json=rental_payload, headers=ana)
    r2 = api.put("/rental_cars/external/shared-ext-1", json=rental_payload, headers=ben)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["id"] != r2.json()["id"]

    # Direct duplicate (owner_id, external_id) on Flight, RentalCar, and Lodging is rejected
    db.add(models.RentalCar(
        owner_id=ana_t["user"]["id"],
        external_id="shared-ext-1",
        rental_company="Avis",
        pickup_location="LAX",
        dropoff_location="LAX",
        pickup_time=datetime(2026, 6, 1, 10, 0),
        dropoff_time=datetime(2026, 6, 2, 10, 0),
    ))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_shared_trip_participant_cannot_edit_or_delete_others_bookings_or_group_links(api):
    ana_t = signup(api, email="ana-m1@example.com", name="Ana")
    ben_t = signup(api, email="ben-m1@example.com", name="Ben")
    cal_t = signup(api, email="cal-m1@example.com", name="Cal")
    ana, ben, cal = bearer(ana_t), bearer(ben_t), bearer(cal_t)

    trip, cy = _placeholder_trip(api, ana, email="ben-m1-invite@example.com")
    code = api.post(f"/trips/{trip['id']}/travelers/{cy['id']}/invite-code", headers=ana).json()["code"]
    assert api.post("/invites/redeem", json={"code": code}, headers=ben).status_code == 200

    rental = api.post("/rental_cars/", json={
        "rental_company": "Sixt",
        "pickup_location": "ZRH",
        "dropoff_location": "ZRH",
        "pickup_time": "2026-07-01T10:00:00",
        "dropoff_time": "2026-07-05T10:00:00",
        "trip_id": trip["id"],
    }, headers=ana).json()
    stay = api.post(f"/trips/{trip['id']}/lodgings/", json={
        "name": "Hotel Baur au Lac",
        "check_in": "2026-07-01T15:00:00",
        "check_out": "2026-07-05T11:00:00",
    }, headers=ana).json()

    # Ben (participant, not owner) can read them, but cannot PATCH or DELETE Ana's rental or stay
    assert api.get(f"/rental_cars/{rental['id']}", headers=ben).status_code == 200
    assert api.patch(f"/rental_cars/{rental['id']}", json={"notes": "hijacked"}, headers=ben).status_code == 403
    assert api.delete(f"/rental_cars/{rental['id']}", headers=ben).status_code == 403
    assert api.get(f"/lodgings/{stay['id']}", headers=ben).status_code == 200
    assert api.patch(f"/lodgings/{stay['id']}", json={"notes": "hijacked"}, headers=ben).status_code == 403
    assert api.delete(f"/lodgings/{stay['id']}", headers=ben).status_code == 403

    # Ben CAN create, edit, and delete his own stay on the shared trip, and Ana (trip owner) can also edit it
    ben_stay = api.post(f"/trips/{trip['id']}/lodgings/", json={
        "name": "Ben Hostel",
        "check_in": "2026-07-01T15:00:00",
        "check_out": "2026-07-02T11:00:00",
    }, headers=ben).json()
    assert api.patch(f"/lodgings/{ben_stay['id']}", json={"notes": "ben note"}, headers=ben).status_code == 200
    assert api.patch(f"/lodgings/{ben_stay['id']}", json={"notes": "ana note"}, headers=ana).status_code == 200
    assert api.delete(f"/lodgings/{ben_stay['id']}", headers=ben).status_code == 204

    # Ben cannot link or unlink Ana's trip to/from a group
    assert api.post(f"/trips/{trip['id']}/group", json={"name": "Ben Group"}, headers=ben).status_code == 403
    grp = api.post(f"/trips/{trip['id']}/group", json={"name": "Ana Group"}, headers=ana)
    assert grp.status_code == 200
    assert api.put(f"/trips/{trip['id']}/group", json={"group_id": None}, headers=ben).status_code == 403
    assert api.put(f"/trips/{trip['id']}/group", json={"group_id": None}, headers=ana).status_code == 200

    # Journey ownership is required on GET /drives?journey_id=
    t2 = api.post("/trips/", json={"title": "Alps Part 2"}, headers=ana).json()
    journey = api.post("/journeys", json={"title": "Grand Alps", "trip_ids": [trip["id"], t2["id"]]}, headers=ana).json()
    assert api.get(f"/drives?journey_id={journey['id']}", headers=ana).status_code == 200
    assert api.get(f"/drives?journey_id={journey['id']}", headers=ben).status_code == 403
    assert api.get(f"/drives?journey_id={journey['id']}", headers=cal).status_code == 404


def test_importer_caps_items_email_text_and_pdf_text(api):
    from app.importers import airline_templates, service
    from app import inbound

    h = bearer(signup(api, email="ana-m5@example.com"))
    # 1. Generic CSV with > MAX_ITEMS rows is rejected cleanly with 400
    header = "airline,flight_number,from,to,dep\n"
    rows = header + ("UA,UA 1,SFO,LAX,2026-05-01T10:00\n" * (service.MAX_ITEMS + 5))
    r = api.post("/import/preview", json={
        "source": "csv",
        "csv_kind": "flight",
        "text": rows,
        "mapping": {
            "airline": "airline",
            "flight_number": "flight_number",
            "departure_airport": "from",
            "arrival_airport": "to",
            "departure_time": "dep",
        },
    }, headers=h)
    assert r.status_code == 400 and str(service.MAX_ITEMS) in r.json()["detail"]

    # 2. normalize() truncates huge email bodies to MAX_EMAIL_TEXT
    huge = "A" * (airline_templates.MAX_EMAIL_TEXT + 50_000)
    assert len(airline_templates.normalize(huge)) <= airline_templates.MAX_EMAIL_TEXT
    assert len(inbound._pdf_text(b"not-a-valid-pdf")) == 0




