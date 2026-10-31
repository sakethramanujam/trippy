"""Accounts: signup/login/refresh/logout/reset/delete, rate limits, per-user isolation, invites."""
import logging
import re

import pytest

from app import auth, models


def signup(api, email="ana@example.com", password="correct horse 1", name="Ana Lima", **extra):
    r = api.post("/auth/signup", json={"email": email, "password": password, "name": name, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def bearer(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def add_and_redeem(api, inviter, trip_id, name, email, joiner):
    """Add a traveler by email, then have the existing account `joiner` claim them with the code."""
    r = api.post(f"/trips/{trip_id}/travelers", json={"name": name, "email": email}, headers=inviter)
    assert r.status_code == 200, r.text
    me = api.get("/me", headers=joiner).json()["id"]
    assert me not in {p["id"] for p in r.json()["participants"]}  # never linked without consent
    pid = next(p["id"] for p in r.json()["participants"] if p["username"].lower().startswith(name.lower()))
    code = api.post(f"/trips/{trip_id}/travelers/{pid}/invite-code", headers=inviter).json()["code"]
    out = api.post("/invites/redeem", json={"code": code}, headers=joiner)
    assert out.status_code == 200, out.text
    return out.json()


def test_signup_login_me_and_password_is_hashed(api, db):
    out = signup(api, email="Ana@Example.com ", home_airport="sfo")
    assert out["user"]["email"] == "ana@example.com"
    assert out["user"]["initials"] == "AL" and out["user"]["home_airport"] == "SFO"
    stored = db.query(models.User).filter_by(email="ana@example.com").one().hashed_password
    assert stored.startswith("$argon2") and "correct horse" not in stored
    assert api.get("/me").status_code == 401
    assert api.get("/me", headers=bearer(out)).json()["name"] == "Ana Lima"
    assert api.post("/auth/login", json={"email": "ANA@example.com", "password": "correct horse 1"}).status_code == 200
    bad = api.post("/auth/login", json={"email": "ana@example.com", "password": "nope nope"})
    assert bad.status_code == 401
    missing = api.post("/auth/login", json={"email": "who@example.com", "password": "nope nope"})
    assert missing.json()["detail"] == bad.json()["detail"]  # doesn't reveal which emails exist


def test_signup_validation(api):
    signup(api)
    assert api.post("/auth/signup", json={"email": "ana@example.com", "password": "another pw 2", "name": "A"}).status_code == 409
    assert api.post("/auth/signup", json={"email": "x@example.com", "password": "short", "name": "X"}).status_code == 400
    assert api.post("/auth/signup", json={"email": "not-an-email", "password": "long enough", "name": "X"}).status_code == 400
    assert api.post("/auth/signup", json={"email": "x@example.com", "password": "long enough", "name": "X",
                                          "home_airport": "SF0X"}).status_code == 400


def test_refresh_and_logout_revoke_tokens(api):
    out = signup(api)
    assert api.post("/auth/refresh", json={"refresh_token": out["access_token"]}).status_code == 401  # wrong type
    new = api.post("/auth/refresh", json={"refresh_token": out["refresh_token"]})
    assert new.status_code == 200
    assert api.post("/auth/logout", headers=bearer(new.json())).status_code == 204
    assert api.get("/me", headers=bearer(new.json())).status_code == 401
    assert api.post("/auth/refresh", json={"refresh_token": out["refresh_token"]}).status_code == 401
    assert api.get("/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_forgot_and_reset_password(api, caplog, monkeypatch):
    out = signup(api)
    with caplog.at_level(logging.WARNING, logger="trippy.auth"):
        r = api.post("/auth/forgot", json={"email": "ana@example.com"})
    assert r.status_code == 200 and "dev_reset_token" not in r.json()
    code = next(m.group(0) for rec in caplog.records
                if (m := re.search(r"[0-9A-F]{6}-[0-9A-F]{6}-[0-9A-F]{6}", rec.getMessage())))
    # Unknown emails get the same answer.
    assert api.post("/auth/forgot", json={"email": "nobody@example.com"}).json() == r.json()
    assert api.post("/auth/reset", json={"token": "AAAAAA-BBBBBB-CCCCCC", "password": "brand new pw"}).status_code == 400
    done = api.post("/auth/reset", json={"token": code, "password": "brand new pw"})
    assert done.status_code == 200, done.text
    assert api.get("/me", headers=bearer(out)).status_code == 401  # old sessions end
    assert api.post("/auth/reset", json={"token": code, "password": "again again"}).status_code == 400  # single use
    assert api.post("/auth/login", json={"email": "ana@example.com", "password": "brand new pw"}).status_code == 200
    monkeypatch.setenv("TRIPPY_DEV_MODE", "1")
    assert "dev_reset_token" in api.post("/auth/forgot", json={"email": "ana@example.com"}).json()


def test_login_rate_limit(api):
    signup(api)
    codes = [api.post("/auth/login", json={"email": "ana@example.com", "password": "wrong pw!"}).status_code
             for _ in range(11)]
    assert codes[:10] == [401] * 10 and codes[10] == 429


def test_profile_update_and_change_password(api):
    out = signup(api)
    h = bearer(out)
    r = api.patch("/me", json={"name": "Ana Maria Lima", "home_airport": "lax"}, headers=h)
    assert r.json()["home_airport"] == "LAX" and r.json()["initials"] == "AL"
    assert api.post("/me/password", json={"current_password": "wrong one", "new_password": "next pw 123"},
                    headers=h).status_code == 400
    fresh = api.post("/me/password", json={"current_password": "correct horse 1", "new_password": "next pw 123"},
                     headers=h)
    assert fresh.status_code == 200
    assert api.get("/me", headers=h).status_code == 401
    assert api.get("/me", headers=bearer(fresh.json())).status_code == 200


def test_users_cannot_see_each_others_trips_or_money(api):
    ana, ben = bearer(signup(api)), bearer(signup(api, email="ben@example.com", name="Ben"))
    trip = api.post("/trips/", json={"title": "Lisbon"}, headers=ana).json()
    api.post(f"/trips/{trip['id']}/flights/", headers=ana, json={
        "airline": "TAP", "flight_number": "TP 236", "departure_airport": "SFO", "arrival_airport": "LIS",
        "departure_time": "2026-05-01T18:00", "arrival_time": "2026-05-02T13:00"})
    group = api.post("/groups", json={"name": "Ana only"}, headers=ana).json()
    assert [t["title"] for t in api.get("/trips/", headers=ana).json()] == ["Lisbon"]
    assert api.get("/trips/", headers=ben).json() == []
    assert api.get("/flights/", headers=ben).json() == []
    assert api.get(f"/trips/{trip['id']}", headers=ben).status_code == 404
    assert api.post(f"/trips/{trip['id']}/flights/", headers=ben, json={
        "airline": "X", "flight_number": "X 1", "departure_airport": "A", "arrival_airport": "B",
        "departure_time": "2026-05-01T18:00", "arrival_time": "2026-05-01T19:00"}).status_code == 404
    assert api.delete(f"/trips/{trip['id']}", headers=ben).status_code == 404
    assert api.get("/groups", headers=ben).json() == []
    assert api.get(f"/groups/{group['id']}/balances", headers=ben).status_code == 404
    assert api.get("/expenses/", headers=ben).json() == []
    assert api.get("/stats/", headers=ben).status_code in (200, 404)
    ids = {u["id"] for u in api.get("/users/", headers=ben).json()}
    assert ids == {api.get("/me", headers=ben).json()["id"]}


def test_invite_by_email_links_existing_account_and_shares_trip(api):
    ana, ben_tokens = bearer(signup(api)), signup(api, email="ben@example.com", name="Ben")
    ben = bearer(ben_tokens)
    trip = api.post("/trips/", json={"title": "Kyoto"}, headers=ana).json()
    add_and_redeem(api, ana, trip["id"], "Benny", "BEN@example.com", ben)
    parts = api.get(f"/trips/{trip['id']}", headers=ana).json()["participants"]
    assert ben_tokens["user"]["id"] in {p["id"] for p in parts}
    assert not any(p["username"].startswith("Benny") for p in parts)  # the placeholder was replaced
    assert [t["title"] for t in api.get("/trips/", headers=ben).json()] == ["Kyoto"]
    # Once they share a trip, adding by email links the account directly.
    other = api.post("/trips/", json={"title": "Nara"}, headers=ana).json()
    r = api.post(f"/trips/{other['id']}/travelers", json={"name": "Ben", "email": "ben@example.com"}, headers=ana)
    assert ben_tokens["user"]["id"] in {p["id"] for p in r.json()["participants"]}
    # A traveler (not the owner) can't delete the trip.
    assert api.delete(f"/trips/{trip['id']}", headers=ben).status_code == 403


def test_pending_invite_is_claimed_at_signup(api):
    ana = bearer(signup(api))
    trip = api.post("/trips/", json={"title": "Oaxaca"}, headers=ana).json()
    api.post(f"/trips/{trip['id']}/travelers", json={"name": "Cy", "email": "cy@example.com"}, headers=ana)
    invites = api.get(f"/trips/{trip['id']}/invites", headers=ana).json()
    assert [i["email"] for i in invites] == ["cy@example.com"] and invites[0]["claimed_at"] is None
    no_code = api.post("/auth/signup", json={"email": "cy@example.com", "password": "correct horse 1", "name": "Cy"})
    assert no_code.status_code == 403
    assert api.post("/auth/signup", json={"email": "cy@example.com", "password": "correct horse 1", "name": "Cy",
                                          "invite_code": "ABCDE-FGHJK"}).status_code == 403
    code = api.post(f"/trips/{trip['id']}/travelers/{invites[0]['user_id']}/invite-code", headers=ana).json()["code"]
    cy = signup(api, email="cy@example.com", name="Cy Twombly", invite_code=code.lower().replace("-", " "))
    assert cy["claimed"] and cy["claimed"][0].startswith("1 trip")
    # Single use.
    assert api.post("/auth/signup", json={"email": "cy2@example.com", "password": "correct horse 1", "name": "Cy",
                                          "invite_code": code}).status_code == 403
    assert [t["title"] for t in api.get("/trips/", headers=bearer(cy)).json()] == ["Oaxaca"]
    assert api.get(f"/trips/{trip['id']}/invites", headers=ana).json()[0]["claimed_at"] is not None


def test_placeholder_people_cannot_log_in(api, db):
    db.add(models.User(username="maya", email="maya@travelers.trippy.local", is_placeholder=True))
    db.commit()
    assert api.post("/auth/login", json={"email": "maya@travelers.trippy.local", "password": "anything 1"}).status_code == 401
    assert api.post("/auth/signup", json={"email": "maya@travelers.trippy.local", "password": "long enough",
                                          "name": "M"}).status_code == 400


def test_first_signup_claims_legacy_data(api, db, monkeypatch):
    owner = models.User(username="ana", email="ana@legacy.local", is_placeholder=True, legacy_owner=True)
    db.add(owner)
    db.commit()
    db.add(models.Trip(title="Old trip", owner_id=owner.id))
    db.commit()
    monkeypatch.setenv("TRIPPY_FIRST_SIGNUP_CLAIMS_LEGACY", "1")
    first = signup(api, email="me@example.com", name="Me")
    assert first["user"]["id"] == owner.id and first["claimed"]
    assert [t["title"] for t in api.get("/trips/", headers=bearer(first)).json()] == ["Old trip"]
    second = signup(api, email="other@example.com", name="Other")
    assert second["user"]["id"] != owner.id
    assert api.get("/trips/", headers=bearer(second)).json() == []


def test_first_signup_does_not_claim_without_flag(api, db, monkeypatch):
    monkeypatch.delenv("TRIPPY_FIRST_SIGNUP_CLAIMS_LEGACY", raising=False)
    db.add(models.User(username="ana", email="ana@legacy.local", is_placeholder=True, legacy_owner=True))
    db.commit()
    assert signup(api, email="me@example.com", name="Me")["claimed"] == []


def test_delete_account_keeps_shared_ledgers(api, db):
    ana, ben = signup(api), signup(api, email="ben@example.com", name="Ben")
    trip = api.post("/trips/", json={"title": "Shared"}, headers=bearer(ana)).json()
    add_and_redeem(api, bearer(ana), trip["id"], "Ben", "ben@example.com", bearer(ben))
    mine = api.post("/trips/", json={"title": "Ben solo"}, headers=bearer(ben)).json()
    r = api.post(f"/trips/{trip['id']}/expenses/split", headers=bearer(ana), json={
        "amount": 40, "description": "Taxi", "payer_id": ben["user"]["id"],
        "split_among": [ana["user"]["id"], ben["user"]["id"]]})
    assert r.status_code == 200, r.text
    assert api.request("DELETE", "/me", json={"password": "wrong pw!!"}, headers=bearer(ben)).status_code == 400
    assert api.request("DELETE", "/me", json={"password": "correct horse 1"}, headers=bearer(ben)).status_code == 204
    assert db.get(models.Trip, mine["id"]) is None
    gone = db.get(models.User, ben["user"]["id"])
    assert gone.is_placeholder and not (gone.hashed_password or "").startswith("$argon2") and "ben@" not in gone.email
    assert api.post("/auth/login", json={"email": "ben@example.com", "password": "correct horse 1"}).status_code == 401
    bal = api.get(f"/trips/{trip['id']}/balances", headers=bearer(ana))
    assert bal.status_code == 200
    # The email is free again.
    signup(api, email="ben@example.com", name="Ben again")


def test_dev_bypass_only_with_flag(api, db, monkeypatch):
    db.add(models.User(username="ana", email="ana@example.com", hashed_password=auth.hash_password("x" * 8)))
    db.commit()
    assert api.get("/me").status_code == 401
    monkeypatch.setenv("TRIPPY_DEV_AUTH_BYPASS", "1")
    assert api.get("/me").json()["email"] == "ana@example.com"
