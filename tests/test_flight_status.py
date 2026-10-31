from datetime import date, datetime, timedelta

import pytest

from app import flight_status, models


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in ("PROVIDER", "API_KEY", "BASE_URL", "CACHE_SECONDS"):
        monkeypatch.delenv(f"TRIPPY_FLIGHT_STATUS_{k}", raising=False)
    flight_status.clear_cache()
    yield
    flight_status.clear_cache()


def _flight(db, people, number="UA 837", when=None):
    f = models.Flight(trip_id=people["trip"], airline="United", flight_number=number,
                      departure_airport="SFO", arrival_airport="NRT",
                      departure_time=when or datetime.utcnow() + timedelta(hours=6),
                      arrival_time=(when or datetime.utcnow()) + timedelta(hours=17))
    db.add(f)
    db.commit()
    return f.id


def test_off_by_default(client, db, people):
    fid = _flight(db, people)
    body = client.get(f"/flights/{fid}/status").json()
    assert body["configured"] is False and body["status"] is None
    assert "isn't configured" in body["message"]


def test_provider_without_key_stays_off(monkeypatch):
    monkeypatch.setenv("TRIPPY_FLIGHT_STATUS_PROVIDER", "aerodatabox")
    assert flight_status.configured() is None
    monkeypatch.setenv("TRIPPY_FLIGHT_STATUS_API_KEY", "k")
    assert flight_status.configured() == "aerodatabox"
    monkeypatch.setenv("TRIPPY_FLIGHT_STATUS_PROVIDER", "opensky")
    assert flight_status.configured() is None


def test_other_users_flight_is_404(client, db, people):
    fid = _flight(db, people)
    stranger = models.User(username="Zed", email="z@t.local", hashed_password="x")
    db.add(stranger)
    db.commit()
    client.acting_as = stranger.id
    assert client.get(f"/flights/{fid}/status").status_code == 404


@pytest.mark.parametrize("text,expected", [("UA 837", ("UA", "837")), ("ua0837", ("UA", "837")),
                                           ("B6 23", ("B6", "23")), ("UAL 1", ("UAL", "1")),
                                           ("hello", None), ("", None)])
def test_split_flight_number(text, expected):
    assert flight_status.split_flight_number(text) == expected


ADB = [{"status": "Delayed", "departure": {"scheduledTime": {"local": "2026-11-01 11:00-07:00"},
                                          "revisedTime": {"local": "2026-11-01 11:45-07:00"},
                                          "terminal": "3", "gate": "G92"},
        "arrival": {"scheduledTime": {"local": "2026-11-02 15:00+09:00"}, "baggageBelt": "7"}}]


def test_aerodatabox_parse_and_headers():
    calls = []
    st = flight_status.aerodatabox("UA", "837", date(2026, 11, 1), "KEY", "",
                                   lambda url, h: calls.append((url, h)) or ADB)
    assert calls[0][0].startswith("https://aerodatabox.p.rapidapi.com/flights/number/UA837/2026-11-01")
    assert calls[0][1]["X-RapidAPI-Key"] == "KEY"
    assert (st.status, st.departure_gate, st.baggage_claim, st.delay_minutes) == ("delayed", "G92", "7", 45)


def test_aviationstack_filters_by_day():
    data = {"data": [{"flight_date": "2026-10-31", "flight_status": "landed"},
                     {"flight_date": "2026-11-01", "flight_status": "active",
                      "departure": {"gate": "G1", "delay": 12}, "arrival": {"baggage": "3"}}]}
    st = flight_status.aviationstack("UA", "837", date(2026, 11, 1), "K", "", lambda u, h: data)
    assert (st.status, st.departure_gate, st.delay_minutes) == ("en_route", "G1", 12)
    with pytest.raises(flight_status.StatusError):
        flight_status.aviationstack("UA", "837", date(2026, 11, 1), "K", "", lambda u, h: {"error": {"code": 101}})


def test_aeroapi_cancelled():
    data = {"flights": [{"cancelled": True, "status": "Scheduled", "gate_origin": "B2", "departure_delay": 600}]}
    st = flight_status.aeroapi("UA", "837", date(2026, 11, 1), "K", "", lambda u, h: data)
    assert (st.status, st.departure_gate, st.delay_minutes) == ("cancelled", "B2", 10)


def test_route_uses_cache_and_window(client, db, people, monkeypatch):
    monkeypatch.setenv("TRIPPY_FLIGHT_STATUS_PROVIDER", "aerodatabox")
    monkeypatch.setenv("TRIPPY_FLIGHT_STATUS_API_KEY", "secret-key")
    calls = []
    monkeypatch.setattr(flight_status, "_http_get", lambda u, h: calls.append(u) or ADB)
    monkeypatch.setattr(flight_status.lookup, "__defaults__", (flight_status._http_get,))
    fid = _flight(db, people)
    for _ in range(3):
        body = client.get(f"/flights/{fid}/status").json()
    assert body["configured"] and body["status"]["departure_gate"] == "G92"
    assert len(calls) == 1  # cached
    assert "secret-key" not in str(body)
    far = _flight(db, people, when=datetime.utcnow() + timedelta(days=20))
    assert "two days" in client.get(f"/flights/{far}/status").json()["message"]
    assert len(calls) == 1


def test_provider_error_is_502(client, db, people, monkeypatch):
    monkeypatch.setenv("TRIPPY_FLIGHT_STATUS_PROVIDER", "aeroapi")
    monkeypatch.setenv("TRIPPY_FLIGHT_STATUS_API_KEY", "k")

    def boom(u, h):
        raise flight_status.StatusError("The flight status provider's quota is used up for now.")
    monkeypatch.setattr(flight_status.lookup, "__defaults__", (boom,))
    fid = _flight(db, people)
    r = client.get(f"/flights/{fid}/status")
    assert r.status_code == 502 and "quota" in r.json()["detail"]


def test_aerodatabox_channel_headers():
    from app.flight_status import _aerodatabox_headers
    assert _aerodatabox_headers("aerodatabox.p.rapidapi.com", "k") == {
        "X-RapidAPI-Key": "k", "X-RapidAPI-Host": "aerodatabox.p.rapidapi.com"}
    assert _aerodatabox_headers("prod.api.market", "k") == {"x-api-market-key": "k"}
    assert _aerodatabox_headers("api.aerodatabox.com", "k") == {"X-Api-Key": "k"}
