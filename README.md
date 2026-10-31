# Trippy

A self-hosted travel companion. Trippy keeps your flights, stays, rental cars and shared trip
expenses in one place, on a server you run yourself, with a native iOS app on top.

Your data stays on your server. There is no Trippy cloud, account service or telemetry.

## Screenshots

<sub>All screenshots use made-up demo data.</sub>

| | | |
|:-:|:-:|:-:|
| <img src="docs/screenshots/01-trips.png" width="240" alt="Trips list with route map"><br>Trips | <img src="docs/screenshots/02-today.png" width="240" alt="Today view with the next flight and rental"><br>Today | <img src="docs/screenshots/03-trip-detail.png" width="240" alt="Trip detail with itinerary"><br>Trip itinerary |
| <img src="docs/screenshots/04-flight.png" width="240" alt="Flight detail"><br>Flight | <img src="docs/screenshots/05-stay.png" width="240" alt="Hotel stay detail"><br>Stay | <img src="docs/screenshots/06-rental.png" width="240" alt="Rental car detail"><br>Rental car |
| <img src="docs/screenshots/07-journey-map.png" width="240" alt="Journey map across two trips"><br>Journey map | <img src="docs/screenshots/08-stats.png" width="240" alt="Year in travel and driver's log stats"><br>Stats | <img src="docs/screenshots/09-story.png" width="240" alt="Trip story"><br>Trip story |
| <img src="docs/screenshots/10-share-card.png" width="240" alt="Shareable trip card"><br>Share card | <img src="docs/screenshots/11-search.png" width="240" alt="Search across trips, flights and stays"><br>Search | <img src="docs/screenshots/12-swipe-actions.png" width="240" alt="Swipe actions on a journey"><br>Swipe actions |
| <img src="docs/screenshots/13-delete.png" width="240" alt="Delete confirmation with Recently Deleted"><br>Delete (30-day undo) | | |

## Features

- **Trips** with flights, hotel and rental stays, rental cars, activities and documents, on a timeline and a map.
- **Journeys** link several trips (Lisbon → Madrid) into one route.
- **Rentals and Driver's Log**: every rental car with pickup, return, mileage and cost.
- **Shared expenses**: add travelers, split costs (equally, exact amounts, percentages or shares) and settle up per trip or group.
- **Stats, stories and share cards**: miles, places, airlines, nights, and a year-in-travel recap you can save as an image.
- **Import** from calendar files and feeds (.ics), Flighty CSV, Apple Wallet boarding passes (.pkpass),
  booking emails (.eml or pasted text) and any CSV. See [IMPORTERS.md](IMPORTERS.md).
- **Email-in** (optional): forward booking confirmations to an address and Trippy files them.
- **Live flight status** (optional, bring your own API key): AeroDataBox, Aviationstack or FlightAware AeroAPI.
- **Accounts**: email and password sign-in, open / invite-only / closed sign-up, trip invites.
- **Recently Deleted**: deleted trips are kept for 30 days.
- **Offline**: the app keeps a cache and shows your trips without a connection.

## Repository layout

| Path | What it is |
|------|------------|
| `app/` | FastAPI server (Python): API, auth, importers, email-in, flight status |
| `alembic/` | Database migrations ([docs/MIGRATIONS.md](docs/MIGRATIONS.md)) |
| `tests/` | Server test suite (pytest) |
| `Dockerfile`, `docker-compose*.yml`, `install.sh` | Self-hosted deployment |
| `Trippy.swiftpm/` | iOS app sources (SwiftUI), also openable in Swift Playgrounds |
| `ios-xcode/`, `project.yml` | Xcode project spec (XcodeGen), Info.plist, widgets, build settings |
| `scripts/` | Optional one-off import and maintenance scripts |
| `docs/` | Design notes, API config, accounts |

## Run the server

You need Docker with Compose v2.

```sh
git clone https://github.com/<you>/trippy.git
cd trippy
./install.sh             # localhost only, open sign-up
curl http://127.0.0.1:8000/health
```

`install.sh` creates `.env` from [.env.example](.env.example) with a random signing key, then runs
`docker compose up -d --build`. Re-run it to upgrade; your `.env` and data are kept.

To reach the server from your phone (LAN, Tailscale, Caddy or Cloudflare Tunnel), set up email-in,
back up or upgrade, see **[SELF_HOSTING.md](SELF_HOSTING.md)**.

## Build the iOS app

Requires a recent Xcode, iOS 17 or later, and [XcodeGen](https://github.com/yonaskolb/XcodeGen).

```sh
brew install xcodegen
cp ios-xcode/Local.xcconfig.example ios-xcode/Local.xcconfig   # optional, gitignored
xcodegen generate
open Trippy.xcodeproj
```

`ios-xcode/Local.xcconfig` holds your own settings:

- `DEVELOPMENT_TEAM`: your Apple team ID (or pick a team in Xcode > Signing & Capabilities).
- `TRIPPY_API_BASE_URL`: the server the build points at by default. Empty means
  `http://localhost:8000`, which matches the Simulator next to `docker compose up`.

People can change the server in the app at any time (sign-in screen > Server, or Profile > Server).
The bundle identifiers live in `project.yml`; change them if you sign with your own team.
Details: [docs/IOS_API_CONFIG.md](docs/IOS_API_CONFIG.md).

## Develop the server

```sh
python3 -m venv venv
venv/bin/pip install -r requirements.txt -r requirements-dev.txt
venv/bin/python -m pytest -q
TRIPPY_DEV_MODE=1 venv/bin/uvicorn app.main:app --reload
```

## Security

Trippy is meant to run on your own machine or private network. Keep `.env` private, use HTTPS
for anything reachable from the internet, and see
[Reaching it from your phone](SELF_HOSTING.md#reaching-it-from-your-phone). Please report vulnerabilities privately instead of in a public issue.

## License

[MIT](LICENSE)

Airline, hotel and rental brand logos in the app are trademarks of their owners and are used only to
identify them. See [LOGOS_SOURCES.md](LOGOS_SOURCES.md).
