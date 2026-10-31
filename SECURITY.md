# Security policy

Trippy holds personal travel data: bookings, confirmation numbers, where people stay and who they travel
with. Security reports are very welcome.

## Supported versions

Trippy is released from `main`. Only the latest commit on `main` (and the newest tagged release, once there
are any) gets security fixes. If you run an older build, upgrade first (see
[SELF_HOSTING.md → Upgrade](SELF_HOSTING.md#upgrade)) and check whether the problem is still there.

| Version | Supported |
|---|---|
| `main` / latest | ✅ |
| anything older | ❌ |

## Reporting a vulnerability

**Please don't open a public issue, discussion or pull request for security problems.**

Report privately through GitHub's private vulnerability reporting:

1. Go to the [Security tab](https://github.com/sakethramanujam/trippy/security) of this repository.
2. Click **Report a vulnerability** (or open
   [a new advisory](https://github.com/sakethramanujam/trippy/security/advisories/new) directly).
3. Describe the issue, the affected component and version or commit, and steps to reproduce.
   A proof of concept helps. Use demo data, not anyone's real bookings.

Only the maintainer can see the report. GitHub private reporting is the only supported channel.

## What to expect

Trippy is a hobby project maintained in spare time, so everything below is best effort, not a guarantee:

- An acknowledgement within about a week.
- An initial assessment, and questions if needed, within a few weeks.
- A fix on `main` as soon as practical for confirmed issues, with severe ones first.
- Credit in the advisory if you'd like it.

Please give a reasonable amount of time to fix a confirmed issue before disclosing it publicly.

## Scope

In scope:

- **Server**: the FastAPI app in `app/`: authentication, sign-up and invites, trip sharing and access
  control, importers, email-in, flight status and the API in general.
- **iOS app**: `Trippy.swiftpm/` and `ios-xcode/`: token storage, the offline cache, widgets and how
  the app talks to the server.
- **Self-host configs**: `Dockerfile`, `docker-compose*.yml`, `install.sh`, `deploy/` and the defaults
  in `.env.example`.

Out of scope:

- Problems that need an already-compromised host, a malicious server admin, or physical access to an
  unlocked device.
- Insecure setups the docs warn against, such as exposing the server to the internet over plain HTTP.
- Third-party services (flight data providers, mail servers, reverse proxies) unless Trippy uses them in an
  unsafe way.
- The marketing website, unless the issue affects users of the app or server.
- Denial of service through sheer request volume, and missing best-practice headers with no demonstrated impact.

## Hardening your own server

Trippy is built to run on your own machine or private network. A few things matter most:

- **Keep sign-up invite-only.** Use `TRIPPY_SIGNUP_MODE=invite` (or `closed` once everyone has an account)
  so strangers can't create accounts. See [Accounts and sign-up](SELF_HOSTING.md#accounts-and-sign-up).
- **Bind to localhost, your LAN or Tailscale.** The default `TRIPPY_BIND=127.0.0.1` keeps it local.
  Reach it from your phone over your home network or [Tailscale](SELF_HOSTING.md#tailscale-private-works-away-from-home)
  rather than opening a port on your router.
- **Use HTTPS for anything beyond your own network.** Put it behind a reverse proxy that terminates TLS
  (for example [Caddy](SELF_HOSTING.md#caddy-public-https-on-your-own-domain) or
  [Cloudflare Tunnel](SELF_HOSTING.md#cloudflare-tunnel-public-https-no-open-ports)).
  **Never expose the server to the internet without TLS**: sign-in tokens and booking data would travel in clear text.
- **Keep `.env` private.** It holds the signing key and any API keys. `install.sh` sets it to mode `600`;
  keep it that way (`chmod 600 .env`) and never commit it or paste it into an issue.
- **Back up regularly** and keep backups as private as the server itself. See
  [Back up and restore](SELF_HOSTING.md#back-up-and-restore).
- **Leave optional features off until you need them.** Email-in and live flight status are off by default.
  If you turn on the built-in SMTP receiver, read its section in SELF_HOSTING.md first.
- **Stay up to date.** Re-run `./install.sh` (after a backup) to pick up fixes.
