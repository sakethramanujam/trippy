"""Trip stories (generation, per-user edits, access) and Year in Travel."""
import sqlite3
from datetime import datetime

from app import models, stories
from tests.test_auth import add_and_redeem, bearer, signup
from tests.test_migration import alembic


def _trip_with_everything(api, db, headers, user_id):
    trip = api.post("/trips/", json={"title": "Japan", "start_date": "2026-03-01T00:00:00",
                                     "end_date": "2026-03-08T00:00:00"}, headers=headers).json()
    tid = trip["id"]
    db.add_all([
        models.Flight(trip_id=tid, owner_id=user_id, airline="United", flight_number="UA 837",
                      departure_airport="SFO", arrival_airport="NRT",
                      departure_time=datetime(2026, 3, 1, 11), arrival_time=datetime(2026, 3, 2, 15, 5)),
        models.Flight(trip_id=tid, owner_id=user_id, airline="ANA", flight_number="NH 7",
                      departure_airport="NRT", arrival_airport="SFO", distance_miles=5130,
                      departure_time=datetime(2026, 3, 8, 17), arrival_time=datetime(2026, 3, 8, 10)),
        models.RentalCar(trip_id=tid, owner_id=user_id, rental_company="Toyota Rent a Car", car_model="Prius",
                         pickup_location="Tokyo", dropoff_location="Kyoto", pickup_city="Tokyo", dropoff_city="Kyoto",
                         pickup_lat=35.68, pickup_lng=139.76, dropoff_lat=35.01, dropoff_lng=135.77,
                         pickup_time=datetime(2026, 3, 3, 9), dropoff_time=datetime(2026, 3, 5, 18), mileage_driven=290),
        models.Lodging(trip_id=tid, owner_id=user_id, name="Hoshinoya Kyoto", address="Kyoto",
                       check_in=datetime(2026, 3, 5, 15), check_out=datetime(2026, 3, 7, 11)),
        models.Expense(trip_id=tid, payer_id=user_id, amount=42.5, description="Ramen", currency="USD",
                       date=datetime(2026, 3, 2, 19)),
        models.Expense(trip_id=tid, payer_id=user_id, amount=240, description="Kaiseki dinner", currency="USD",
                       date=datetime(2026, 3, 5, 19)),
        models.Expense(trip_id=tid, payer_id=user_id, amount=18, description="Bus", currency="USD",
                       date=datetime(2026, 3, 5, 9)),
    ])
    db.commit()
    return tid


def test_story_is_generated_in_order_with_stats(api, db):
    ana = signup(api, home_airport="SFO")
    h = bearer(ana)
    tid = _trip_with_everything(api, db, h, ana["user"]["id"])
    s = api.get(f"/trips/{tid}/story", headers=h).json()

    assert s["title"] == "Japan" and s["edited"] is False and s["theme"] == "indigo"
    assert [i["key"].split(":")[0] for i in s["items"]] == [
        "flight", "expenses", "rental", "lodging", "expenses", "flight"]
    first = s["items"][0]
    assert first["title"] == "San Francisco to Tokyo" and first["day"] == 1
    assert first["subtitle"] == "United UA 837 · 28h 5m"  # naive times: no time zones in the DB
    assert s["items"][1]["title"] == "Spent $42.50" and s["items"][4]["title"] == "Spent $258"
    assert s["items"][4]["subtitle"] == "Kaiseki dinner, Bus"
    assert s["items"][2]["subtitle"] == "Toyota Rent a Car · 2 days · one-way to Kyoto"
    assert s["items"][3]["subtitle"] == "2 nights · Kyoto"

    st = s["stats"]
    assert st["days"] == 8 and st["flights"] == 2 and st["rentals"] == 1 and st["stays"] == 1 and st["nights"] == 2
    assert st["drive_miles"] == 290
    assert 5100 < st["flight_miles"] - 5130 < 5200  # SFO-NRT by great circle + the stored 5130
    assert st["distance_miles"] == st["flight_miles"] + 290
    assert st["spend_text"] == "$300"  # whole dollars from $100 up and st["countries"] == 2
    assert [p["city"] for p in s["route"]] == ["San Francisco", "Tokyo", "Kyoto", "Tokyo", "San Francisco"]
    labels = [x["label"] for x in s["highlights"]]
    assert labels == ["Longest flight", "Longest drive", "Furthest from home", "Biggest spend"]
    assert s["highlights"][3]["value"] == "$240"


