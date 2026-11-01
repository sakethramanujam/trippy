"""Trip photos: thumbnails only, private to whoever added them, gone with the trip."""
import base64
import sqlite3

from app import photos

from test_importers import signup  # noqa: E402
from test_migration import alembic  # noqa: E402


def jpeg(w=320, h=240, pad=0) -> bytes:
    """A tiny synthetic JPEG header (SOI, APP0, SOF0, EOI) — enough for the size check."""
    app0 = b"\xff\xe0" + (16).to_bytes(2, "big") + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = b"\xff\xc0" + (17).to_bytes(2, "big") + b"\x08" + h.to_bytes(2, "big") + w.to_bytes(2, "big") + b"\x03" + b"\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    return b"\xff\xd8" + app0 + sof + b"\x00" * pad + b"\xff\xd9"


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def trip(api, me, start="2024-05-02T00:00", end="2024-05-05T00:00"):
    return api.post("/trips/", headers=me, json={"title": "Texas", "start_date": start, "end_date": end}).json()


def body(asset="IMG_0001", taken="2024-05-03T10:00:00", **kw):
    return {"device_id": "dev-a", "asset_id": asset, "taken_at": taken, "lat": 30.27, "lng": -97.74,
            "thumb_base64": b64(jpeg()), **kw}


def test_jpeg_size_reads_frame_header():
    assert photos.jpeg_size(jpeg(512, 384)) == (512, 384)
    assert photos.jpeg_size(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20) is None
    assert photos.jpeg_size(b"\xff\xd8\xff\xd9") is None


def test_add_list_thumb_dedupe_and_delete(api):
    me = signup(api, "ana@example.com")
    t = trip(api, me)
    r = api.post(f"/trips/{t['id']}/photos", headers=me, json=body())
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["width"] == 320 and p["thumb_url"] == f"/photos/{p['id']}/thumb" and "thumb" not in p
    # Same asset from the same device replaces, not duplicates; a re-add without GPS keeps the known location.
    again = api.post(f"/trips/{t['id']}/photos", headers=me, json=body(lat=None, lng=None))
    assert again.status_code == 200 and again.json()["id"] == p["id"] and again.json()["lat"] == p["lat"] is not None
    moved = api.post(f"/trips/{t['id']}/photos", headers=me, json=body(lat=10.5, lng=20.25))
    assert moved.json()["lat"] == 10.5 and moved.json()["lng"] == 20.25
    api.post(f"/trips/{t['id']}/photos", headers=me, json=body("IMG_0002", device_id="dev-b"))
    assert len(api.get(f"/trips/{t['id']}/photos", headers=me).json()) == 2
    assert len(api.get(f"/trips/{t['id']}/photos?device_id=dev-b", headers=me).json()) == 1
    th = api.get(p["thumb_url"], headers=me)
    assert th.status_code == 200 and th.headers["content-type"] == "image/jpeg" and th.content == jpeg()
    assert api.delete(f"/photos/{p['id']}", headers=me).status_code == 204
    assert api.get(p["thumb_url"], headers=me).status_code == 404


def test_rejects_big_or_non_jpeg_thumbnails(api):
    me = signup(api, "ana@example.com")
    t = trip(api, me)
    url = f"/trips/{t['id']}/photos"
    assert api.post(url, headers=me, json=body(thumb_base64=b64(jpeg(1024, 768)))).status_code == 422
    assert api.post(url, headers=me, json=body(thumb_base64=b64(b"\x89PNG" + b"\x00" * 64))).status_code == 422
    assert api.post(url, headers=me, json=body(thumb_base64="not base64!")).status_code == 422
    assert api.post(url, headers=me, json=body(thumb_base64=b64(jpeg(pad=photos.MAX_BYTES)))).status_code in (413, 422)
    assert api.post(url, headers=me, json=body(lat=200)).status_code == 422


