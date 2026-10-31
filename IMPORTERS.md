# Importing trips into Trippy

Every importer works the same way:

1. **Preview**: `POST /import/preview` reads the file, feed or text and returns what it found.
   Nothing is saved. Each item is marked `duplicate_of` when you already have it (or someone has
   shared it with you), or `duplicate_in_batch` when the same booking appears twice in the file.
2. **Commit**: `POST /import/commit` with the items you picked. Duplicates are checked again and
   skipped. Each item is owned by you and attached to a trip of yours whose dates cover it
   (`auto_trip`, the default; one day of slack), or to the `trip_id` you pass.

In the app: **Profile → Import** (or the Import tile), pick a source, choose a file or paste text,
review the list, untick what you don't want, then tap **Add**.

The importers here read formats that are published or that we checked against several independent
tools. Formats are never invented: if a source has no export we can read, it's listed as unsupported.

| Source | What to give Trippy | Finds | How sure |
|---|---|---|---|
| Calendar file | `.ics` from Google Calendar, Outlook, Apple Calendar, TripIt (per trip) | flights, hotels, rental cars | heuristic |
| Calendar feed | `webcal://` or `https://` link (TripIt feed, Google "secret address in iCal format", Outlook published calendar, iCloud public calendar) | same | heuristic |
| Flighty | the CSV from Flighty's export | flights | column names checked against 3 independent importers |
| Apple Wallet | a boarding pass `.pkpass` | flights | IATA BCBP standard |
| Email | a forwarded `.eml`, or paste the email text | rental cars (strong), flights and hotels (heuristic) | mixed |
| Any CSV | a CSV/TSV/semicolon file and a column mapping | flights, rental cars or hotel stays | you decide |

## Calendars (.ics files and feeds)

- Parsed with the `icalendar` library. Each `VEVENT` is classified from its title, location and description:
  - **Flight**: a flight number such as `UA837` or `AS 331`, plus two airport codes, as in `SFO to NRT`, `SFO → SEA`, or `(SFO) … (SEA)`.
  - **Rental car**: "car rental" or "rental car", or a rental company (Hertz, Avis, Enterprise, …) together with car/pickup/return words.
  - **Hotel**: "Stay at …", "hotel", "check-in", or a hotel brand.
  - Everything else is skipped and counted in `stats.skipped`.
- The event's `UID` becomes the item's `external_id` (`ics:<UID>`), so re-importing a feed doesn't create copies.
- Times keep the wall-clock time from the calendar. When an event is stored in UTC (`…Z`), the item carries a warning, because the local time at the airport isn't known.
- Feeds are downloaded by the server, with a 15 s timeout and a 5 MB cap. `webcal://` is treated as `https://`. Private, LAN and loopback addresses are refused, so the server can't be used to probe your home network.
- **TripIt**: TripIt's public API isn't open to new developers, so Trippy uses what TripIt still offers to everyone:
  - **Calendar feed**: on tripit.com, Settings → Calendar Feed (Calendar Sharing), then copy the `webcal://` link.
  - **One trip**: open the trip on tripit.com and use its iCal/Add-to-calendar option to get a `.ics`.
  - There is no TripIt file import beyond iCal. We didn't build an "official TripIt" connector because there isn't a usable public one.

## Flighty (CSV)

In Flighty, use the export-flights option in Settings; it produces a CSV file (the menu path may differ by version). Flighty
doesn't publish a spec. The columns below match what several third-party importers read; we haven't
seen a real export yet, so please send one if a row doesn't import:

`Date, Airline, Flight, From, To, Dep Terminal, Dep Gate, Arr Terminal, Arr Gate, Canceled, Diverted To,
Gate Departure (Scheduled), Gate Departure (Actual), Take off (Scheduled), Take off (Actual), Landing (Scheduled),
Landing (Actual), Gate Arrival (Scheduled), Gate Arrival (Actual), Aircraft Type Name, Tail Number, PNR, Seat,
Seat Type, Cabin Class, Flight Reason, Notes, Flight Flighty ID, Airline Flighty ID, …`

- `Airline` is the ICAO code (UAL, ANA, JAL). It's converted to the IATA code for the flight number (UA 837) and to the airline's name.
- Departure is the actual gate time when there is one, then the scheduled gate time, then take-off, then `Date`. Arrival follows the same order.
- Delay = actual minus scheduled gate departure. A flight with an actual arrival is marked Landed.
- Canceled flights are skipped. For a diverted flight, the diversion airport is used and the planned one goes into a warning.
- `Flight Flighty ID` becomes `external_id` (`flighty:<id>`).
- If the required columns (Date, Airline, Flight, From, To) are missing, the API returns 400 and suggests Generic CSV.

## Apple Wallet boarding passes (.pkpass)

