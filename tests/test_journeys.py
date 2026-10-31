"""Journeys: link/unlink trips, merge, move items, suggestions, and who can see what."""
from datetime import datetime as dt

import pytest

from app import models, money


def _user(db, name):
    u = models.User(username=name, email=f"{name}@t.local", hashed_password="x", home_airport="SFO")
    db.add(u)
    db.commit()
    return u


def _trip(db, owner, title, start, end, flights=(), stays=(), rentals=()):
    t = models.Trip(title=title, owner_id=owner.id, start_date=start, end_date=end)
    db.add(t)
    db.flush()
    for dep, arr, when in flights:
        db.add(models.Flight(trip_id=t.id, owner_id=owner.id, airline="UA", flight_number="UA 1",
                             departure_airport=dep, arrival_airport=arr, departure_time=when,
                             arrival_time=when.replace(hour=min(when.hour + 3, 23)), cost=200.0))
    for name, city, cin, cout in stays:
        db.add(models.Lodging(trip_id=t.id, owner_id=owner.id, name=name, city=city, check_in=cin, check_out=cout,
                              nights=(cout - cin).days, cost=100.0 * (cout - cin).days))
    for pick, drop, when, back in rentals:
        db.add(models.RentalCar(trip_id=t.id, owner_id=owner.id, rental_company="Hertz", pickup_location=pick,
                                dropoff_location=drop, pickup_code=pick, dropoff_code=drop,
                                pickup_time=when, dropoff_time=back))
    db.commit()
    return t


@pytest.fixture()
def world(db):
    """Ana's Europe trip in three pieces, a trip home in between something else, and Ben's own trip."""
    ana, ben, cy = _user(db, "ana"), _user(db, "ben"), _user(db, "cy")
    lis = _trip(db, ana, "Lisbon", dt(2026, 5, 1), dt(2026, 5, 5),
                flights=[("SFO", "LIS", dt(2026, 5, 1, 8))], stays=[("Memmo", "Lisbon", dt(2026, 5, 1), dt(2026, 5, 5))])
    por = _trip(db, ana, "Porto", dt(2026, 5, 5), dt(2026, 5, 8),
                rentals=[("LIS", "OPO", dt(2026, 5, 5, 9), dt(2026, 5, 5, 15))],
                stays=[("Torel", "Porto", dt(2026, 5, 5), dt(2026, 5, 8))])
    mad = _trip(db, ana, "Madrid", dt(2026, 5, 9), dt(2026, 5, 12),
                flights=[("OPO", "MAD", dt(2026, 5, 9, 10)), ("MAD", "SFO", dt(2026, 5, 12, 12))])
    den = _trip(db, ana, "Denver", dt(2026, 5, 13), dt(2026, 5, 15), flights=[("SFO", "DEN", dt(2026, 5, 13, 8))])
    bens = _trip(db, ben, "Ben's Rome", dt(2026, 5, 2), dt(2026, 5, 6), flights=[("SFO", "FCO", dt(2026, 5, 2, 8))])
    por.participants.append(cy)
    db.commit()
    return {"ana": ana, "ben": ben, "cy": cy, "lis": lis.id, "por": por.id, "mad": mad.id, "den": den.id,
            "bens": bens.id}


def test_link_detail_and_unlink_keeps_trips(client, db, world):
    client.acting_as = world["ana"].id
    r = client.post("/journeys/", json={"trip_ids": [world["mad"], world["lis"], world["por"]]})
    assert r.status_code == 201, r.text
    j = r.json()
    assert j["title"] == "Lisbon → Porto → Madrid"  # prefilled from places, home left out
    assert j["trip_ids"] == [world["lis"], world["por"], world["mad"]]  # by date
    assert j["stats"]["days"] == 12 and j["stats"]["flights"] == 3 and j["stats"]["nights"] == 7
    assert j["stats"]["miles"] > 5000
    assert j["cost_by_currency"] == {"USD": 1300.0}  # 3 flights × 200 + 7 nights × 100
    assert [l["leg"] for l in j["legs"]] == [1, 2, 3]
    assert {i["trip_id"] for i in j["timeline"]} == {world["lis"], world["por"], world["mad"]}
    assert [i["leg"] for i in j["timeline"]] == sorted(i["leg"] for i in j["timeline"])  # grouped by leg
    assert j["route"][0]["code"] == "SFO" and j["route"][-1]["code"] == "SFO"
    jid = j["id"]
    assert client.get(f"/trips/{world['lis']}").json()["journey_id"] == jid
    assert [x["id"] for x in client.get("/journeys/").json()] == [jid]

    r = client.delete(f"/journeys/{jid}/trips/{world['por']}")
    assert r.json()["trip_ids"] == [world["lis"], world["mad"]]
    por = client.get(f"/trips/{world['por']}").json()
    assert por["journey_id"] is None and len(por["lodgings"]) == 1 and len(por["rental_cars"]) == 1

    r = client.delete(f"/journeys/{jid}")
    assert r.json()["unlinked_trip_ids"] == [world["lis"], world["mad"]]
    assert client.get(f"/journeys/{jid}").status_code == 404
    lis = client.get(f"/trips/{world['lis']}").json()
    assert lis["journey_id"] is None and len(lis["flights"]) == 1 and len(lis["lodgings"]) == 1


