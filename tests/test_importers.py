"""Importers: each parser on synthetic fixtures, then preview → commit → de-dupe through the API."""
import base64
import io
import json
import zipfile
from datetime import datetime
from pathlib import Path

import pytest

from app import models
from app.importers import csv_generic, emails, flighty, ics, pkpass
from app.importers.common import ImportError_

FIX = Path(__file__).parent / "fixtures" / "import"
BCBP = "M1DESMARAIS/LUC       EABC123 YULFRAAC 0834 326J001A0025 100"  # IATA Resolution 792 example


def make_pkpass(pass_json: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("pass.json", json.dumps(pass_json))
        z.writestr("manifest.json", "{}")
    return buf.getvalue()


def boarding_pass(**extra) -> dict:
    return {"formatVersion": 1, "passTypeIdentifier": "pass.test", "serialNumber": "SN1",
            "organizationName": "Air Canada", "relevantDate": "2026-11-22T15:30-05:00",
            "boardingPass": {"transitType": "PKTransitTypeAir"}, **extra}


# --- parsers -------------------------------------------------------------------

def test_ics_classifies_flights_hotels_cars_and_skips_the_rest():
    items, stats = ics.parse_ics((FIX / "synthetic_calendar.ics").read_bytes())
    assert stats == {"events": 5, "skipped": 1}
    by = {(i["kind"], i["fields"].get("flight_number") or i["fields"].get("name") or i["fields"].get("rental_company")): i
          for i in items}
    ua = by[("flight", "UA 837")]["fields"]
    assert (ua["departure_airport"], ua["arrival_airport"], ua["confirmation_number"]) == ("SFO", "NRT", "ABC123")
    assert ua["external_id"] == "ics:flight-1@synthetic"
    assert "UTC" in by[("flight", "UA 837")]["warnings"][0]
    assert by[("flight", "AS 331")]["fields"]["departure_time"] == datetime(2026, 5, 1, 7, 30)
    hotel = by[("lodging", "Hotel Gracery Shinjuku")]["fields"]
    # date-only stay: usual hours, flagged approximate (not a 12:00 AM check-in)
    assert (hotel["check_in"], hotel["check_out"]) == (datetime(2026, 4, 11, 15), datetime(2026, 4, 15, 11))
    assert hotel["time_approx"] is True
    assert by[("rental", "Hertz")]["fields"]["pickup_time"] == datetime(2026, 4, 20, 10)


def test_ics_rejects_garbage():
    with pytest.raises(ImportError_):
        ics.parse_ics(b"not a calendar")


@pytest.mark.parametrize("url", ["http://127.0.0.1/cal.ics", "webcal://localhost/x.ics", "ftp://example.com/x.ics",
                                 "http://10.0.0.5/feed", "http://169.254.169.254/latest"])
def test_feed_fetch_refuses_private_and_odd_urls(url):
    with pytest.raises(ImportError_):
        ics.fetch_feed(url)


def test_flighty_csv_maps_icao_skips_canceled_and_keeps_actual_times():
    items, stats = flighty.parse_flighty_csv((FIX / "flighty_export_synthetic.csv").read_bytes())
    assert stats == {"rows": 3, "skipped": 0, "canceled": 1}
    ua, jl = (i["fields"] for i in items)
    assert (ua["flight_number"], ua["airline"], ua["seat"], ua["cabin_class"]) == ("UA 837", "United Airlines", "31A", "economy")
    assert ua["departure_time"] == datetime(2026, 3, 3, 11, 25) and ua["delay_minutes"] == 20
    assert ua["arrival_time"] == datetime(2026, 3, 4, 14, 38) and ua["status"] == "Landed"
    assert ua["external_id"] == "flighty:f-1" and ua["aircraft_model"] == "Boeing 787-9"
    # Crossing the date line eastbound: arrives "before" it leaves, local time. Kept as-is.
    assert jl["flight_number"] == "JL 2" and jl["arrival_time"] < jl["departure_time"]


def test_flighty_csv_rejects_other_csvs():
    with pytest.raises(ImportError_, match="Generic CSV"):
        flighty.parse_flighty_csv((FIX / "generic_flights.csv").read_bytes())


def test_bcbp_mandatory_fields():
    (leg,) = pkpass.parse_bcbp(BCBP)
    assert (leg["pnr"], leg["from"], leg["to"], leg["carrier"], leg["flight"], leg["julian"], leg["seat"]) == \
           ("ABC123", "YUL", "FRA", "AC", "834", "326", "1A")
    assert pkpass.parse_bcbp("not a boarding pass") == []


def test_pkpass_with_barcode_uses_relevant_date_for_time():
    data = make_pkpass(boarding_pass(barcodes=[{"format": "PKBarcodeFormatPDF417", "message": BCBP}]))
    (item,), stats = pkpass.parse_pkpass(data)
    f = item["fields"]
    assert stats["barcode"] == "bcbp"
    assert (f["flight_number"], f["departure_airport"], f["arrival_airport"]) == ("AC 834", "YUL", "FRA")
    assert f["departure_time"] == datetime(2026, 11, 22, 15, 30) and f["confirmation_number"] == "ABC123"


def test_pkpass_without_barcode_falls_back_to_fields():
    bp = boarding_pass()
    bp["boardingPass"].update(primaryFields=[{"key": "origin", "label": "SFO", "value": "SFO"},
                                             {"key": "destination", "label": "JFK", "value": "JFK"}],
                              auxiliaryFields=[{"key": "flight", "label": "Flight", "value": "B6 416"},
                                               {"key": "seat", "label": "Seat", "value": "12C"}])
    (item,), _ = pkpass.parse_pkpass(make_pkpass(bp))
    assert (item["fields"]["flight_number"], item["fields"]["seat"], item["confidence"]) == ("B6 416", "12C", "medium")


def test_pkpass_rejects_non_boarding_passes():
    with pytest.raises(ImportError_, match="boarding pass"):
        pkpass.parse_pkpass(make_pkpass({"formatVersion": 1, "storeCard": {}}))
    with pytest.raises(ImportError_):
        pkpass.parse_pkpass(b"PK not really")


def test_email_rental_receipts_reuse_the_tracker_parser():
    for name, company, pickup in (("avis_receipt_SAMPLE.eml", "Avis", datetime(2026, 3, 2, 10, 15)),
                                  ("budget_receipt_SAMPLE.txt", "Budget", datetime(2025, 6, 18, 14, 5))):
        (item,), _ = emails.parse_email((FIX / name).read_bytes(), name)
        assert item["kind"] == "rental" and item["fields"]["rental_company"] == company
        assert item["fields"]["pickup_time"] == pickup and item["fields"]["external_id"].startswith("r_")
        assert any("SAMPLE" in w for w in item["warnings"])


def test_email_flight_and_hotel_heuristics():
    (fl,), _ = emails.parse_email((FIX / "flight_email_synthetic.txt").read_bytes(), "x.txt")
    assert (fl["fields"]["flight_number"], fl["fields"]["departure_airport"], fl["fields"]["arrival_airport"]) == ("TP 236", "SFO", "LIS")
    assert fl["fields"]["departure_time"] == datetime(2026, 5, 2, 18, 30)
    assert fl["fields"]["arrival_time"] == datetime(2026, 5, 3, 14, 45)  # next day
    assert fl["fields"]["confirmation_number"] == "XK7Q2P" and fl["confidence"] == "low"
    (h,), _ = emails.parse_email((FIX / "hotel_email_synthetic.txt").read_bytes(), "x.txt")
    assert h["fields"]["name"] == "Hotel Alfama Test"
    assert (h["fields"]["check_in"], h["fields"]["check_out"]) == (datetime(2026, 5, 3, 15), datetime(2026, 5, 7, 11))
    assert h["fields"]["confirmation_number"] == "H55TEST9" and h["fields"]["address"].startswith("Rua de Exemplo")


def test_email_with_nothing_travel_related():
    items, _ = emails.parse_email(b"Hi! Lunch on Friday?", "x.txt")
    assert items == []


MAPPING = {"flight_number": "Flight No", "airline": "Carrier", "departure_airport": "Origin",
           "arrival_airport": "Destination", "departure_time": "Departure Date", "arrival_time": "Arrival Date",
           "confirmation_number": "Record Locator"}


def test_generic_csv_suggests_mapping_and_parses():
    data = (FIX / "generic_flights.csv").read_bytes()
    desc = csv_generic.describe(data, "flight")
    assert desc["suggested_mapping"] == MAPPING and desc["row_count"] == 3
    items, stats = csv_generic.parse_csv(data, "flight", MAPPING)
    assert stats == {"rows": 3, "skipped": 1}
    assert [i["fields"]["departure_airport"] for i in items] == ["ATL", "BOS"]
    assert items[1]["fields"]["departure_time"] == datetime(2026, 6, 5, 18)
    with pytest.raises(ImportError_, match="Map a column"):
        csv_generic.parse_csv(data, "flight", {"flight_number": "Flight No"})
    with pytest.raises(ImportError_, match="Unknown column"):
        csv_generic.parse_csv(data, "flight", {**MAPPING, "seat": "Nope"})


# --- API -----------------------------------------------------------------------

def signup(api, email):
    r = api.post("/auth/signup", json={"email": email, "password": "long enough 1", "name": email.split("@")[0]})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_preview_commit_dedupe_and_auto_trip(api):
    me = signup(api, "ana@example.com")
    trip = api.post("/trips/", headers=me, json={"title": "Japan", "start_date": "2026-04-09T00:00",
                                                 "end_date": "2026-04-16T00:00"}).json()
    ics_text = (FIX / "synthetic_calendar.ics").read_text()
    prev = api.post("/import/preview", headers=me, json={"source": "ics", "text": ics_text})
    assert prev.status_code == 200, prev.text
    body = prev.json()
    assert body["new_count"] == 4 and all(i["duplicate_of"] is None for i in body["items"])
    picked = [{"kind": i["kind"], "fields": i["fields"]} for i in body["items"]]
    done = api.post("/import/commit", headers=me, json={"items": picked}).json()
    assert len(done["created"]) == 4 and done["skipped"] == []
    on_trip = {c["kind"] for c in done["created"] if c["trip_id"] == trip["id"]}
    assert on_trip == {"flight", "lodging"}  # April 10-15; the Apr 20 car and May 1 flight don't fit
    t = api.get(f"/trips/{trip['id']}", headers=me).json()
    assert [l["name"] for l in t["lodgings"]] == ["Hotel Gracery Shinjuku"]
    # Same file again: everything is flagged, and committing creates nothing.
    again = api.post("/import/preview", headers=me, json={"source": "ics", "text": ics_text}).json()
    assert again["new_count"] == 0 and all(i["duplicate_of"] for i in again["items"])
    assert api.post("/import/commit", headers=me, json={"items": picked}).json()["created"] == []
    # A Flighty row for the same UA 837 on another day is new; a CSV copy of a flight on the same day isn't.
    assert len(api.get("/flights/", headers=me).json()) == 2


def test_imports_are_private_and_dedupe_is_per_user(api):
    ana, ben = signup(api, "ana@example.com"), signup(api, "ben@example.com")
    payload = {"source": "flighty_csv", "data_base64": base64.b64encode((FIX / "flighty_export_synthetic.csv").read_bytes()).decode()}
    items = [{"kind": i["kind"], "fields": i["fields"]} for i in api.post("/import/preview", headers=ana, json=payload).json()["items"]]
    assert len(api.post("/import/commit", headers=ana, json={"items": items}).json()["created"]) == 2
    assert api.get("/flights/", headers=ben).json() == []
    # Ben's preview isn't affected by Ana's data, and he can't attach to her trips.
    assert api.post("/import/preview", headers=ben, json=payload).json()["new_count"] == 2
    ana_trip = api.post("/trips/", headers=ana, json={"title": "Ana's"}).json()
    assert api.post("/import/commit", headers=ben, json={"items": items, "trip_id": ana_trip["id"]}).status_code == 404


def test_batch_duplicates_and_bad_items(api):
    me = signup(api, "ana@example.com")
    f = {"airline": "Delta", "flight_number": "DL 1", "departure_airport": "ATL", "arrival_airport": "BOS",
         "departure_time": "2026-06-01T08:00", "arrival_time": "2026-06-01T10:40"}
    r = api.post("/import/commit", headers=me, json={"items": [{"kind": "flight", "fields": f}] * 2}).json()
    assert len(r["created"]) == 1 and r["skipped"][0]["reason"] == "duplicate"
    bad = api.post("/import/commit", headers=me, json={"items": [{"kind": "flight", "fields": {"airline": "X"}}]})
    assert bad.status_code == 400
    assert api.post("/import/commit", headers=me, json={"items": []}).status_code == 400


def test_preview_errors_and_csv_mapping_step(api):
    me = signup(api, "ana@example.com")
    assert api.post("/import/preview", headers=me, json={"source": "pkpass", "data_base64": base64.b64encode(b"nope").decode()}).status_code == 400
    assert api.post("/import/preview", headers=me, json={"source": "ics_url", "url": "http://127.0.0.1:8000/x.ics"}).status_code == 400
    assert api.post("/import/preview", headers=me, json={"source": "email"}).status_code == 400
    csv_text = (FIX / "generic_flights.csv").read_text()
    step1 = api.post("/import/preview", headers=me, json={"source": "csv", "text": csv_text}).json()
    assert step1["needs_mapping"] and step1["suggested_mapping"]["departure_time"] == "Departure Date"
    step2 = api.post("/import/preview", headers=me, json={"source": "csv", "text": csv_text,
                                                          "mapping": step1["suggested_mapping"]}).json()
    assert step2["new_count"] == 2
    assert api.post("/import/preview", json={"source": "email", "text": "x"}).status_code == 401
    assert [s["source"] for s in api.get("/import/sources", headers=me).json()] == \
           ["ics", "ics_url", "flighty_csv", "pkpass", "email", "csv", "google_timeline"]


def test_email_import_of_rental_via_api(api):
    me = signup(api, "ana@example.com")
    data = base64.b64encode((FIX / "avis_receipt_SAMPLE.eml").read_bytes()).decode()
    prev = api.post("/import/preview", headers=me, json={"source": "email", "data_base64": data,
                                                         "filename": "avis.eml"}).json()
    (item,) = prev["items"]
    created = api.post("/import/commit", headers=me, json={"items": [{"kind": "rental", "fields": item["fields"]}]}).json()
    rid = created["created"][0]["id"]
    rentals = api.get("/rental_cars/", headers=me).json()
    assert [r["id"] for r in rentals] == [rid] and rentals[0]["owner_id"] is not None


def test_feed_previews_have_their_own_rate_limit(api):
    me = signup(api, "feeds@example.com")
    codes = [api.post("/import/preview", headers=me,
                      json={"source": "ics_url", "url": "http://127.0.0.1/cal.ics"}).status_code
             for _ in range(21)]
    assert codes[:20] == [400] * 20  # refused: private address
    assert codes[20] == 429
    # File previews aren't affected by the feed limit.
    ok = api.post("/import/preview", headers=me, json={"source": "ics", "text": (FIX / "synthetic_calendar.ics").read_text()})
    assert ok.status_code == 200
