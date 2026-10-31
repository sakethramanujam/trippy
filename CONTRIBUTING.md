# Contributing to Trippy

Thanks for your interest in Trippy! It's a small, self-hosted travel tracker: a native iOS app (SwiftUI)
and a FastAPI server you run yourself. Bug fixes, importers for new booking emails, docs and design polish
are all welcome.

By taking part you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
Found a security problem? Please follow [SECURITY.md](SECURITY.md) instead of opening an issue.

## Contents

1. [Before you start](#before-you-start)
2. [Backend setup](#backend-setup)
3. [iOS setup](#ios-setup)
4. [Repository layout](#repository-layout)
5. [Coding style](#coding-style)
6. [Commits and pull requests](#commits-and-pull-requests)
7. [Adding an importer or parser](#adding-an-importer-or-parser)
8. [Design principles](#design-principles)
9. [Personal data never goes in the repo](#personal-data-never-goes-in-the-repo)

## Before you start

- For anything bigger than a small fix, open an issue first (bug report or feature request) so we can agree
  on the approach before you spend time on it.
- Issues labelled `good first issue` are a good place to start.
- Keep pull requests focused: one change per PR is much easier to review.

## Backend setup

You need Python 3 (the Docker image uses 3.12, so that is the safest choice).

```sh
git clone https://github.com/sakethramanujam/trippy.git
cd trippy
python3 -m venv venv
venv/bin/pip install -r requirements.txt -r requirements-dev.txt

# run the tests
venv/bin/python -m pytest -q

# run the server locally on http://127.0.0.1:8000 with auto-reload
TRIPPY_DEV_MODE=1 venv/bin/uvicorn app.main:app --reload
curl http://127.0.0.1:8000/health
```

- The local server uses a SQLite file in the repo folder. It's gitignored; never commit it.
- Interactive API docs are at `http://127.0.0.1:8000/docs` while the server is running.
- Changing a model in `app/models.py`? Add an Alembic migration
  (`alembic revision --autogenerate -m "describe change"`) and check it. See [docs/MIGRATIONS.md](docs/MIGRATIONS.md).
- To try the Docker image the way self-hosters run it: `./install.sh`, then `docker compose logs -f api`.

## iOS setup

You need a recent Xcode (iOS 17 SDK or later) and [XcodeGen](https://github.com/yonaskolb/XcodeGen).

```sh
brew install xcodegen
cp ios-xcode/Local.xcconfig.example ios-xcode/Local.xcconfig   # gitignored, your own settings
xcodegen generate
open Trippy.xcodeproj
```

- Pick the **Trippy** scheme and an iPhone Simulator, then Run. You don't need a signing team for the Simulator.
- Leave `TRIPPY_API_BASE_URL` empty in `Local.xcconfig` and the Simulator talks to `http://localhost:8000`,
  which matches the local server above.
- To run on a device, set `DEVELOPMENT_TEAM` in `Local.xcconfig` (and change the bundle identifiers in
  `project.yml` if you sign with your own team). Don't commit either change.
- `Trippy.xcodeproj` is generated from `project.yml`. Edit `project.yml`, not the project file, and re-run
  `xcodegen generate`.
- More detail: [docs/IOS_API_CONFIG.md](docs/IOS_API_CONFIG.md).

## Repository layout

| Path | What it is |
|------|------------|
| `app/` | FastAPI server: API routes, auth, sharing, money, journeys, email-in, flight status |
| `app/importers/` | Importers: `.ics`, Flighty CSV, `.pkpass`, generic CSV, and email templates for airlines and hotels |
| `alembic/` | Database migrations |
| `tests/` | Server test suite (pytest); `tests/fixtures/` holds scrubbed sample files |
| `Trippy.swiftpm/Sources/Trippy/` | iOS app sources (SwiftUI) |
| `ios-xcode/`, `project.yml` | XcodeGen spec, Info.plist, widgets (`TrippyWidgets/`), build settings |
| `Dockerfile`, `docker-compose*.yml`, `install.sh`, `deploy/` | Self-hosted deployment |
| `scripts/` | Optional one-off maintenance scripts |
| `docs/` | Design notes, API config, README images |
| `site/` | The project website (static HTML/CSS/JS, deployed by GitHub Pages) |

## Coding style

**Python**
- Follow the style of the code around you: PEP 8, type hints on public functions, `from __future__ import annotations`.
- Keep route handlers thin. Put logic in plain functions that are easy to test.
- Every behavior change gets a test. Bug fixes get a test that fails without the fix.
- Times are local wall-clock times at the place they happen (an airport, a hotel), like the rest of Trippy.

**Swift**
- SwiftUI and Swift concurrency (`async`/`await`); no new third-party dependencies without discussing it first.
- Small views, with logic in models or managers, not inside `body`.
- Support Dynamic Type, Dark Mode and VoiceOver labels for anything that isn't plain text.

**General**
- No new external services, telemetry or analytics. Optional integrations stay off by default and use the
  user's own keys.
- Update the docs (README, SELF_HOSTING.md, IMPORTERS.md) in the same PR when setup or behavior changes.

## Commits and pull requests

- Write commit messages in the imperative mood with a short summary line, for example
  `Add Lufthansa booking template` or `Fix overnight arrival dates in Alaska receipts`.
  Add a body explaining *why* when it isn't obvious.
- Branch from `main`, and rebase on `main` before opening the PR if it has moved.
- Fill in the pull request template: what changed, the linked issue, how you tested it, and screenshots for UI
  changes (demo data only).
- Run the tests (and an iOS build for app changes) before asking for review.

## Adding an importer or parser

Importers turn a file, feed or email into flights, stays and rental cars. Read [IMPORTERS.md](IMPORTERS.md)
first; it describes the preview → commit flow and the duplicate rules.

**A new airline or hotel email layout** (the most common contribution):

1. Get a real confirmation email of that layout and **scrub it** (see below). Save it as
   `tests/fixtures/emails/<sender>_<kind>.eml`.
2. Add a template function to `app/importers/airline_templates.py` (returns `Segment`s) or
   `app/importers/hotel_templates.py` (returns `Stay`s). It gets the normalized text and the email's sent date.
   Return an empty list when the layout doesn't match. Never guess.
3. Register it in that module's `TEMPLATES` list. More specific templates go before more general ones.
4. Add tests in `tests/test_airline_templates.py` or `tests/test_hotel_stays.py` that check the parsed
   fields exactly: flight numbers, airports, local times, overnight arrivals, confirmation number and price.
5. Run the whole suite, since a new template must not steal emails that other templates already handle.

**A new file format or source:** add a module under `app/importers/`, wire it into `service.py` and
`GET /import/sources`, add a small synthetic sample under `tests/fixtures/import/`, and document it in
IMPORTERS.md. Only support formats that are published or that you can check against several independent
exports. Don't invent a format.

**Scrubbing a fixture.** Replace, consistently through the whole file:

- names → `Jane Doe`, `John Smith`
- email addresses → `user@example.com`; domains you don't need → `example.com`
- confirmation and record locators → made-up codes such as `ABC123` / `DLTEST`
- ticket, loyalty, card and phone numbers → zeros or obviously fake numbers
- street addresses → a fake street in the same city
- prices → a different plausible amount
- years → a future year (the existing fixtures use 2030+), keeping weekdays consistent if the parser relies on them
- remove `Received:`, `X-*` and other headers that carry IPs, message IDs or tracking tokens, and tracking
  links and images in the HTML body

Keep the layout, labels and spacing exactly as the sender wrote them. That is what the parser needs.

## Design principles

Trippy should feel like a premium, Flighty-style travel app, not a form-filling tool:

- **Dark first.** Deep near-black backgrounds, with coral (`#FF7A59`) as the one accent color.
- **Big, confident type.** Large numbers and codes (`SFO → LIS`, `25 days to go`, `1:05 PM`) with tight
  tracking; secondary details in smaller, dimmer text.
- **The trip is the timeline.** Show what's next first. Group everything else by day.
- **Maps and routes** as the visual anchor for flights and journeys.
- **Calm, not busy.** Generous spacing, cards with subtle borders, motion that is short and purposeful,
  and that respects Reduce Motion.
- **Native.** System controls, SF Symbols, haptics where they help; works offline from the cache.
- **Honest data.** Show where information came from and how sure it is. Never make up a gate, time or seat.
- **Accessible.** Dynamic Type, VoiceOver labels and enough contrast on every screen.

Use made-up demo data for screenshots in issues, PRs and docs.

## Personal data never goes in the repo

Trippy's whole point is keeping travel data private, and that applies to this repository too.

- **Never commit real personal data**: no real names, email addresses, confirmation numbers, ticket or loyalty
  numbers, addresses, phone numbers, IP addresses or server URLs. That includes test fixtures, screenshots,
  logs, docs and commit messages.
- **Fixtures are always scrubbed or synthetic.** If you're unsure whether something identifies a person,
  replace it.
- **Never commit secrets or local config**: `.env`, `ios-xcode/Local.xcconfig`, API keys, database files
  (`*.db`) or exported data. They're gitignored; keep it that way.
- If you accidentally push personal data or a secret, tell the maintainer right away through
  [private reporting](https://github.com/sakethramanujam/trippy/security/advisories/new) so it can be removed
  from history, and rotate any exposed key.
