"""Deleting trips: preview, Recently Deleted, restore, purge, bulk, journeys, leaving, email-in."""
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime as dt, timedelta
from pathlib import Path

import pytest

from app import inbound, models, trash
from tests.test_inbound import FLIGHT, addr, mail, on, users  # noqa: F401  (fixtures)
from tests.test_journeys import _trip, _user


@pytest.fixture()
def world(db):
    ana, ben = _user(db, "ana"), _user(db, "ben")
    lis = _trip(db, ana, "Lisbon", dt(2026, 5, 1), dt(2026, 5, 5),
                flights=[("SFO", "LIS", dt(2026, 5, 1, 8)), ("LIS", "SFO", dt(2026, 5, 5, 9))],
                stays=[("Memmo", "Lisbon", dt(2026, 5, 1), dt(2026, 5, 3)), ("Torel", "Lisbon", dt(2026, 5, 3), dt(2026, 5, 5))],
                rentals=[("LIS", "LIS", dt(2026, 5, 2, 9), dt(2026, 5, 3, 9))])
    por = _trip(db, ana, "Porto", dt(2026, 5, 6), dt(2026, 5, 8), stays=[("Ribeira", "Porto", dt(2026, 5, 6), dt(2026, 5, 8))])
    mad = _trip(db, ana, "Madrid", dt(2026, 5, 9), dt(2026, 5, 12), flights=[("OPO", "MAD", dt(2026, 5, 9, 10))])
    lis.participants.append(ben)
    db.commit()
    return {"ana": ana, "ben": ben, "lis": lis.id, "por": por.id, "mad": mad.id}


def as_(client, user):
    client.acting_as = user.id
    return client


def test_preview_counts_and_unsettled_warning(client, db, world):
    c = as_(client, world["ana"])
    c.post(f"/trips/{world['lis']}/expenses/split", json={"amount": 50, "description": "Dinner",
                                                        "payer_id": world["ana"].id,
                                                        "split_among": [world["ana"].id, world["ben"].id]})
    p = c.get(f"/trips/{world['lis']}/delete-preview").json()
    assert p["action"] == "delete" and p["keep_days"] == 30
    assert {k: p["counts"][k] for k in ("flights", "stays", "rentals", "expenses", "travelers")} == \
        {"flights": 2, "stays": 2, "rentals": 1, "expenses": 1, "travelers": 1}
    assert p["unsettled"] is True and p["unsettled_people"] == 2 and p["unsettled_cents"] == 2500
    # A warning, not a block.
    assert c.delete(f"/trips/{world['lis']}").status_code == 204
    assert c.get(f"/trips/{world['por']}/delete-preview").json()["unsettled"] is False


def test_deleted_trip_is_hidden_everywhere_and_restores(client, db, world):
    c = as_(client, world["ana"])
    before = c.get("/stats/").json()
    c.put(f"/trips/{world['lis']}/story", json={"title": "Pastéis"})
    assert c.delete(f"/trips/{world['lis']}").status_code == 204
    assert world["lis"] not in [t["id"] for t in c.get("/trips/").json()]
    assert c.get(f"/trips/{world['lis']}").status_code == 404
    assert c.get(f"/trips/{world['lis']}/story").status_code == 404
    assert [f["departure_airport"] for f in c.get("/flights/").json()] == ["OPO"]
    assert c.get("/rental_cars/").json() == []
    assert {h["name"] for h in c.get("/lodgings/").json()} == {"Ribeira"}
    assert c.get("/stats/").json() != before
    # Ben (a traveler) no longer sees it either.
    assert as_(client, world["ben"]).get("/trips/").json() == []
    c = as_(client, world["ana"])
    (row,) = c.get("/trash/trips").json()["trips"]
    assert row["id"] == world["lis"] and row["counts"]["flights"] == 2
    assert dt.fromisoformat(row["purge_at"]) - dt.fromisoformat(row["deleted_at"]) == timedelta(days=30)
    # Nothing was actually removed.
    assert db.query(models.Flight).count() == 3 and db.query(models.Lodging).count() == 3
    r = c.post(f"/trash/trips/{world['lis']}/restore")
    assert r.status_code == 200 and r.json()["id"] == world["lis"]
    assert c.get(f"/trips/{world['lis']}/story").json()["title"] == "Pastéis"
    assert c.get("/stats/").json() == before
    assert c.get("/trash/trips").json()["trips"] == []
    assert as_(client, world["ben"]).get("/trips/").json()[0]["id"] == world["lis"]