def test_add_trip_and_reorder(client, db, world):
    client.acting_as = world["ana"].id
    jid = client.post("/journeys/", json={"title": "Iberia", "trip_ids": [world["lis"]]}).json()["id"]
    j = client.post(f"/journeys/{jid}/trips", json={"trip_ids": [world["mad"], world["por"]]}).json()
    assert j["title"] == "Iberia" and j["trip_ids"] == [world["lis"], world["por"], world["mad"]]
    j = client.put(f"/journeys/{jid}/order", json={"trip_ids": [world["mad"], world["lis"], world["por"]]}).json()
    assert j["trip_ids"] == [world["mad"], world["lis"], world["por"]]
    assert client.put(f"/journeys/{jid}/order", json={"trip_ids": [world["mad"]]}).status_code == 400
    assert client.patch(f"/journeys/{jid}", json={"title": "Spain & Portugal"}).json()["title"] == "Spain & Portugal"
    # A trip in another journey moves over.
    other = client.post("/journeys/", json={"trip_ids": [world["den"]]}).json()["id"]
    client.post(f"/journeys/{other}/trips", json={"trip_ids": [world["lis"]]})
    assert world["lis"] not in client.get(f"/journeys/{jid}").json()["trip_ids"]
    story = client.get(f"/journeys/{other}/story").json()
    assert story["journey_id"] == other and story["stats"]["flights"] == 2


def test_scoping(client, db, world):
    client.acting_as = world["ben"].id
    # Can't link someone else's trip, even into your own journey.
    assert client.post("/journeys/", json={"trip_ids": [world["lis"]]}).status_code == 404
    client.acting_as = world["ana"].id
    jid = client.post("/journeys/", json={"trip_ids": [world["lis"], world["por"]]}).json()["id"]
    assert client.post(f"/journeys/{jid}/trips", json={"trip_ids": [world["bens"]]}).status_code == 404
    client.acting_as = world["ben"].id
    assert client.get(f"/journeys/{jid}").status_code == 404
    assert client.get("/journeys/").json() == []
    assert client.delete(f"/journeys/{jid}").status_code == 404
    # Cy travels on Porto only: sees the journey with just that leg, read-only.
    client.acting_as = world["cy"].id
    j = client.get(f"/journeys/{jid}").json()
    assert j["trip_ids"] == [world["por"]] and j["is_owner"] is False
    assert client.patch(f"/journeys/{jid}", json={"title": "x"}).status_code == 403
    assert client.delete(f"/journeys/{jid}/trips/{world['por']}").status_code == 403
    assert client.post(f"/trips/{world['por']}/merge", json={"source_trip_id": world["lis"], "confirm": True}).status_code in (403, 404)


def test_merge_moves_everything(client, db, world):
    client.acting_as = world["ana"].id
    ana, cy = world["ana"], world["cy"]
    money.create_expense(db, amount=90, description="Port tasting", payer_id=cy.id, split_among=[ana.id, cy.id],
                         trip_id=world["por"])
    jid = client.post("/journeys/", json={"trip_ids": [world["por"], world["mad"]]}).json()["id"]
    r = client.post(f"/trips/{world['lis']}/merge", json={"source_trip_id": world["por"]})
    assert r.status_code == 400  # needs confirm
    r = client.post(f"/trips/{world['lis']}/merge", json={"source_trip_id": world["por"], "confirm": True})
    assert r.status_code == 200, r.text
    t = r.json()
    assert len(t["lodgings"]) == 2 and len(t["rental_cars"]) == 1 and len(t["expenses"]) == 1
    assert {p["id"] for p in t["participants"]} == {cy.id}
    assert t["journey_id"] == jid  # inherited from the merged trip
    assert t["start_date"].startswith("2026-05-01") and t["end_date"].startswith("2026-05-08")
    assert client.get(f"/trips/{world['por']}").status_code == 404
    led = client.get(f"/trips/{world['lis']}/ledger").json()
    assert led["total_cents"] == 9000


