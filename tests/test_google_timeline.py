"""Google Maps Timeline → drives: both export formats (synthetic fixtures only), preview scoping,
commit + trip/journey matching, de-dupe, privacy, rental suggestions and cleanup."""
import base64
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from app.importers import google_timeline as gt
from app.importers.common import ImportError_

from test_importers import signup  # noqa: E402  (tests/ is on sys.path)
from test_migration import alembic  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "import"
ON_DEVICE = FIX / "google_timeline_on_device_synthetic.json"
IOS = FIX / "google_timeline_ios_synthetic.json"
TAKEOUT = FIX / "google_semantic_history_synthetic.json"


# --- parser ------------------------------------------------------------------------------------

@pytest.mark.parametrize("raw, want", [
    ("30.2672°, -97.7431°", (30.2672, -97.7431)),
    ("geo:30.267200,-97.743100", (30.2672, -97.7431)),
    ({"latLng": "1.5°, 2.5°"}, (1.5, 2.5)),
    ({"latitudeE7": 302672000, "longitudeE7": -977431000}, (30.2672, -97.7431)),
    ({"latE7": 10000000, "lngE7": 20000000}, (1.0, 2.0)),
    ("0°, 0°", None), ("91°, 0°", None), ("nonsense", None), (None, None),
])
def test_parse_latlng(raw, want):
    got = gt.parse_latlng(raw)
    assert (got and (round(got[0], 4), round(got[1], 4))) == want or got == want


def test_parse_time_zones_and_epoch():
    assert gt.parse_time("2024-05-03T08:15:00.123456789-05:00").utcoffset().total_seconds() == -5 * 3600
    assert gt.parse_time("2024-05-03T13:15:00Z").hour == 13
    assert gt.parse_time("1714743600000") == gt.parse_time("2024-05-03T13:40:00Z")
    assert gt.parse_time("yesterday") is None


def test_downsample_keeps_ends_and_caps_points():
    pts = [(30 + i / 1000, -97 - i / 1000) for i in range(1000)]
    out = gt.downsample(pts)
    assert len(out) == gt.MAX_PATH_POINTS and out[0] == [30.0, -97.0] and out[-1] == [30.999, -97.999]
    assert gt.downsample([(1, 2), (1, 2), (1, 2)]) == [[1, 2]]


def test_on_device_export_merges_stops_and_skips_walks_and_tiny_drives():
    items, stats = gt.parse_timeline(ON_DEVICE.read_bytes())
    assert stats["format"] == "on_device" and stats["drives"] == 3 and stats["skipped_short"] == 1
    day1 = items[0]["fields"]
    assert day1["start_time"] == datetime(2024, 5, 3, 8, 15) and day1["end_time"] == datetime(2024, 5, 3, 9, 20)
    assert day1["start_utc_offset"] == -300 and day1["distance_miles"] == 21.2 and day1["duration_minutes"] == 65
    assert day1["stops"] == [{"name": "Cafe", "lat": 30.39, "lng": -97.73, "minutes": 12}]
    assert day1["path"][0] == [30.2672, -97.7431] and day1["path"][-1] == [30.51, -97.82] and len(day1["path"]) >= 5
    assert day1["start_place"]["name"] == "Near Austin"  # "UNKNOWN" visit → nearest airport city
    assert items[2]["fields"]["start_utc_offset"] == -420  # the August drive is in Pacific time
    assert items[0]["summary"].startswith("May 3, 2024 · 08:15–09:20 · 21.2 mi")
    assert len({i["fields"]["external_id"] for i in items}) == 3


def test_ios_variant_is_a_top_level_list_with_geo_strings():
    items, stats = gt.parse_timeline(IOS.read_bytes())
    assert stats["format"] == "on_device" and len(items) == 1
    f = items[0]["fields"]
    assert f["distance_miles"] == 21.2 and f["stops"][0]["minutes"] == 12
    assert [30.3, -97.74] in f["path"]  # durationMinutesOffsetFromStartTime points
    # Same drive as the Android export → same id, so importing both doesn't double up.
    assert f["external_id"] == gt.parse_timeline(ON_DEVICE.read_bytes())[0][0]["fields"]["external_id"]


def test_takeout_semantic_history_is_utc_and_uses_the_given_zone():
    items, stats = gt.parse_timeline(TAKEOUT.read_bytes(), "America/Chicago")
    assert stats == {"format": "takeout", "segments": 7, "drives": 2, "skipped_short": 0, "timezone": "America/Chicago"}
    f = items[0]["fields"]
    assert f["start_time"] == datetime(2024, 5, 3, 8, 15) and f["start_utc_offset"] == -300
    assert f["start_place"]["name"] == "Example Hotel" and f["end_place"]["name"] == "Example State Park"
    assert f["stops"][0]["name"] == "Sample Coffee Co."
    assert items[0]["warnings"] and "UTC" in items[0]["warnings"][0]
    utc, _ = gt.parse_timeline(TAKEOUT.read_bytes(), "Not/AZone")
    assert utc[0]["fields"]["start_time"] == datetime(2024, 5, 3, 13, 15)


