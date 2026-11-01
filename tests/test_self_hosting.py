"""Self-hosting settings: signup modes, allowlist, health, CORS origins, SMTP reset delivery."""
import pytest

from app import mailer


def signup(api, email, name="Someone"):
    return api.post("/auth/signup", json={"email": email, "password": "long enough 1", "name": name})


def test_health_reports_service_and_signup_mode(api, monkeypatch):
    monkeypatch.setenv("TRIPPY_SIGNUP_MODE", "invite")
    body = api.get("/health").json()
    assert body["status"] == "healthy" and body["service"] == "trippy"
    assert body["signup"] == "invite" and body["password_reset"] == "server-log"


@pytest.mark.parametrize("mode", ["invite", "closed"])
def test_first_account_can_always_sign_up(api, monkeypatch, mode):
    monkeypatch.setenv("TRIPPY_SIGNUP_MODE", mode)
    assert signup(api, "owner@example.com").status_code == 201
    r = signup(api, "stranger@example.com")
    assert r.status_code == 403
    assert ("invite-only" if mode == "invite" else "closed") in r.json()["detail"]


def test_invite_mode_lets_invited_people_join(api, monkeypatch):
    monkeypatch.setenv("TRIPPY_SIGNUP_MODE", "invite")
    owner = {"Authorization": f"Bearer {signup(api, 'owner@example.com').json()['access_token']}"}
    trip = api.post("/trips/", headers=owner, json={"title": "Lisbon", "start_date": "2031-05-01T00:00:00",
                                                   "end_date": "2031-05-05T00:00:00"}).json()
    r = api.post(f"/trips/{trip['id']}/travelers", headers=owner, json={"email": "friend@example.com", "name": "Friend"})
    assert r.status_code in (200, 201), r.text
    friend = next(p for p in r.json()["participants"] if p["username"] != "owner")
    # Knowing the invited email isn't enough: the traveler needs the one-time code.
    assert signup(api, "friend@example.com", "Friend").status_code == 403
    code = api.post(f"/trips/{trip['id']}/travelers/{friend['id']}/invite-code", headers=owner).json()["code"]
    ok = api.post("/auth/signup", json={"email": "friend@example.com", "password": "long enough 1",
                                        "name": "Friend", "invite_code": code})
    assert ok.status_code == 201 and ok.json()["user"]["id"] == friend["id"]
    assert signup(api, "stranger@example.com").status_code == 403


def test_closed_mode_blocks_invited_but_allowlist_wins(api, monkeypatch):
    monkeypatch.setenv("TRIPPY_SIGNUP_MODE", "closed")
    monkeypatch.setenv("TRIPPY_SIGNUP_ALLOWLIST", "@family.example, pal@example.com")
    # With TRIPPY_SIGNUP_ALLOWLIST set, a non-allowlisted stranger cannot even claim the first account
    assert signup(api, "scanner@stranger.example").status_code == 403
    assert signup(api, "owner@family.example").status_code == 201
    assert signup(api, "kid@family.example").status_code == 201
    assert signup(api, "pal@example.com").status_code == 201
    assert signup(api, "other@example.com").status_code == 403


def test_bad_signup_mode_fails_loudly(monkeypatch):
    from app import auth
    monkeypatch.setenv("TRIPPY_SIGNUP_MODE", "sometimes")
    with pytest.raises(RuntimeError):
        auth.signup_mode()


def test_dev_bypass_refused_on_non_loopback_bind(monkeypatch):
    from app import auth
    monkeypatch.setenv("TRIPPY_DEV_AUTH_BYPASS", "1")
    monkeypatch.setenv("TRIPPY_BIND", "127.0.0.1")
    assert auth.dev_bypass() is True
    monkeypatch.setenv("TRIPPY_BIND", "0.0.0.0")
    with pytest.raises(RuntimeError):
        auth.dev_bypass()
    monkeypatch.setenv("TRIPPY_BIND", "127.0.0.1")
    monkeypatch.setenv("TRIPPY_LISTEN", "127.0.0.1:8000,192.168.1.10:8000")
    with pytest.raises(RuntimeError):
        auth.dev_bypass()


def test_reset_code_is_emailed_when_smtp_is_configured(api, monkeypatch):
    sent = []
    monkeypatch.setenv("TRIPPY_SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(mailer, "send_reset_code", lambda to, code: sent.append((to, code)))
    signup(api, "owner@example.com")
    body = api.post("/auth/forgot", json={"email": "owner@example.com"}).json()
    assert body["delivery"] == "email" and "dev_reset_token" not in body
    assert sent and sent[0][0] == "owner@example.com"
    r = api.post("/auth/reset", json={"token": sent[0][1], "password": "another long 2"})
    assert r.status_code == 200


def test_reset_message_contains_code_and_sender(monkeypatch):
    monkeypatch.setenv("TRIPPY_SMTP_FROM", "Trippy <trippy@example.com>")
    msg = mailer.reset_message("a@example.com", "abc123")
    assert msg["From"] == "Trippy <trippy@example.com>" and "abc123" in msg.get_content()


def test_allowed_origins_parsing(monkeypatch):
    from app.main import _allowed_origins
    monkeypatch.setenv("TRIPPY_ALLOWED_ORIGINS", "https://trips.example.com/, http://localhost:3000")
    assert _allowed_origins() == ["https://trips.example.com", "http://localhost:3000"]
    monkeypatch.setenv("TRIPPY_ALLOWED_ORIGINS", "")
    assert _allowed_origins() == []
    monkeypatch.setenv("TRIPPY_ALLOWED_ORIGINS", "*")
    assert _allowed_origins() == []
