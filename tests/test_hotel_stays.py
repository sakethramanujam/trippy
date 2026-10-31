"""Hotel stays: email templates (anonymized real layouts), the /lodgings API, trip spend, stats and stories."""
from datetime import datetime
from pathlib import Path

import pytest

from app.importers import hotel_templates as H
from app.importers.emails import parse_email
from tests.test_auth import bearer, signup

FIX = Path(__file__).parent / "fixtures" / "emails"


def stay(name):
    items, _ = parse_email((FIX / f"{name}.eml").read_bytes(), f"{name}.eml")
    assert len(items) == 1 and items[0]["kind"] == "lodging", items
    return items[0]["fields"] | {"_warn": items[0]["warnings"]}


def test_booking_com_confirmation_new_layout():
    f = stay("hotel_booking_confirmation")
    assert f["name"] == "Red Roof Inn Demo Springfield" and f["brand"] == "Red Roof"
    assert (f["check_in"], f["check_out"]) == (datetime(2031, 3, 27, 15), datetime(2031, 3, 31, 11))
    assert f["nights"] == 4 and f["cost"] == 412.50 and f["currency"] == "USD"
    assert f["confirmation_number"] == "4000000000000000001" and f["booking_source"] == "Booking.com"
    assert (f["city"], f["country"], f["check_in_tz"]) == ("Springfield", "US", "America/Chicago")
    assert f["external_id"] == "email:hotel:4000000000000000001:2031-03-27"


def test_booking_com_group_booking_flags_rooms_and_check_out_uses_until_time():
    f = stay("hotel_booking_confirmation_group")
    assert (f["rooms"], f["guests"], f["cost"], f["currency"], f["taxes_fees"]) == (3, 3, 330.0, "EUR", 19.43)
    assert f["check_out"] == datetime(2028, 9, 11, 12)
    assert (f["country"], f["check_in_tz"]) == ("DE", "Europe/Berlin")
    assert "Booking covers 3 rooms" in f["_warn"]


def test_booking_com_receipt_and_cancellation():
    r = stay("hotel_booking_receipt")
    assert (r["name"], r["cost"], r["nights"], r["brand"]) == ("Super 8 by Wyndham Demo Valley", 150.20, 2, "Wyndham")
    assert (r["city"], r["country"], r["check_in_tz"]) == ("Demo Valley", "US", "America/Denver")
    c = stay("hotel_booking_cancellation")
    assert c["status"] == "cancelled" and c["confirmation_number"] == "4100000004"
    assert "This booking was cancelled" in c["_warn"]


def test_airbnb_confirmation_and_receipt():
    c = stay("hotel_airbnb_confirmation")
    assert (c["name"], c["confirmation_number"], c["cost"], c["nights"]) == ("Sunny Demo Loft Near Downtown", "HMDEMO0001", 188.0, 2)
    assert c["property_type"] == "rental" and c["booking_source"] == "Airbnb" and c["address"] is None
    assert c["check_in"] == datetime(2027, 4, 14, 16)
    r = stay("hotel_airbnb_receipt")  # a changed reservation: the receipt carries the new dates and total
    assert (r["check_in"].date().isoformat(), r["nights"], r["cost"]) == ("2031-05-21", 2, 321.40)


def test_hotels_com_and_capital_one():
    h = stay("hotel_hotels_com")
    assert (h["brand"], h["booking_source"], h["cost"], h["taxes_fees"], h["guests"]) == ("IHG", "Hotels.com", 149.90, 12.32, 3)
    c = stay("hotel_capital_one")
    assert (c["brand"], c["booking_source"], c["cost"], c["rooms"], c["nights"]) == ("Hilton", "Capital One Travel", 702.15, 2, 3)
    assert c["check_in_tz"] == "America/Los_Angeles"