A `.pkpass` is a zip file holding `pass.json` (Apple's PassKit format). Trippy:

1. Reads the barcode message as an IATA Bar Coded Boarding Pass (Resolution 792, the `M1…` string printed on every boarding pass).
   The fixed-width mandatory fields give the PNR, from, to, carrier, flight number, the day of the year, cabin and seat. Every leg of a multi-leg pass becomes its own item.
2. Takes the year and departure time from the pass's `relevantDate` when it's the same day (passes don't carry the year). Otherwise the year closest to the pass date is used and the item is flagged "only the date is known".
3. Falls back to the pass's display fields (origin/destination/flight/seat keys) when there's no IATA barcode, at medium confidence.

Airline passes signed by Apple are read as-is; Trippy doesn't verify the signature.

Getting a pass out of Wallet: in the airline's app or email, use "Share" / "Save to Files" on the pass, then pick that file in Trippy. Wallet itself doesn't export passes.

## Emails (.eml or pasted text)

- **Rental cars**: the receipt parser from Rental Car Tracker (vendored at commit 3370820 in `app/importers/vendor/`).
  It has templates for Avis, Enterprise and Hertz, and generic rules that also read Budget- and National-style receipts.
  Results are mapped with Trippy's `scripts/import_rentals.py` without network lookups (no geocoding or photos).
  The receipt's id becomes the `external_id`.
- **Flights** (low confidence): a flight number ("Flight TP 236", or a known airline code), two airport codes nearby, and dates/times after it.
  An arrival time earlier than departure on the same date is taken as the next day.
- **Hotels, by template** (`app/importers/hotel_templates.py`, learned from real emails):
  Booking.com confirmations (old and new layout), receipts and cancellations; Airbnb confirmations and receipts;
  Hotels.com confirmations; Capital One Travel; and hotel folios from Hilton, Marriott, IHG and Wyndham.
  Each gives name, check-in/out with times, nights, rooms, guests, room type, total, taxes, currency, address, city,
  country, a guessed time zone, brand, booking source and loyalty program (the program name only, never the member number).
  The `external_id` is `email:hotel:{confirmation}:{check-in date}`. Cancellations come back with `status: cancelled`.
  Bookings for more than one room get a warning, because the total covers everyone.
- **Hotels, fallback** (low confidence): hotel words plus "Check-in"/"Check-out" dates. The name comes from "Your stay at …", "Hotel: …", or a line with a hotel brand. Also reads "Address:" and the confirmation/reservation number.
- PDFs aren't accepted on the Import screen yet. Email-in (below) does read PDF attachments: their text goes through this same email reader.
- Hotel template tests use anonymized copies of real layouts (`tests/fixtures/emails/hotel_*.eml`). Flight emails are tested only with synthetic emails, so check the preview.

## Any CSV

1. Send the CSV without a mapping. The response has `needs_mapping: true`, the columns, five sample rows and a `suggested_mapping` guessed from the column names.
2. Send it again with `mapping` (`{"departure_time": "Departure Date", …}`) and `csv_kind` (`flight`, `rental` or `lodging`).

Required fields:
- flight: `flight_number, departure_airport, arrival_airport, departure_time`
- rental: `rental_company, pickup_time`
- lodging: `name, check_in`

Dates accept ISO (`2026-06-01 08:00`), US (`06/05/2026 18:00`) and `Jun 5, 2026`. Rows missing a required value are skipped and counted. Comma, semicolon and tab separators are detected.

## Not supported (and why)

- **TripIt API / OAuth**: closed to new developers. Use the calendar feed.
- **Google Travel, Kayak Trips, App in the Air**: no export format we can document. Kayak and Google can add trips to a calendar, which the calendar import reads.
- **Airline loyalty accounts**: these need each airline's private API and your login.
- **Gmail/Outlook mailbox scanning**: not built. Instead, a server can turn on **email-in**: people forward
  bookings to a per-user address and the server runs the body, `.ics`, `.pkpass`, PDF and `.eml` attachments
  through these importers, then files the results on matching trips (`app/inbound.py`, see SELF_HOSTING.md → Email-in).

## API

```
POST /import/preview
{ "source": "ics" | "ics_url" | "flighty_csv" | "pkpass" | "email" | "csv",
  "text": "…",            # or
  "data_base64": "…",     # file bytes (max 5 MB)
  "url": "webcal://…",    # ics_url only
  "filename": "x.eml",    # helps the email reader
  "csv_kind": "flight", "mapping": {…} }
→ { "items": [{ "index", "kind", "fields", "summary", "confidence", "warnings", "duplicate_of", "duplicate_in_batch" }],
    "stats": {…}, "new_count": 3, "needs_mapping": false }

POST /import/commit
{ "items": [{ "kind": "flight", "fields": {…} }], "trip_id": null, "auto_trip": true }
→ { "created": [{ "index", "kind", "id", "trip_id" }], "skipped": [{ "index", "kind", "duplicate_of", "reason" }] }

GET /import/sources   # the list the app's picker shows
```

Duplicate rules (against what you can see):
- flight: same `external_id`, or same flight number on the same day, or same route on the same day.
- rental: same `external_id` or confirmation number, or same company on the same pickup day.
- hotel: same `external_id` or confirmation number, or same name on the same check-in day.