def test_photos_are_private_to_whoever_added_them(api, db):
    from app import models
    ana, ben = signup(api, "ana@example.com"), signup(api, "ben@example.com")
    t = trip(api, ana)
    p = api.post(f"/trips/{t['id']}/photos", headers=ana, json=body()).json()
    assert api.get(f"/trips/{t['id']}/photos", headers=ben).status_code == 404  # not on the trip
    assert api.post(f"/trips/{t['id']}/photos", headers=ben, json=body()).status_code == 404
    tr = db.get(models.Trip, t["id"])
    tr.participants.append(db.query(models.User).filter_by(email="ben@example.com").one())
    db.commit()
    assert api.get(f"/trips/{t['id']}/photos", headers=ben).json() == []
    assert api.get(p["thumb_url"], headers=ben).status_code == 404
    assert api.delete(f"/photos/{p['id']}", headers=ben).status_code == 404
    # Ben adds his own and then leaves: his go, Ana's stay.
    api.post(f"/trips/{t['id']}/photos", headers=ben, json=body("B1"))
    assert api.post(f"/trips/{t['id']}/leave", headers=ben).status_code == 204
    assert db.query(models.TripPhoto).filter_by(trip_id=t["id"]).count() == 1


def test_story_places_photos_on_days(api):
    me = signup(api, "ana@example.com")
    t = trip(api, me)
    api.post(f"/trips/{t['id']}/flights/", headers=me, json={
        "airline": "Example Air", "flight_number": "EX12", "departure_airport": "SFO", "arrival_airport": "AUS",
        "departure_time": "2024-05-03T08:00", "arrival_time": "2024-05-03T14:00"})
    api.post(f"/trips/{t['id']}/photos", headers=me, json=body("A", "2024-05-03T16:00:00"))
    api.post(f"/trips/{t['id']}/photos", headers=me, json=body("B", None))
    s = api.get(f"/trips/{t['id']}/story", headers=me).json()
    tp = {p["asset_id"]: p for p in s["trip_photos"]}
    assert tp["A"]["day"] == 2 and tp["A"]["item_key"] and tp["A"]["item_key"].startswith("flight")
    assert tp["B"]["day"] is None and tp["B"]["item_key"] is None


def test_trash_hides_and_purge_deletes_thumbnails(api, db):
    from app import models
    me = signup(api, "ana@example.com")
    t = trip(api, me)
    p = api.post(f"/trips/{t['id']}/photos", headers=me, json=body()).json()
    assert api.delete(f"/trips/{t['id']}", headers=me).status_code in (200, 204)
    assert api.get(p["thumb_url"], headers=me).status_code == 404  # hidden while in Recently Deleted
    assert db.query(models.TripPhoto).count() == 1
    api.post(f"/trash/trips/{t['id']}/restore", headers=me)
    assert api.get(p["thumb_url"], headers=me).status_code == 200
    api.delete(f"/trips/{t['id']}", headers=me)
    assert api.delete(f"/trash/trips/{t['id']}", headers=me).status_code in (200, 204)
    db.expire_all()
    assert db.query(models.TripPhoto).count() == 0


def test_merge_moves_photos_and_delete_account_removes_them(api, db):
    from app import models
    me = signup(api, "ana@example.com")
    a, b = trip(api, me), trip(api, me)
    api.post(f"/trips/{a['id']}/photos", headers=me, json=body("SAME"))
    api.post(f"/trips/{b['id']}/photos", headers=me, json=body("SAME"))
    api.post(f"/trips/{b['id']}/photos", headers=me, json=body("OTHER"))
    r = api.post(f"/trips/{a['id']}/merge", headers=me, json={"source_trip_id": b["id"], "confirm": True})
    assert r.status_code == 200, r.text
    assert sorted(p["asset_id"] for p in api.get(f"/trips/{a['id']}/photos", headers=me).json()) == ["OTHER", "SAME"]
    assert api.request("DELETE", "/me", headers=me, json={"password": "long enough 1"}).status_code in (200, 204)
    db.expire_all()
    assert db.query(models.TripPhoto).count() == 0


def test_migration_creates_trip_photos(tmp_path):
    db = tmp_path / "m.db"
    alembic(db, "upgrade", "b9e3d7f1a0c4")
    alembic(db, "upgrade", "head")
    c = sqlite3.connect(db)
    cols = {r[1] for r in c.execute("PRAGMA table_info(trip_photos)")}
    assert {"trip_id", "user_id", "device_id", "asset_id", "taken_at", "thumb", "width", "height"} <= cols
    c.close()
    alembic(db, "downgrade", "b9e3d7f1a0c4")
    alembic(db, "upgrade", "head")