def test_folios_hilton_and_marriott():
    h = stay("hotel_folio_hilton")
    assert (h["name"], h["cost"], h["currency"], h["loyalty_program"]) == ("Hilton Garden Inn Demo Messe", 105.0, "EUR", "Hilton Honors")
    assert (h["check_in"], h["check_out"]) == (datetime(2028, 9, 16, 17, 38), datetime(2028, 9, 17, 9, 28))
    assert h["city"] == "Demostadt" and h["country"] == "DE"
    m = stay("hotel_folio_marriott")
    assert (m["name"], m["brand"], m["cost"], m["nights"], m["taxes_fees"]) == ("Aloft Demo Airport", "Marriott", 277.10, 2, 39.92)
    assert m["loyalty_program"] == "Marriott Bonvoy" and m["city"] == "Springfield"


def test_no_loyalty_member_numbers_are_kept():
    for p in FIX.glob("hotel_*.eml"):
        items, _ = parse_email(p.read_bytes(), p.name)
        for i in items:
            assert not [k for k in i["fields"] if "member" in k or "loyalty_number" in k]


@pytest.mark.parametrize("addr,city,country", [
    ("1 North Road, Salt Lake City (Utah), United States of America, UT 84116", "Salt Lake City", "US"),
    ("10 Ocean Boulevard, Manhattan Beach, CA 90266, United", "Manhattan Beach", "US"),
    ("Demostraße 2, 10000 Neustadt, Germany", "Neustadt", "Germany"),
    (None, None, None),
])
def test_split_address(addr, city, country):
    assert H.split_address(addr) == (city, country)


def test_brand_and_tz_guess():
    assert H.brand_of("Moxy Demo Airport") == "Marriott"
    assert H.brand_of("SureStay Plus Hotel by Best Western") == "Best Western"
    assert H.brand_of("Gasthof Demo") is None
    assert H.guess_tz("1 Main St, Moab, UT 84532, United States", "US") == "America/Denver"
    assert H.guess_tz("Rue 1, Waterloo, Belgium", "Belgium") == "Europe/Brussels"
    assert H.guess_tz("somewhere", None) is None


# ------------------------------------------------------------------ API

STAY = {"name": "Demo Inn", "address": "1 Main St, Springfield, TX 78701, United States", "check_in": "2031-03-27T15:00:00",
        "check_out": "2031-03-30T11:00:00", "confirmation_number": "DEMO1", "cost": 300.0, "currency": "USD",
        "booking_source": "Booking.com", "brand": "Demo Hotels", "city": "Springfield", "country": "US",
        "check_in_tz": "America/Chicago", "check_out_tz": "America/Chicago", "rooms": 1, "guests": 2,
        "room_type": "King", "taxes_fees": 30.0, "loyalty_program": "Demo Rewards", "loyalty_points": 1200}


def _trip(api, h, title="Texas", start="2031-03-26T00:00:00", end="2031-04-01T00:00:00"):
    return api.post("/trips/", headers=h, json={"title": title, "start_date": start, "end_date": end}).json()


def test_lodging_crud_is_per_user(api):
    ana, ben = bearer(signup(api, "ana@example.com")), bearer(signup(api, "ben@example.com"))
    trip = _trip(api, ana)
    r = api.post(f"/trips/{trip['id']}/lodgings/", headers=ana, json=STAY)
    assert r.status_code == 200, r.text
    lid = r.json()["id"]
    got = api.get(f"/lodgings/{lid}", headers=ana).json()
    assert got["night_count"] == 3 and got["stay_status"] == "booked" and got["trip_id"] == trip["id"]
    assert got["loyalty_points"] == 1200 and got["check_in_tz"] == "America/Chicago"
    # Ben can't see, change or delete Ana's stay, or add one to her trip.
    assert api.get(f"/lodgings/{lid}", headers=ben).status_code == 404
    assert api.patch(f"/lodgings/{lid}", headers=ben, json={"name": "x"}).status_code == 404
    assert api.delete(f"/lodgings/{lid}", headers=ben).status_code == 404
    assert api.post(f"/trips/{trip['id']}/lodgings/", headers=ben, json=STAY).status_code == 404
    assert api.get("/lodgings/", headers=ben).json() == []
    # Partial update and filters
    p = api.patch(f"/lodgings/{lid}", headers=ana, json={"status": "cancelled", "room_type": "Queen"}).json()
    assert (p["status"], p["stay_status"], p["room_type"], p["name"]) == ("cancelled", "cancelled", "Queen", "Demo Inn")
    assert [l["id"] for l in api.get("/lodgings/?status=cancelled", headers=ana).json()] == [lid]
    assert api.get("/lodgings/?year=2030", headers=ana).json() == []
    assert len(api.get("/lodgings/?year=2031&brand=Demo Hotels", headers=ana).json()) == 1
    assert api.delete(f"/lodgings/{lid}", headers=ana).status_code == 204
    assert api.get(f"/lodgings/{lid}", headers=ana).status_code == 404