def test_only_the_owner_deletes_travelers_leave(client, db, world):
    c = as_(client, world["ben"])
    assert c.get(f"/trips/{world['lis']}/delete-preview").json()["action"] == "leave"
    assert c.delete(f"/trips/{world['lis']}").status_code == 403
    assert c.post(f"/trash/trips/{world['lis']}/restore").status_code == 404
    out = c.post("/trips/bulk-delete", json={"trip_ids": [world["lis"], world["por"]]}).json()
    assert out["deleted"] == [] and {s["reason"] for s in out["skipped"]} == {"not_owner", "not_found"}
    assert c.post(f"/trips/{world['lis']}/leave").status_code == 204
    assert c.get("/trips/").json() == []
    assert as_(client, world["ana"]).post(f"/trips/{world['lis']}/leave").status_code == 400


def test_journey_keeps_one_trip_and_goes_away_at_zero(client, db, world):
    c = as_(client, world["ana"])
    j = c.post("/journeys/", json={"trip_ids": [world["lis"], world["por"], world["mad"]]}).json()
    p = c.get(f"/trips/{world['mad']}/delete-preview").json()
    assert p["journey"] == {"id": j["id"], "title": j["title"], "trips_left": 2, "journey_deleted": False}
    c.delete(f"/trips/{world['mad']}")
    assert c.get(f"/journeys/{j['id']}").json()["trip_ids"] == [world["lis"], world["por"]]
    c.delete(f"/trips/{world['por']}")
    assert c.get(f"/journeys/{j['id']}").json()["trip_ids"] == [world["lis"]]  # 1 trip: kept
    assert c.get(f"/trips/{world['lis']}/delete-preview").json()["journey"]["journey_deleted"] is True
    c.delete(f"/trips/{world['lis']}")
    assert c.get(f"/journeys/{j['id']}").status_code == 404
    # Restoring after the journey is gone leaves the trip on its own.
    c.post(f"/trash/trips/{world['lis']}/restore")
    assert db.get(models.Trip, world["lis"]).journey_id is None


def test_restore_rejoins_a_journey_that_still_exists(client, db, world):
    c = as_(client, world["ana"])
    j = c.post("/journeys/", json={"trip_ids": [world["lis"], world["por"], world["mad"]]}).json()
    c.delete(f"/trips/{world['por']}")
    c.post(f"/trash/trips/{world['por']}/restore")
    assert c.get(f"/journeys/{j['id']}").json()["trip_ids"] == [world["lis"], world["por"], world["mad"]]


def test_delete_journey_unlinks_by_default_or_deletes_its_trips(client, db, world):
    c = as_(client, world["ana"])
    j = c.post("/journeys/", json={"trip_ids": [world["lis"], world["por"]]}).json()
    out = c.delete(f"/journeys/{j['id']}").json()
    assert out["unlinked_trip_ids"] == [world["lis"], world["por"]] and out["deleted_trip_ids"] == []
    assert len(c.get("/trips/").json()) == 3
    j = c.post("/journeys/", json={"trip_ids": [world["lis"], world["por"]]}).json()
    out = c.delete(f"/journeys/{j['id']}?delete_trips=true").json()
    assert sorted(out["deleted_trip_ids"]) == sorted([world["lis"], world["por"]])
    assert [t["id"] for t in c.get("/trips/").json()] == [world["mad"]]
    assert db.query(models.Journey).count() == 0
    assert len(c.get("/trash/trips").json()["trips"]) == 2


def test_bulk_delete_permanent_and_delete_now(client, db, world):
    c = as_(client, world["ana"])
    out = c.post("/trips/bulk-delete", json={"trip_ids": [world["por"], world["mad"]]}).json()
    assert [d["id"] for d in out["deleted"]] == [world["por"], world["mad"]]
    assert c.delete(f"/trash/trips/{world['por']}").status_code == 204
    assert db.get(models.Trip, world["por"]) is None and db.query(models.Lodging).count() == 2
    assert c.delete("/trash/trips").json() == {"purged": 1}
    out = c.post("/trips/bulk-delete", json={"trip_ids": [world["lis"]], "permanent": True}).json()
    assert out["deleted"][0]["permanent"] is True
    assert db.query(models.Trip).count() == 0 and db.query(models.Flight).count() == 0
    assert db.query(models.RentalCar).count() == 0 and db.query(models.Lodging).count() == 0