@pytest.mark.parametrize("data, msg", [
    (b"PK\x03\x04zip", "zip"),
    (json.dumps({"locations": []}).encode(), "Records.json"),
    (b"{not json", "doesn't look like"),
    (json.dumps({"hello": 1}).encode(), "doesn't look like"),
])
def test_bad_files(data, msg):
    with pytest.raises(ImportError_, match=msg):
        gt.parse_timeline(data)


# --- API ---------------------------------------------------------------------------------------

def preview(api, me, path=ON_DEVICE, **extra):
    body = {"source": "google_timeline", "data_base64": base64.b64encode(path.read_bytes()).decode(),
            "filename": path.name, **extra}
    r = api.post("/import/preview", headers=me, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def picked(body, only_suggested=True):
    return [{"kind": i["kind"], "fields": i["fields"]} for i in body["items"] if i["suggested"] or not only_suggested]


def make_trip(api, me, title="Texas", start="2024-05-02T00:00", end="2024-05-04T00:00"):
    return api.post("/trips/", headers=me, json={"title": title, "start_date": start, "end_date": end}).json()


def test_preview_scopes_to_trips_and_commit_matches_trip_and_journey(api):
    me = signup(api, "ana@example.com")
    trip = make_trip(api, me)
    journey = api.post("/journeys/", headers=me, json={"title": "Road trip", "trip_ids": [trip["id"]]}).json()
    body = preview(api, me)
    assert body["stats"]["outside_trips"] == 1 and body["stats"]["scope"] == "trips"
    assert len(body["items"]) == 2 and body["new_count"] == 2
    assert all(i["match"]["trip_id"] == trip["id"] and i["match"]["journey_id"] == journey["id"] for i in body["items"])
    everything = preview(api, me, drives_scope="all")
    assert len(everything["items"]) == 3 and [i["suggested"] for i in everything["items"]] == [True, True, False]

    done = api.post("/import/commit", headers=me, json={"items": picked(body)}).json()
    assert len(done["created"]) == 2 and {c["trip_id"] for c in done["created"]} == {trip["id"]}
    drives = api.get(f"/drives?trip_id={trip['id']}", headers=me).json()
    assert [d["distance_miles"] for d in drives] == [21.2, 32.3] and drives[0]["path"]
    assert len(api.get(f"/drives?journey_id={journey['id']}", headers=me).json()) == 2
    assert api.get("/drives?year=2023", headers=me).json() == []

    # Re-import (even the iOS copy of the same day) is all duplicates.
    again = preview(api, me)
    assert again["new_count"] == 0 and all(i["duplicate_of"] for i in again["items"])
    assert api.post("/import/commit", headers=me, json={"items": picked(again)}).json()["created"] == []
    assert preview(api, me, IOS)["new_count"] == 0


def test_takeout_preview_uses_device_timezone(api):
    me = signup(api, "ana@example.com")
    make_trip(api, me)
    body = preview(api, me, TAKEOUT, timezone="America/Chicago")
    assert body["stats"]["timezone"] == "America/Chicago"
    assert body["items"][0]["fields"]["start_time"] == "2024-05-03T08:15:00"


def test_drives_are_private(api):
    ana, ben = signup(api, "ana@example.com"), signup(api, "ben@example.com")
    trip = make_trip(api, ana)
    created = api.post("/import/commit", headers=ana, json={"items": picked(preview(api, ana))}).json()["created"]
    did = created[0]["id"]
    assert api.get("/drives", headers=ben).json() == []
    assert api.get(f"/drives/{did}", headers=ben).status_code == 404
    assert api.patch(f"/drives/{did}", headers=ben, json={"clear_trip": True}).status_code == 404
    assert api.delete(f"/drives/{did}", headers=ben).status_code == 404
    # Ben's preview of the same file isn't flagged as duplicates of Ana's drives.
    assert preview(api, ben, drives_scope="all")["new_count"] == 3
    ben_trip = make_trip(api, ben, "Ben's")
    assert api.patch(f"/drives/{did}", headers=ana, json={"trip_id": ben_trip["id"]}).status_code == 404


def test_commit_validates_drive_fields(api):
    me = signup(api, "ana@example.com")
    item = picked(preview(api, me, drives_scope="all"), only_suggested=False)[0]
    bad = json.loads(json.dumps(item))
    bad["fields"]["path"] = [[200, 1]]
    assert api.post("/import/commit", headers=me, json={"items": [bad]}).status_code == 400
    bad["fields"] = {**item["fields"], "external_id": ""}
    assert api.post("/import/commit", headers=me, json={"items": [bad]}).status_code == 400


def test_edit_unlink_delete_and_cleanup(api):
    me = signup(api, "ana@example.com")
    trip = make_trip(api, me)
    other = make_trip(api, me, "Other", "2025-01-01T00:00", "2025-01-02T00:00")
    ids = [c["id"] for c in api.post("/import/commit", headers=me,
                                     json={"items": picked(preview(api, me))}).json()["created"]]
    assert api.patch(f"/drives/{ids[0]}", headers=me, json={"trip_id": other["id"]}).json()["trip_id"] == other["id"]
    assert api.patch(f"/drives/{ids[0]}", headers=me, json={"clear_trip": True}).json()["trip_id"] is None
    assert api.delete(f"/drives/{ids[0]}", headers=me).status_code == 204
    assert api.get(f"/drives/{ids[0]}", headers=me).status_code == 404
    # Deleting a trip for good keeps your drives but unlinks them.
    assert api.delete(f"/trips/{trip['id']}", headers=me).status_code in (200, 204)
    assert api.delete(f"/trash/trips/{trip['id']}", headers=me).status_code == 204
    left = api.get("/drives", headers=me).json()
    assert len(left) == 1 and left[0]["trip_id"] is None


def test_delete_account_removes_drives(api, db):
    from app import models
    me = signup(api, "ana@example.com")
    api.post("/import/commit", headers=me, json={"items": picked(preview(api, me, drives_scope="all"), False)})
    assert db.query(models.Drive).count() == 3
    r = api.request("DELETE", "/me", headers=me, json={"password": "long enough 1"})
    assert r.status_code in (200, 204), r.text
    assert db.query(models.Drive).count() == 0


def test_rental_suggestions_link_and_dismiss(api):
    me = signup(api, "ana@example.com")
    trip = make_trip(api, me)
    rental = api.post(f"/trips/{trip['id']}/rental_cars/", headers=me, json={
        "rental_company": "Example Rent-a-Car", "pickup_location": "AUS", "dropoff_location": "AUS",
        "pickup_time": "2024-05-03T07:30", "dropoff_time": "2024-05-04T10:00"}).json()
    ids = [c["id"] for c in api.post("/import/commit", headers=me,
                                     json={"items": picked(preview(api, me))}).json()["created"]]
    sug = api.get("/drives/rental-suggestions", headers=me).json()
    assert {(s["drive_id"], s["match"]) for s in sug} == {(ids[0], "pickup"), (ids[1], "dropoff")}
    assert all(s["rental_id"] == rental["id"] for s in sug) and "min after pickup" in sug[0]["reason"]
    # Suggestions only: nothing is linked yet.
    assert all(d["rental_id"] is None for d in api.get("/drives", headers=me).json())
    assert api.post(f"/drives/{ids[0]}/rental", headers=me, json={"rental_id": rental["id"]}).json()["rental_id"] == rental["id"]
    assert api.post(f"/drives/{ids[1]}/rental/dismiss", headers=me, json={"rental_id": rental["id"]}).status_code == 204
    assert api.get("/drives/rental-suggestions", headers=me).json() == []
    # Someone else's rental can't be linked.
    ben = signup(api, "ben@example.com")
    ben_trip = make_trip(api, ben, "Ben's")
    ben_rental = api.post(f"/trips/{ben_trip['id']}/rental_cars/", headers=ben, json={
        "rental_company": "X", "pickup_location": "AUS", "dropoff_location": "AUS",
        "pickup_time": "2024-05-03T07:30", "dropoff_time": "2024-05-04T10:00"}).json()
    assert api.post(f"/drives/{ids[1]}/rental", headers=me, json={"rental_id": ben_rental["id"]}).status_code == 404
    # Deleting the rental unlinks the drive.
    api.delete(f"/rental_cars/{rental['id']}", headers=me)
    assert api.get(f"/drives/{ids[0]}", headers=me).json()["rental_id"] is None


def test_timeline_upload_limit_is_bigger_only_for_preview(api):
    from app import main
    me = signup(api, "ana@example.com")
    big = "x" * (main.MAX_BODY + 10)
    assert api.post("/trips/", headers=me, json={"title": big}).status_code == 413
    r = api.post("/import/preview", headers=me, json={"source": "google_timeline", "text": "[" + " " * (main.MAX_BODY + 10) + "]"})
    assert r.status_code == 400  # past the body cap, then a clean parser error


def test_migration_creates_drives(tmp_path):
    db = tmp_path / "m.db"
    alembic(db, "upgrade", "a7c4e2f9b318")
    alembic(db, "upgrade", "head")
    c = sqlite3.connect(db)
    cols = {r[1] for r in c.execute("PRAGMA table_info(drives)")}
    assert {"owner_id", "trip_id", "journey_id", "rental_id", "external_id", "path_json", "stops_json"} <= cols
    assert "uq_drives_owner_external" in {r[1] for r in c.execute("PRAGMA index_list(drives)")}
    c.close()
    alembic(db, "downgrade", "a7c4e2f9b318")
    alembic(db, "upgrade", "head")


# --- where drives show up ------------------------------------------------------------------------

def test_story_driving_days_and_miles_without_double_counting(api):
    me = signup(api, "ana@example.com")
    trip = make_trip(api, me)
    api.post("/import/commit", headers=me, json={"items": picked(preview(api, me))})
    story = api.get(f"/trips/{trip['id']}/story", headers=me).json()
    days = [i for i in story["items"] if i["kind"] == "drive"]
    assert [i["key"] for i in days] == ["drive:2024-05-03", "drive:2024-05-04"]
    d1 = days[0]
    assert d1["miles"] == 21.2 and d1["metric"] == "21 mi" and d1["paths"][0][0] == [30.2672, -97.7431]
    assert d1["stops"][0]["name"] == "Cafe" and "1 stop" in d1["subtitle"] and d1["day"] == 2
    assert story["stats"]["drive_miles"] == 54 and story["stats"]["drives"] == 2
    assert any(h["label"] == "Longest drive" for h in story["highlights"])
    assert any(p.get("city") == "Austin" for p in story["route"])
    # Hiding a driving day sticks like any other story item.
    api.put(f"/trips/{trip['id']}/story", headers=me, json={"items": {"drive:2024-05-03": {"hidden": True}}})
    again = api.get(f"/trips/{trip['id']}/story", headers=me).json()
    assert next(i for i in again["items"] if i["key"] == "drive:2024-05-03")["hidden"] is True

    # A rental with odometer miles over the same days: its miles count, the drives inside it don't.
    api.post(f"/trips/{trip['id']}/rental_cars/", headers=me, json={
        "rental_company": "Example Rent-a-Car", "pickup_location": "AUS", "dropoff_location": "AUS",
        "pickup_time": "2024-05-03T07:30", "dropoff_time": "2024-05-04T10:00", "mileage_driven": 60})
    st = api.get(f"/trips/{trip['id']}/story", headers=me).json()["stats"]
    assert st["drive_miles"] == 60 and st["timeline_miles"] == 54


def test_other_travelers_dont_see_your_drives_in_the_story(api, db):
    from app import models
    ana, ben = signup(api, "ana@example.com"), signup(api, "ben@example.com")
    trip = make_trip(api, ana)
    t = db.get(models.Trip, trip["id"])
    t.participants.append(db.query(models.User).filter_by(email="ben@example.com").one())
    db.commit()
    api.post("/import/commit", headers=ana, json={"items": picked(preview(api, ana))})
    ben_story = api.get(f"/trips/{trip['id']}/story", headers=ben).json()
    assert not [i for i in ben_story["items"] if i["kind"] == "drive"]
    assert api.get(f"/trips/{trip['id']}/story", headers=ana).json()["stats"]["drives"] == 2


def test_year_in_travel_adds_timeline_miles(api):
    me = signup(api, "ana@example.com")
    api.post("/import/commit", headers=me, json={"items": picked(preview(api, me, drives_scope="all"), False)})
    y = api.get("/stories/year?year=2024", headers=me).json()
    assert y["drives"] == 3 and y["timeline_drive_miles"] == 66 and y["drive_miles"] == 66 and y["miles"] == 66


def test_journey_shows_driving_days_including_between_legs(api):
    me = signup(api, "ana@example.com")
    a = make_trip(api, me, "Austin", "2024-04-30T00:00", "2024-05-02T00:00")
    b = make_trip(api, me, "Bay Area", "2024-08-19T00:00", "2024-08-21T00:00")
    j = api.post("/journeys/", headers=me, json={"title": "2024", "trip_ids": [a["id"], b["id"]]}).json()
    body = preview(api, me)
    assert len(body["items"]) == 3  # May 3 is a day after Austin (still matched); May 4 is only in the journey
    assert body["items"][1]["match"] == {"trip_id": None, "trip_title": None, "journey_id": j["id"], "journey_title": "2024"}
    api.post("/import/commit", headers=me, json={"items": picked(body)})
    d = api.get(f"/journeys/{j['id']}", headers=me).json()
    assert [i["key"] for i in d["drives"]] == ["drive:2024-05-03", "drive:2024-05-04", "drive:2024-08-20"]
    between = next(i for i in d["timeline"] if i["key"] == "drive:2024-05-04")
    assert between["leg"] is None and between["paths"]
    assert d["stats"]["drive_miles"] == 66
    s = api.get(f"/journeys/{j['id']}/story", headers=me).json()
    assert len([i for i in s["items"] if i["kind"] == "drive"]) == 3 and s["stats"]["drive_miles"] == 66