def test_story_edits_are_saved_per_user_and_survive_new_items(api, db):
    ana_t, ben_t = signup(api), signup(api, email="ben@example.com", name="Ben")
    ana, ben = bearer(ana_t), bearer(ben_t)
    tid = _trip_with_everything(api, db, ana, ana_t["user"]["id"])
    add_and_redeem(api, ana, tid, "Ben", "ben@example.com", ben)

    s = api.get(f"/trips/{tid}/story", headers=ana).json()
    keys = [i["key"] for i in s["items"]]
    assert keys[0] == "travelers" and s["items"][0]["title"] == "2 travelers"
    rental = next(k for k in keys if k.startswith("rental:"))
    new_order = [rental] + [k for k in keys if k != rental]
    r = api.put(f"/trips/{tid}/story", headers=ana, json={
        "title": "Spring in Japan", "theme": "sunset", "order": new_order + ["flight:9999"],
        "items": {rental: {"note": "  Snow on Fuji!  ", "photos": ["A1B2-C3", "A1B2-C3"]},
                  keys[1]: {"hidden": True}, "bogus:1": {"note": "x"}}})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["title"] == "Spring in Japan" and s["theme"] == "sunset" and s["edited"] is True
    assert s["items"][0]["key"] == rental
    assert s["items"][0]["note"] == "Snow on Fuji!" and s["items"][0]["photos"] == ["A1B2-C3"]
    assert next(i for i in s["items"] if i["key"] == keys[1])["hidden"] is True

    # Ben sees the generated story, not Ana's edits.
    b = api.get(f"/trips/{tid}/story", headers=ben).json()
    assert b["title"] == "Japan" and b["edited"] is False and [i["key"] for i in b["items"]] == keys

    # A new flight lands right after its chronological neighbour inside Ana's custom order.
    db.add(models.Flight(trip_id=tid, airline="JAL", flight_number="JL 1", departure_airport="NRT",
                         arrival_airport="KIX", departure_time=datetime(2026, 3, 5, 20)))
    db.commit()
    s = api.get(f"/trips/{tid}/story", headers=ana).json()
    order = [i["key"] for i in s["items"]]
    new_key = next(k for k in order if k not in keys)
    gen = [i["key"] for i in api.get(f"/trips/{tid}/story", headers=ben).json()["items"]]
    assert order[0] == rental and order[order.index(new_key) - 1] == gen[gen.index(new_key) - 1]
    assert s["title"] == "Spring in Japan"  # partial PUTs keep other fields
    api.put(f"/trips/{tid}/story", headers=ana, json={"subtitle": "with Ben"})
    s = api.get(f"/trips/{tid}/story", headers=ana).json()
    assert s["title"] == "Spring in Japan" and s["subtitle"] == "with Ben" and s["items"][0]["key"] == rental

    r = api.delete(f"/trips/{tid}/story", headers=ana)
    assert r.json()["title"] == "Japan" and r.json()["edited"] is False


def test_story_access_and_validation(api, db):
    ana, eve = bearer(signup(api)), bearer(signup(api, email="eve@example.com", name="Eve"))
    tid = api.post("/trips/", json={"title": "Solo"}, headers=ana).json()["id"]
    assert api.get(f"/trips/{tid}/story").status_code == 401
    assert api.get(f"/trips/{tid}/story", headers=eve).status_code == 404
    assert api.put(f"/trips/{tid}/story", headers=eve, json={"title": "mine"}).status_code == 404
    assert api.put(f"/trips/{tid}/story", headers=ana, json={"title": "x" * 81}).status_code == 422
    assert api.put(f"/trips/{tid}/story", headers=ana, json={"theme": "neon"}).status_code == 422
    assert api.put(f"/trips/{tid}/story", headers=ana,
                   json={"items": {"travelers": {"photos": ["../etc/passwd"]}}}).status_code == 422
    empty = api.get(f"/trips/{tid}/story", headers=ana).json()
    assert empty["items"] == [] and empty["stats"]["days"] is None and empty["route"] == []


