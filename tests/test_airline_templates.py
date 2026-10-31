"""Real airline email layouts, anonymized (names, codes, prices, years and ticket numbers replaced)."""
from datetime import datetime
from pathlib import Path

import pytest

from app.importers.emails import parse_email

FIX = Path(__file__).parent / "fixtures" / "emails"


def flights(name):
    items, _ = parse_email((FIX / f"{name}.eml").read_bytes(), f"{name}.eml")
    assert items and all(i["kind"] == "flight" for i in items)
    return [i["fields"] | {"_conf": i["confidence"], "_warn": i["warnings"]} for i in items]


def route(fs):
    return [(f["flight_number"], f["departure_airport"], f["arrival_airport"],
             f["departure_time"].strftime("%Y-%m-%d %H:%M"), f["arrival_time"].strftime("%Y-%m-%d %H:%M")) for f in fs]


def test_alaska_receipt_crosses_midnight_and_infers_year():
    fs = flights("alaska_receipt")
    assert route(fs) == [("AS 1562", "LAX", "ANC", "2031-06-12 19:55", "2031-06-13 00:22"),
                         ("AS 1563", "ANC", "LAX", "2031-06-21 23:18", "2031-06-22 05:40")]
    assert {f["confirmation_number"] for f in fs} == {"QXALAS"}
    assert fs[0]["cost"] == 211.40 and fs[1]["cost"] is None  # booking total on the first flight only
    assert fs[0]["_conf"] == "high"


def test_delta_time_change_uses_new_times_not_old():
    fs = flights("delta_time_change")
    assert route(fs) == [("DL 381", "SFO", "AUS", "2030-07-29 13:58", "2030-07-29 19:41"),
                         ("AA 7421", "AUS", "SFO", "2030-07-30 16:11", "2030-07-30 17:57")]
    assert fs[0]["confirmation_number"] == "DLTEST"


def test_united_receipt():
    fs = flights("united_receipt")
    assert route(fs) == [("UA 573", "SFO", "DEN", "2031-11-12 20:23", "2031-11-12 23:59"),
                         ("UA 2123", "DEN", "SFO", "2031-11-17 21:18", "2031-11-17 23:09")]
    assert fs[0]["cost"] == 250.00 and fs[0]["currency"] == "USD" and fs[0]["cabin_class"] == "economy"


def test_frontier_confirmation():
    fs = flights("frontier_confirmation")
    assert route(fs) == [("F9 1230", "SFO", "DEN", "2031-05-20 06:00", "2031-05-20 09:52"),
                         ("F9 1093", "DEN", "SFO", "2031-05-27 06:05", "2031-05-27 08:01")]
    assert fs[0]["confirmation_number"] == "F9DEMO" and fs[0]["cost"] == 99.96


def test_capital_one_delta_uses_airline_code():
    fs = flights("capital_one_delta")
    assert [f["flight_number"] for f in fs] == ["DL 1088", "DL 1464", "DL 3798", "DL 1091"]
    assert route(fs)[1][3:] == ("2030-08-30 21:30", "2030-08-30 23:10")
    assert route(fs)[3][3:] == ("2030-09-03 21:45", "2030-09-03 22:51")
    assert {f["confirmation_number"] for f in fs} == {"DLDEMO"}


def test_bcd_southwest_receipt():
    fs = flights("bcd_southwest_receipt")
    assert route(fs) == [("WN 2039", "PHX", "SJC", "2027-01-07 10:10", "2027-01-07 11:15")]
    assert fs[0]["confirmation_number"] == "WNTEST" and fs[0]["cost"] == 150.25


def test_external_ids_are_stable_per_flight():
    a = [f["external_id"] for f in flights("united_receipt")]
    assert a == [f["external_id"] for f in flights("united_receipt")] and len(set(a)) == 2


def test_same_flight_number_two_legs_same_day_are_not_duplicates(api):
    r = api.post("/auth/signup", json={"email": "leg@example.com", "password": "long enough 1", "name": "leg"})
    me = {"Authorization": f"Bearer {r.json()['access_token']}"}
    legs = [{"kind": "flight", "fields": {"airline": "United", "flight_number": "UA 1924", "departure_airport": a,
             "arrival_airport": b, "departure_time": d, "arrival_time": e}}
            for a, b, d, e in [("SJC", "DEN", "2031-08-14T18:37:00", "2031-08-14T22:15:00"),
                               ("DEN", "IAD", "2031-08-14T23:59:00", "2031-08-15T05:25:00")]]
    r = api.post("/import/commit", json={"items": legs, "auto_trip": False}, headers=me)
    assert r.status_code == 200, r.text
    assert len(r.json()["created"]) == 2
    again = api.post("/import/commit", json={"items": legs, "auto_trip": False}, headers=me).json()
    assert again["created"] == [] and len(again["skipped"]) == 2
