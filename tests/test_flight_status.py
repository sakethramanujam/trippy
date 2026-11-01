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
    calls = []
    data = {"data": [{"flight_date": "2026-10-31", "flight_status": "landed"},
                     {"flight_date": "2026-11-01", "flight_status": "active",
                      "departure": {"gate": "G1", "delay": 12}, "arrival": {"baggage": "3"}}]}
    st = flight_status.aviationstack("UA", "837", date(2026, 11, 1), "K", "", lambda u, h: calls.append(u) or data)
    assert calls[0].startswith("https://api.aviationstack.com/v1/flights?")
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


ADB_LOOKUP = [{
    "status": "Scheduled",
    "airline": {"name": "United Airlines", "iata": "UA"},
    "aircraft": {"model": "Boeing 787-9"},
    "departure": {
        "airport": {"iata": "SFO", "name": "San Francisco"},
        "scheduledTime": {"local": "2026-11-01 11:00-07:00"},
        "terminal": "I",
        "gate": "G92",
    },
    "arrival": {
        "airport": {"iata": "NRT", "name": "Tokyo Narita"},
        "scheduledTime": {"local": "2026-11-02 15:00+09:00"},
    },
}]


def test_flights_lookup_prefill(client, people, monkeypatch):
    # 503 when flight status provider is not configured
    r = client.get("/flights/lookup", params={"flight_number": "UA 837", "date": "2026-11-01"})
    assert r.status_code == 503

    monkeypatch.setenv("TRIPPY_FLIGHT_STATUS_PROVIDER", "aerodatabox")
    monkeypatch.setenv("TRIPPY_FLIGHT_STATUS_API_KEY", "secret-key")
    monkeypatch.setattr(flight_status, "_http_get", lambda u, h: ADB_LOOKUP)
    monkeypatch.setattr(flight_status.lookup, "__defaults__", (flight_status._http_get,))

    # 400 on invalid flight number or date
    assert client.get("/flights/lookup", params={"flight_number": "not-a-flight", "date": "2026-11-01"}).status_code == 400
    assert client.get("/flights/lookup", params={"flight_number": "UA 837", "date": "bad-date"}).status_code == 400

    # 200 with schedule prefill
    res = client.get("/flights/lookup", params={"flight_number": "ua837", "date": "2026-11-01"})
    assert res.status_code == 200
    body = res.json()
    assert body["flight_number"] == "UA 837"
    assert body["airline"] == "United Airlines"
    assert body["departure_airport"] == "SFO"
    assert body["arrival_airport"] == "NRT"
    assert body["departure_time"].startswith("2026-11-01T11:00:00")
    assert body["arrival_time"].startswith("2026-11-02T15:00:00")
    assert body["terminal"] == "I"
    assert body["gate"] == "G92"
    assert body["aircraft_model"] == "Boeing 787-9"

    # 404 when provider returns empty schedule
    monkeypatch.setattr(flight_status, "_http_get", lambda u, h: [])
    monkeypatch.setattr(flight_status.lookup, "__defaults__", (flight_status._http_get,))
    flight_status.clear_cache()
    assert client.get("/flights/lookup", params={"flight_number": "UA 999", "date": "2026-11-01"}).status_code == 404


def test_flight_patch_delete_and_extra_fields(client, db, people):
    created = client.post(f"/trips/{people['trip']}/flights/", json={
        "airline": "United",
        "flight_number": "UA 837",
        "departure_airport": "SFO",
        "arrival_airport": "NRT",
        "departure_time": "2026-11-01T11:00:00",
        "arrival_time": "2026-11-02T15:00:00",
        "seat": "12A",
        "cabin_class": "Economy",
        "terminal": "I",
        "gate": "G92",
        "notes": "Window seat, vegetarian meal",
    })
    assert created.status_code == 200
    f = created.json()
    fid = f["id"]
    assert f["terminal"] == "I" and f["gate"] == "G92" and f["notes"] == "Window seat, vegetarian meal"

    # PATCH updates only supplied fields
    patched = client.patch(f"/flights/{fid}", json={
        "seat": "3A",
        "cabin_class": "Business",
        "gate": "G94",
        "notes": "Upgraded with miles",
    })
    assert patched.status_code == 200
    body = patched.json()
    assert body["seat"] == "3A"
    assert body["cabin_class"] == "Business"
    assert body["terminal"] == "I"
    assert body["gate"] == "G94"
    assert body["notes"] == "Upgraded with miles"

    # Non-owner trip participant cannot edit or delete another participant's flight unless trip owner
    # people["trip"] is owned by people["a"] (client's default user); act as people["b"] (a trip participant,
    # not trip owner) and verify 403.
    client.acting_as = people["b"]
    assert client.get(f"/flights/{fid}").status_code == 200
    assert client.patch(f"/flights/{fid}", json={"seat": "99Z"}).status_code == 403
    assert client.delete(f"/flights/{fid}").status_code == 403

    # Owner can delete
    client.acting_as = people["a"]
    assert client.delete(f"/flights/{fid}").status_code == 204
    assert client.get(f"/flights/{fid}").status_code == 404