def test_purge_after_30_days_keeps_other_travelers_bookings(db, world):
    lis = db.get(models.Trip, world["lis"])
    db.add(models.Flight(trip_id=lis.id, owner_id=world["ben"].id, airline="TP", flight_number="TP 1",
                         departure_airport="LIS", arrival_airport="OPO", departure_time=dt(2026, 5, 4, 9)))
    db.commit()
    trash.soft_delete(db, lis, now=dt.utcnow() - timedelta(days=31))
    trash.soft_delete(db, db.get(models.Trip, world["por"]), now=dt.utcnow() - timedelta(days=29))
    db.commit()
    assert trash.purge_expired(db) == 1
    assert db.get(models.Trip, world["lis"]) is None and db.get(models.Trip, world["por"]) is not None
    (bens,) = db.query(models.Flight).filter(models.Flight.owner_id == world["ben"].id).all()
    assert bens.trip_id is None  # unlinked, not deleted
    assert db.query(models.Flight).filter(models.Flight.owner_id == world["ana"].id).count() == 1  # Madrid's


def test_email_in_does_not_bring_back_a_deleted_trip(client, db, users, on):
    ana = users[0]
    first = inbound.receive(db, mail(to=addr(db, ana), mid="<a@x>"))
    (trip_id,) = inbound.summary(first)["new_trip_ids"]
    client.acting_as = ana.id
    assert client.delete(f"/trips/{trip_id}").status_code == 204
    again = inbound.receive(db, mail(to=addr(db, ana), mid="<b@x>"))
    assert again.status == "duplicate"
    assert json.loads(again.result_json)["skipped"][0]["reason"] == "deleted"
    assert db.query(models.Trip).count() == 1 and db.query(models.Flight).count() == 1
    assert client.get("/trips/").json() == []


def test_suggestions_ignore_deleted_trips(client, db, world):
    c = as_(client, world["ana"])
    ids = lambda: {i for s in c.get("/journeys/suggestions").json()["suggestions"] for i in s["trip_ids"]}
    assert world["por"] in ids()
    c.delete(f"/trips/{world['por']}")
    assert world["por"] not in ids()


def test_migration_adds_trash_columns(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    env = {**os.environ, "TRIPPY_DATABASE_URL": f"sqlite:///{tmp_path / 't.db'}"}
    run = lambda *a: subprocess.run([sys.executable, "-m", "alembic", *a], cwd=repo, env=env, check=True,
                                    capture_output=True, text=True)
    run("upgrade", "a7d2e9f1c3b5")
    c = sqlite3.connect(tmp_path / "t.db")
    c.execute("INSERT INTO trips (id, title) VALUES (1, 'Kept')")
    c.commit()
    run("upgrade", "head")
    assert c.execute("SELECT id, title, deleted_at, trash_json FROM trips").fetchall() == [(1, "Kept", None, None)]
    assert c.execute("SELECT count(*) FROM trip_pins").fetchone() == (0,)
    run("downgrade", "a7d2e9f1c3b5")
    assert "deleted_at" not in {r[1] for r in c.execute("PRAGMA table_info(trips)")}
    assert not c.execute("SELECT name FROM sqlite_master WHERE name = 'trip_pins'").fetchall()
    run("upgrade", "head")
    c.close()


def test_pins_are_per_user_and_survive_trash(client, db, world):
    c = as_(client, world["ana"])
    assert c.put(f"/trips/{world['lis']}/pin").json() == {"trip_id": world["lis"], "pinned": True}
    c.put(f"/trips/{world['lis']}/pin")  # idempotent
    pinned = lambda cl: {t["id"] for t in cl.get("/trips/").json() if t["pinned"]}
    assert pinned(c) == {world["lis"]} and c.get(f"/trips/{world['lis']}").json()["pinned"] is True
    assert pinned(as_(client, world["ben"])) == set()  # Ben's list isn't affected
    c = as_(client, world["ana"])
    c.delete(f"/trips/{world['lis']}")
    c.post(f"/trash/trips/{world['lis']}/restore")
    assert pinned(c) == {world["lis"]}
    assert c.delete(f"/trips/{world['lis']}/pin").json()["pinned"] is False and pinned(c) == set()
    c.put(f"/trips/{world['por']}/pin")
    c.delete(f"/trips/{world['por']}?permanent=true")
    assert db.query(models.TripPin).count() == 0
    assert as_(client, world["ben"]).put(f"/trips/{world['por']}/pin").status_code == 404