def test_deleting_trip_or_account_removes_story(api, db):
    t = signup(api)
    ana = bearer(t)
    tid = api.post("/trips/", json={"title": "Gone"}, headers=ana).json()["id"]
    api.put(f"/trips/{tid}/story", headers=ana, json={"title": "Bye"})
    assert db.query(models.TripStory).count() == 1
    api.delete(f"/trips/{tid}", headers=ana)
    assert db.query(models.TripStory).count() == 0
    tid = api.post("/trips/", json={"title": "Kept"}, headers=ana).json()["id"]
    api.put(f"/trips/{tid}/story", headers=ana, json={"title": "Bye"})
    assert api.request("DELETE", "/me", headers=ana, json={"password": "correct horse 1"}).status_code == 204
    assert db.query(models.TripStory).count() == 0


def test_merge_order_places_new_keys_after_predecessor():
    # b follows a, d follows c (their chronological predecessors), wherever the user moved them.
    assert stories.merge_order(["a", "b", "c", "d"], ["c", "a"]) == ["c", "d", "a", "b"]
    assert stories.merge_order(["a", "b", "c"], ["c", "b", "a"]) == ["c", "b", "a"]
    assert stories.merge_order(["x", "a"], ["a"]) == ["x", "a"]
    assert stories.merge_order(["a", "b"], ["gone", "b"]) == ["a", "b"]


def test_year_in_travel(api, db):
    ana = signup(api, home_airport="SFO")
    h = bearer(ana)
    _trip_with_everything(api, db, h, ana["user"]["id"])
    other = api.post("/trips/", json={"title": "Old", "start_date": "2025-06-01T00:00:00",
                                      "end_date": "2025-06-03T00:00:00"}, headers=h).json()
    y = api.get("/stories/year?year=2026", headers=h).json()
    assert y["year"] == 2026 and y["trips"] == 1 and y["days_away"] == 8
    assert y["flights"] == 2 and y["rentals"] == 1 and y["drive_miles"] == 290
    assert y["countries"] == 2 and y["country_codes"] == ["JP", "US"]
    assert y["top_destinations"][0] == {"city": "Tokyo", "visits": 2}  # NRT arrival + Tokyo pickup
    assert y["top_airline"] in ("United", "ANA") and y["top_rental_company"] == "Toyota Rent a Car"
    assert y["longest_trip"] == {"title": "Japan", "days": 8}
    assert len(y["arcs"]) == 1 and y["arcs"][0]["count"] == 2  # SFO<->NRT both ways is one arc
    assert y["home"]["code"] == "SFO" and y["around_earth"] > 0.4
    assert api.get("/stories/year?year=2025", headers=h).json()["trips"] == 1
    assert other["id"]
    assert api.get("/stories/year?year=1800", headers=h).status_code == 422
    eve = bearer(signup(api, email="eve@example.com", name="Eve"))
    assert api.get("/stories/year?year=2026", headers=eve).json()["trips"] == 0


def test_story_migration_up_down(tmp_path):
    db = tmp_path / "s.db"
    alembic(db, "upgrade", "head")
    c = sqlite3.connect(db)
    cols = {r[1] for r in c.execute("PRAGMA table_info(trip_stories)")}
    assert cols >= {"trip_id", "user_id", "title", "order_json", "items_json", "theme", "cover_photo"}
    c.close()
    alembic(db, "downgrade", "d3a7c1e5f202")
    c = sqlite3.connect(db)
    assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='trip_stories'").fetchone()
    c.close()
    alembic(db, "upgrade", "head")


def test_rental_station_text_resolves_airport_codes():
    p = stories._rental_place(None, "LHR Airport", None, None, None)
    assert p["code"] == "LHR" and p["city"] == "London" and p["country"] == "GB"
    p = stories._rental_place(None, "Downtown Kyoto", "Kyoto", 35.0, 135.7)
    assert p == {"code": None, "city": "Kyoto", "country": "JP", "lat": 35.0, "lng": 135.7}  # nearest airport KIX/ITM
    assert stories._rental_place(None, "Somewhere", None, -60.0, -40.0)["country"] is None
    assert stories._rental_place(None, "", None, None, None) is None