def test_standalone_stay_and_external_upsert(api):
    ana, ben = bearer(signup(api, "ana@example.com")), bearer(signup(api, "ben@example.com"))
    ben_trip = _trip(api, ben)
    assert api.post("/lodgings/", headers=ana, json=STAY | {"trip_id": ben_trip["id"]}).status_code == 404
    solo = api.post("/lodgings/", headers=ana, json=STAY).json()
    assert solo["trip_id"] is None
    ext = "email:hotel:DEMO2:2031-05-01"
    a = api.put(f"/lodgings/external/{ext}", headers=ana, json=STAY | {"cost": 100}).json()
    b = api.put(f"/lodgings/external/{ext}", headers=ana, json=STAY | {"cost": 120}).json()
    assert a["id"] == b["id"] and b["cost"] == 120 and b["external_id"] == ext
    assert len(api.get("/lodgings/", headers=ana).json()) == 2


def test_trip_detail_spend_stats_and_story_include_stays(api):
    h = bearer(signup(api, "ana@example.com"))
    trip = _trip(api, h)
    api.post(f"/trips/{trip['id']}/lodgings/", headers=h, json=STAY)
    api.post(f"/trips/{trip['id']}/lodgings/", headers=h, json=STAY | {"name": "Euro Inn", "cost": 90, "currency": "EUR",
                                                                     "confirmation_number": "DEMO3", "brand": None})
    api.post(f"/trips/{trip['id']}/lodgings/", headers=h, json=STAY | {"name": "Gone Inn", "status": "cancelled",
                                                                     "confirmation_number": "DEMO4"})
    t = api.get(f"/trips/{trip['id']}", headers=h).json()
    assert len(t["lodgings"]) == 3
    assert t["stay_cost_by_currency"] == {"USD": 300.0, "EUR": 90.0}  # cancelled stays don't count
    stays = api.get("/stats/?year=2031", headers=h).json()["stays"]
    assert stays["count"] == 2 and stays["nights"] == 6
    assert stays["total_cost_by_currency"] == {"USD": 300.0, "EUR": 90.0}
    assert stays["top_booking_sources"][0]["name"] == "Booking.com" and stays["cities"] == 1
    s = api.get(f"/trips/{trip['id']}/story", headers=h).json()
    names = [i.get("title") for i in s["items"] if i["kind"] == "lodging"]
    assert "Gone Inn" not in " ".join(map(str, names)) and len(names) == 2
    assert s["stats"]["stays"] == 2 and s["stats"]["stay_spend"] == {"USD": 300.0, "EUR": 90.0}


def test_email_import_of_hotel_via_api(api):
    h = bearer(signup(api, "ana@example.com"))
    trip = _trip(api, h)
    text = (FIX / "hotel_booking_confirmation.eml").read_text()
    prev = api.post("/import/preview", headers=h, json={"source": "email", "text": text}).json()
    assert [i["kind"] for i in prev["items"]] == ["lodging"]
    done = api.post("/import/commit", headers=h, json={"items": [{"kind": "lodging", "fields": prev["items"][0]["fields"]}]}).json()
    assert done["created"][0]["trip_id"] == trip["id"]
    again = api.post("/import/preview", headers=h, json={"source": "email", "text": text}).json()
    assert again["items"][0]["duplicate_of"]["id"] == done["created"][0]["id"]
    l = api.get("/lodgings/", headers=h).json()[0]
    assert (l["brand"], l["nights"], l["city"], l["external_id"]) == ("Red Roof", 4, "Springfield", "email:hotel:4000000000000000001:2031-03-27")