def test_move_items(client, db, world):
    client.acting_as = world["ana"].id
    ana, cy = world["ana"], world["cy"]
    por = db.get(models.Trip, world["por"])
    stay = por.lodgings[0].id
    rental = por.rental_cars[0].id
    flight = db.get(models.Trip, world["mad"]).flights[0].id
    e = money.create_expense(db, amount=40, description="Tram", payer_id=cy.id, split_among=[ana.id, cy.id],
                             trip_id=world["por"])
    r = client.post("/items/move", json={"trip_id": world["lis"], "items": [
        {"kind": "stay", "id": stay}, {"kind": "rental", "id": rental}, {"kind": "flight", "id": flight},
        {"kind": "expense", "id": e.id}]})
    assert r.status_code == 200, r.text
    assert r.json()["added_traveler_ids"] == [cy.id]  # the expense's people join the target trip
    lis = client.get(f"/trips/{world['lis']}").json()
    assert len(lis["lodgings"]) == 2 and len(lis["rental_cars"]) == 1 and len(lis["flights"]) == 2
    assert lis["end_date"].startswith("2026-05-09")  # widened to fit the moved flight
    # All or nothing: one bad id moves nothing.
    r = client.post("/items/move", json={"trip_id": world["den"], "items": [
        {"kind": "stay", "id": stay}, {"kind": "flight", "id": 99999}]})
    assert r.status_code == 404
    assert db.get(models.Lodging, stay).trip_id == world["lis"]
    # Off a trip entirely (not allowed for expenses).
    assert client.post("/items/move", json={"trip_id": None, "items": [{"kind": "rental", "id": rental}]}).status_code == 200
    assert db.get(models.RentalCar, rental).trip_id is None
    assert client.post("/items/move", json={"trip_id": None, "items": [{"kind": "expense", "id": e.id}]}).status_code == 400
    # Someone else's items or trips: 404.
    client.acting_as = world["ben"].id
    assert client.post("/items/move", json={"trip_id": world["bens"], "items": [{"kind": "stay", "id": stay}]}).status_code == 404
    client.acting_as = world["ana"].id
    assert client.post("/items/move", json={"trip_id": world["bens"], "items": [{"kind": "stay", "id": stay}]}).status_code == 404


def test_suggestions(client, db, world):
    client.acting_as = world["ana"].id
    s = client.get("/journeys/suggestions").json()["suggestions"]
    assert len(s) == 1
    top = s[0]
    assert top["trip_ids"] == [world["lis"], world["por"], world["mad"]]  # Denver comes after a flight home
    assert any("Lisbon" in r for r in top["reasons"])
    assert top["title"] == "Lisbon → Porto → Madrid"
    # Ben's overlapping Rome trip never shows up for Ana, and nothing is applied.
    assert client.get(f"/trips/{world['lis']}").json()["journey_id"] is None
    assert client.post("/journeys/suggestions/dismiss", json={"trip_ids": top["trip_ids"]}).status_code == 200
    assert client.get("/journeys/suggestions").json()["suggestions"] == []
    assert len(client.get("/journeys/suggestions?include_dismissed=true").json()["suggestions"]) == 1
    client.acting_as = world["ben"].id
    assert client.post("/journeys/suggestions/dismiss", json={"trip_ids": [world["lis"]]}).status_code == 404


def test_suggestions_skip_linked_and_overlap_without_place(client, db, world):
    client.acting_as = world["ana"].id
    client.post("/journeys/", json={"trip_ids": [world["lis"], world["por"], world["mad"]]})
    assert client.get("/journeys/suggestions").json()["suggestions"] == []
    # Two trips that overlap but share no place (Tokyo vs Denver) aren't suggested.
    ana = world["ana"]
    _trip(db, ana, "Tokyo", dt(2026, 11, 1), dt(2026, 11, 10), flights=[("SFO", "NRT", dt(2026, 11, 1, 8))])
    _trip(db, ana, "Denver2", dt(2026, 11, 5), dt(2026, 11, 7), flights=[("SFO", "DEN", dt(2026, 11, 5, 8))])
    assert client.get("/journeys/suggestions").json()["suggestions"] == []


def test_suggestion_note_for_one_trip_loop(client, db, world):
    """Trip 47 shape: drive SFO→LAX, fly LAX→ANC→PHX→SFO, titled after the first leg only."""
    client.acting_as = world["ana"].id
    t = _trip(db, world["ana"], "San Francisco → Los Angeles (auto)", dt(2026, 6, 11), dt(2026, 6, 21),
              rentals=[("SFO", "LAX", dt(2026, 6, 11, 19), dt(2026, 6, 12, 9))],
              flights=[("LAX", "ANC", dt(2026, 6, 12, 19)), ("ANC", "PHX", dt(2026, 6, 20, 20)),
                       ("PHX", "SFO", dt(2026, 6, 21, 10))])
    notes = client.get("/journeys/suggestions").json()["notes"]
    n = next(n for n in notes if n["trip_id"] == t.id)
    assert "SFO → LAX → ANC → PHX → SFO" in n["note"]
    assert n["suggested_title"] == "Los Angeles → Anchorage → Phoenix"
