import json
"""Quality-of-life fixes: date-only stays, route titles that cover the whole trip."""
import sqlite3
from datetime import datetime

from app import models, titles
from app.importers import ics
from tests.test_migration import alembic

ALL_DAY_HOTEL = b"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:stay-1@test
SUMMARY:Hotel: Hilton Garden Inn Anchorage
LOCATION:100 W Tudor Rd, Anchorage, AK
DTSTART;VALUE=DATE:20270611
DTEND;VALUE=DATE:20270614
END:VEVENT
BEGIN:VEVENT
UID:stay-2@test
SUMMARY:Hotel stay: Cozy Inn
DTSTART:20270701T160000
DTEND:20270703T100000
END:VEVENT
END:VCALENDAR
"""


def test_ics_date_only_stay_gets_usual_hours_marked_approximate():
    items, _ = ics.parse_ics(ALL_DAY_HOTEL)
    stays = {i["fields"]["external_id"]: i["fields"] for i in items if i["kind"] == "lodging"}
    hilton = stays["ics:stay-1@test"]
    assert hilton["check_in"] == datetime(2027, 6, 11, 15) and hilton["check_out"] == datetime(2027, 6, 14, 12)
    assert hilton["time_approx"] is True
    timed = stays["ics:stay-2@test"]
    assert timed["check_in"] == datetime(2027, 7, 1, 16) and timed["time_approx"] is False


def test_stay_hours_default():
    assert ics.stay_hours("Some Small Motel") == (15, 11)
    assert ics.stay_hours("Marriott Downtown") == (16, 12)


def _trip(db, title, owner, auto=True):
    t = models.Trip(title=title, owner_id=owner.id, title_auto=auto)
    db.add(t)
    db.commit()
    return t


def _flight(db, trip, dep, arr, when):
    db.add(models.Flight(trip_id=trip.id, airline="UA", flight_number="UA 1", departure_airport=dep,
                         arrival_airport=arr, departure_time=when, arrival_time=when.replace(hour=when.hour + 2)))


def test_route_title_covers_rental_and_every_flight(db, people):
    owner = db.get(models.User, people["a"])
    t = _trip(db, "San Francisco → Los Angeles (auto)", owner)
    db.add(models.RentalCar(trip_id=t.id, rental_company="Avis", pickup_location="SFO", dropoff_location="LAX",
                            pickup_city="San Francisco", dropoff_city="Los Angeles",
                            pickup_time=datetime(2026, 6, 11, 9), dropoff_time=datetime(2026, 6, 11, 18)))
    _flight(db, t, "LAX", "ANC", datetime(2026, 6, 12, 8))
    _flight(db, t, "ANC", "PHX", datetime(2026, 6, 15, 8))
    _flight(db, t, "PHX", "SFO", datetime(2026, 6, 18, 8))
    db.commit()
    db.refresh(t)
    assert titles.route_places(t) == ["San Francisco", "Los Angeles", "Anchorage", "Phoenix"]
    changes = titles.refresh(db, [t])
    assert t.title == "San Francisco → Los Angeles → Anchorage → Phoenix (auto)"
    assert changes == [(t.id, "San Francisco → Los Angeles (auto)", t.title)]
    assert titles.refresh(db, [t]) == []  # stable


def test_layovers_nearby_airports_and_state_suffixes(db, people):
    owner = db.get(models.User, people["a"])
    t = _trip(db, "Tempe (auto)", owner)
    _flight(db, t, "SFO", "ANC", datetime(2026, 6, 12, 8))
    db.add(models.Flight(trip_id=t.id, airline="AA", flight_number="AA 1", departure_airport="ANC",
                         arrival_airport="PHX", departure_time=datetime(2026, 6, 20, 23, 42),
                         arrival_time=datetime(2026, 6, 21, 6, 11)))
    db.add(models.Flight(trip_id=t.id, airline="AA", flight_number="AA 2", departure_airport="PHX",
                         arrival_airport="SFO", departure_time=datetime(2026, 6, 21, 10, 50),
                         arrival_time=datetime(2026, 6, 21, 12, 57)))
    db.add(models.RentalCar(trip_id=t.id, rental_company="Hertz", pickup_location="x", dropoff_location="x",
                            pickup_city="Tempe, AZ", dropoff_city="Phoenix, AZ", pickup_code=None,
                            pickup_lat=33.42, pickup_lng=-111.94, dropoff_lat=33.45, dropoff_lng=-112.07,
                            pickup_time=datetime(2026, 6, 1, 9), dropoff_time=datetime(2026, 6, 5, 9)))
    db.commit()
    db.refresh(t)
    # PHX at the end is a 4h connection; Tempe and Phoenix are two towns, both kept, without ", AZ"
    assert titles.route_places(t) == ["Tempe", "Phoenix", "San Francisco", "Anchorage"]


def test_route_title_long_routes_and_home_and_suffix(db, people):
    owner = db.get(models.User, people["a"])
    owner.home_airport = "SFO"
    t = _trip(db, "Tokyo (flights)", owner)
    for i, (a, b) in enumerate([("SFO", "NRT"), ("NRT", "SIN"), ("SIN", "DXB"), ("DXB", "LHR"),
                                ("LHR", "JFK"), ("JFK", "SFO")]):
        _flight(db, t, a, b, datetime(2027, 3, 1 + 2 * i, 8))
    db.commit()
    db.refresh(t)
    titles.refresh(db, [t])
    assert t.title == "Tokyo → Singapore → Dubai → London +1 (flights)"


def test_hand_titles_are_never_rewritten(client, db, people):
    owner = db.get(models.User, people["a"])
    client.acting_as = owner.id
    r = client.post("/trips/", json={"title": "Oakland (auto)"})
    assert r.status_code in (200, 201) and r.json()["title_auto"] is True
    tid = r.json()["id"]
    _flight(db, db.get(models.Trip, tid), "OAK", "LAS", datetime(2027, 1, 5, 8))
    db.commit()
    assert client.get(f"/trips/{tid}").json()["title"] == "Oakland → Las Vegas (auto)"
    r = client.patch(f"/trips/{tid}", json={"title": "Vegas weekend"})
    assert r.status_code == 200 and r.json()["title"] == "Vegas weekend" and r.json()["title_auto"] is False
    _flight(db, db.get(models.Trip, tid), "LAS", "DEN", datetime(2027, 1, 7, 8))
    db.commit()
    assert client.get(f"/trips/{tid}").json()["title"] == "Vegas weekend"
    assert {t["id"]: t["title"] for t in client.get("/trips/").json()}[tid] == "Vegas weekend"
    assert client.patch(f"/trips/{tid}", json={"title": "  "}).status_code == 400
    plain = client.post("/trips/", json={"title": "Honeymoon"}).json()
    assert plain["title_auto"] is False


def test_rename_is_owner_only(client, db, people):
    owner, guest = db.get(models.User, people["a"]), db.get(models.User, people["b"])
    t = _trip(db, "Ana's (auto)", owner)
    t.participants.append(guest)
    db.commit()
    client.acting_as = guest.id
    assert client.patch(f"/trips/{t.id}", json={"title": "Mine now"}).status_code in (403, 404)


def test_migration_fixes_midnight_stays_and_flags_auto_titles_reversibly(tmp_path):
    db = tmp_path / "old.db"
    alembic(db, "upgrade", "c3e8b5d1f7a2")
    c = sqlite3.connect(db)
    c.execute("INSERT INTO users (id, username, email, hashed_password) VALUES (1, 'a', 'a@t.local', 'x')")
    c.executemany("INSERT INTO trips (id, title, owner_id) VALUES (?,?,1)",
                  [(1, "Fremont (auto)"), (2, "Delhi (flights)"), (3, "Lisbon (email)"), (4, "Honeymoon")])
    c.executemany("INSERT INTO lodgings (id, name, check_in, check_out) VALUES (?,?,?,?)", [
        (1, "ICS Hotel", "2026-06-11 00:00:00.000000", "2026-06-14 00:00:00.000000"),
        (2, "Real Hotel", "2026-06-11 15:00:00.000000", "2026-06-14 11:00:00.000000"),
        (3, "Late arrival", "2026-06-11 00:00:00.000000", "2026-06-12 11:00:00.000000"),
    ])
    c.commit()
    c.close()
    alembic(db, "upgrade", "head")
    c = sqlite3.connect(db)
    rows = {r[0]: r[1:] for r in c.execute("SELECT id, check_in, check_out, time_approx FROM lodgings")}
    assert rows[1] == ("2026-06-11 15:00:00.000000", "2026-06-14 11:00:00.000000", 1)
    assert rows[2][2] == 0 and rows[3][2] == 0  # a real midnight check-in with a timed check-out stays
    assert dict(c.execute("SELECT id, title_auto FROM trips")) == {1: 1, 2: 1, 3: 1, 4: 0}
    c.close()
    alembic(db, "downgrade", "c3e8b5d1f7a2")
    c = sqlite3.connect(db)
    assert c.execute("SELECT check_in, check_out FROM lodgings WHERE id = 1").fetchone() == (
        "2026-06-11 00:00:00.000000", "2026-06-14 00:00:00.000000")
    assert "time_approx" not in {r[1] for r in c.execute("PRAGMA table_info(lodgings)")}
    c.close()
    alembic(db, "upgrade", "head")


def test_automatic_retitles_are_journaled_for_revert(db, people, tmp_path, monkeypatch):
    log = tmp_path / "title-changes.jsonl"
    monkeypatch.setenv("TRIPPY_TITLE_LOG", str(log))
    owner = db.get(models.User, people["a"])
    t = _trip(db, "Oakland (auto)", owner)
    _flight(db, t, "OAK", "LAS", datetime(2026, 3, 1, 9))
    _flight(db, t, "LAS", "OAK", datetime(2026, 3, 5, 9))
    db.commit()
    db.refresh(t)
    changes = titles.refresh(db, [t])
    assert changes == [(t.id, "Oakland (auto)", "Oakland → Las Vegas (auto)")]
    rows = [json.loads(l) for l in log.read_text().splitlines()]
    assert rows[0]["id"] == t.id and rows[0]["old"] == "Oakland (auto)" and rows[0]["new"] == "Oakland → Las Vegas (auto)"
    assert titles.refresh(db, [t]) == []  # stable: nothing new to write
    assert len(log.read_text().splitlines()) == 1
