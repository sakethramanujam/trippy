# Self-hosting Trippy

The Trippy API is one small container: a Python (FastAPI) app with a SQLite database
stored in a Docker volume. One server can hold many accounts. Friends who share trips
should use the same server.

- Image: built from this repository's `Dockerfile` (multi-arch: amd64 and arm64, so it also runs on a Raspberry Pi 4/5 or an Apple-silicon Mac).
- Runs as a non-root user (uid/gid 10001).
- Applies database migrations (`alembic upgrade head`) on every start.
- Health check: `GET /health` (no sign-in needed). The iOS app uses it to check the server address.
- Data: `/data/trippy.db` and `/data/jwt-secret` inside the container.

## Contents

1. [Quick start](#quick-start)
2. [Settings](#settings)
3. [Accounts and sign-up](#accounts-and-sign-up)
4. [Portainer](#portainer)
5. [Reaching it from your phone](#reaching-it-from-your-phone): LAN, Tailscale, Caddy, Cloudflare Tunnel
6. [Connect the iOS app](#connect-the-ios-app)
7. [Back up and restore](#back-up-and-restore)
8. [Upgrade](#upgrade)
9. [Email-in (forward bookings)](#email-in-forward-bookings)
10. [Troubleshooting](#troubleshooting)

## Quick start

You need Docker with Compose v2 (`docker compose version`).

```sh
git clone <this repository> trippy
cd trippy
./install.sh            # localhost only, open sign-up
# or: ./install.sh --lan --port 8000 --signup invite
```

`install.sh` does the following:

1. Creates `.env` from `.env.example` the first time, with a random signing key, and sets its mode to 600.
2. Applies any flags you passed.
3. Runs `docker compose up -d --build`.
4. Waits until `/health` answers.

You can run it again at any time. It keeps your `.env` and your data.

If you'd rather run the steps yourself:

```sh
cp .env.example .env     # then edit it
docker compose up -d --build
curl http://127.0.0.1:8000/health
# {"status":"healthy","service":"trippy","version":"0.2.0","auth":"required","signup":"invite","password_reset":"server-log"}
```

By default the API is published only on `127.0.0.1:8000`, so nothing outside the machine
can reach it. See [Reaching it from your phone](#reaching-it-from-your-phone) to change that.

## Settings

All settings are environment variables. They go in `.env` next to `docker-compose.yml`,
or in the stack's environment variables in Portainer. `.env.example` documents each one.

| Variable | Default | What it does |
|---|---|---|
| `TRIPPY_PORT` | `8000` | Host port to publish on. |
| `TRIPPY_BIND` | `127.0.0.1` | Host interface to publish on. Use `0.0.0.0` for your LAN. |
| `TRIPPY_DATA` | `trippy-data` (named volume) | Where the database and key are stored. A host path such as `./trippy-data` must be writable by uid 10001. |
| `TRIPPY_JWT_SECRET` | generated into `/data/jwt-secret` | Key that signs sign-in tokens. Changing it signs everyone out. |
| `TRIPPY_SIGNUP_MODE` | `invite` | `open`, `invite`, or `closed`. See below. |
| `TRIPPY_SIGNUP_ALLOWLIST` | empty | Comma-separated emails or `@domain`s that may always sign up. |
| `TRIPPY_ALLOWED_ORIGINS` | empty | Browser origins allowed by CORS, comma-separated. Empty (and `*`) means no browser access. The iOS app doesn't need this. |
| `TRIPPY_DOCS` | `0` | `1` serves `/docs`, `/redoc` and `/openapi.json`. Leave it off on a shared network. |
| `TRIPPY_MAX_BODY_BYTES` | `8388608` | Largest request body accepted (8 MB). Bigger requests get 413 before sign-in is checked. |
| `TRIPPY_MAX_IMPORT_BODY_BYTES` | `29360128` | Larger cap for `POST /import/preview` only (28 MB), for Google Maps Timeline exports. Parsing a 20 MB export briefly needs ~250 MB of RAM; lower this on small boxes. |
| `TRIPPY_LISTEN` | unset | Comma-separated `IP:port` list, for `network_mode: host`. The server binds each address itself and keeps retrying (every 5 s) any that does not exist yet, so a Tailscale address that comes up after Docker at boot still gets served. Use this instead of `"100.x.y.z:8840:8000"` port publishing, which leaves the container stopped after a reboot if the address is late. Include `127.0.0.1:PORT` so the health check works. |
| `TRIPPY_FORWARDED_ALLOW_IPS` | `127.0.0.1` | IPs whose `X-Forwarded-*` headers are trusted. Set it to your reverse proxy's IP, or `*` **only** if no host port is directly reachable (`TRIPPY_BIND=127.0.0.1`). Never combine `TRIPPY_FORWARDED_ALLOW_IPS=*` with a public `TRIPPY_BIND=0.0.0.0`, or callers can spoof `X-Forwarded-For` to bypass per-IP rate limits. |
| `TRIPPY_SMTP_HOST`, `_PORT`, `_SECURITY`, `_USERNAME`, `_PASSWORD`, `_FROM` | unset | Lets the server email password-reset codes. `_SECURITY` is `starttls` (port 587), `ssl` (port 465), or `none`. |
| `TRIPPY_INBOUND_MODE` | `off` | Email-in: `off`, `imap` or `smtp`. The other `TRIPPY_INBOUND_*` settings are in [Email-in](#email-in-forward-bookings) and `.env.example`. |
| `TZ` | `UTC` | Container time zone. Only affects logs. |

After you edit `.env`, apply the change with `docker compose up -d`.

## Accounts and sign-up

- **The first account.** The first person to sign up on an empty server always gets in,
  whatever the mode. Create your own account right after the first start, before you share
  the address with anyone.
- **`open`**. Anyone who can reach the server can create an account. Only use this on a
  network where you trust every device.
- **`invite`** (default). A new account is allowed only with:
  - a one-time **invite code** (see below), or
  - an email that matches `TRIPPY_SIGNUP_ALLOWLIST`.

  Anyone else gets "This server is invite-only."
- **`closed`**. No new accounts, except emails on the allowlist. Invite codes don't work.

**Invite codes.** A traveler you add to a trip who hasn't signed up yet is a placeholder.
Whoever claims that placeholder gets every trip, expense and group attached to it, so knowing
the email address isn't enough, in any mode:

1. On the trip, tap the traveler and choose **Share invite code**
   (`POST /trips/{trip_id}/travelers/{user_id}/invite-code`).
2. Send the code yourself (message, in person). It works once and expires after 14 days.
   Asking again replaces the previous code.
3. They enter it on the sign-up screen. If they already have an account, they use
   **Join with invite code** in Settings (`POST /invites/redeem`) and take the traveler's place
   on the trip, including its expenses.

An allowlisted email can still claim its placeholder without a code. Adding someone by email
only links their existing account if you already share a trip or group with them; otherwise
they get a placeholder and need a code, so nobody is added to a trip without agreeing.

To turn off open sign-up:

```sh
# in .env
TRIPPY_SIGNUP_MODE=invite          # or closed
TRIPPY_SIGNUP_ALLOWLIST=friend@example.com,@family.example
docker compose up -d
```

`/health` reports the current mode, and the app shows it on the sign-up screen.

**Password resets.** With SMTP configured, the server emails reset codes. Without SMTP,
the code is printed to the server log. The person resetting their password then asks you for it:

```sh
docker compose logs api | grep -i "reset code"
```

## Portainer

Portainer can deploy Trippy straight from this repository and build the image itself:

1. Go to **Stacks**, then **Add stack**, then **Repository**.
2. Fill in the stack:
   - Repository URL: this repo. Add credentials if it's private.
   - Reference: `refs/heads/main`
   - Compose path: `docker-compose.yml`
3. Under **Environment variables**, add the settings you want. For example:
   - `TRIPPY_BIND=0.0.0.0`
   - `TRIPPY_PORT=8000`
   - `TRIPPY_SIGNUP_MODE=invite`
   - `TRIPPY_JWT_SECRET=<output of openssl rand -hex 32>`

   The compose file passes each `TRIPPY_*` variable into the container, so you don't need a `.env` file.
4. Click **Deploy the stack**. The first build takes a few minutes.
5. Check the container. It should show **healthy**. You can also open `http://<host>:8000/health`.

To upgrade, open the stack and click **Pull and redeploy**. The data volume
(`trippy_trippy-data`) is kept.

If you'd rather paste the compose file into the **Web editor**, first build and push the image
somewhere Portainer can pull from. Then set `TRIPPY_IMAGE` to that image and remove the `build:` line.

## Reaching it from your phone

The defaults publish nothing beyond the host. Pick one of the options below.
Each one exposes something different.

### Home LAN only

Set `TRIPPY_BIND=0.0.0.0` (or run `./install.sh --lan`), then run `docker compose up -d`.

- **Exposes:** port 8000, over plain HTTP, to every device on your network. Nothing reaches the internet unless you forward the port on your router. Don't forward it.
- **App address:** `http://<host-ip>:8000` or `http://<hostname>.local:8000`. iOS allows plain HTTP to local hostnames and LAN IPs, and asks for Local Network permission the first time.

### Tailscale (private, works away from home)

Install Tailscale on the server and on your phone. Keep `TRIPPY_BIND=127.0.0.1`, then run:

```sh
sudo tailscale serve --bg --https=443 http://127.0.0.1:8000
```

- **Exposes:** `https://<machine>.<tailnet>.ts.net`, with a valid certificate. Only devices signed in to your tailnet can reach it. Nothing is public.
- **App address:** `https://<machine>.<tailnet>.ts.net`
- Friends need to join your tailnet, or you can share the machine with them from the Tailscale admin console.
- Don't use `tailscale funnel`. It makes the server public.

### Caddy (public HTTPS on your own domain)

Use this when the server has a public IP and you control a domain. First point an `A`/`AAAA`
record at the server and open ports 80 and 443. Then add a `Caddyfile`:

```
trippy.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

- **Exposes:** the whole API to the internet over HTTPS. Caddy gets the certificate automatically. Set `TRIPPY_SIGNUP_MODE=invite` or `closed` before you do this.
- If Caddy runs in a container on the same Docker network instead, reverse-proxy to `api:8000`. Also set `TRIPPY_FORWARDED_ALLOW_IPS` to Caddy's IP, or `*` if no port is published.
- **App address:** `https://trippy.example.com`

### Cloudflare Tunnel (public HTTPS, no open ports)

1. In Cloudflare Zero Trust, go to **Networks**, then **Tunnels**, and create a tunnel. Copy its token.
2. Add a public hostname, for example `trippy.example.com`, with service `http://localhost:8000`.
3. Run the connector on the server:

   ```sh
   docker run -d --name cloudflared --restart unless-stopped --network host \
     cloudflare/cloudflared:latest tunnel --no-autoupdate run --token <TOKEN>
   ```

- **Exposes:** the API at `https://trippy.example.com` to anyone on the internet, through Cloudflare. No inbound ports are opened on your router.
- Use `invite` or `closed` sign-up.
- Don't put Cloudflare Access (the browser login page) in front of the API. The app can't complete that login.
- **App address:** `https://trippy.example.com`

## Connect the iOS app

1. On the welcome, sign-up, or log-in screen, tap the **Server** row under the buttons.
2. Enter your server address, for example:
   - `https://trippy.example.com`
   - `http://192.168.1.20:8000`
   - `https://box.tailnet.ts.net`
3. Tap **Test connection**. The app calls `/health` and checks that the answer comes from a Trippy server.
4. Tap **Save**.

The dot next to the address shows the server's state: green when it's reachable, orange when it isn't. The text
next to it shows the server's version and sign-up mode.

If you build the app yourself, set the default address in `project.yml`
(`TRIPPY_API_BASE_URL`). See `docs/IOS_API_CONFIG.md`.

## Back up and restore

Everything lives in two files on the data volume: `trippy.db` and `jwt-secret`.
Trip photo thumbnails (≤512 px JPEGs, up to 500 per trip per person) are stored in `trippy.db` too, so
it grows by roughly 30–60 KB per photo. Full-size photos never leave the phones they were taken on.

**Back up** (safe while the server is running):

```sh
docker compose exec api python -c "import sqlite3; sqlite3.connect('/data/trippy.db').backup(sqlite3.connect('/data/backup.db'))"
docker compose cp api:/data/backup.db ./trippy-$(date +%F).db
docker compose cp api:/data/jwt-secret ./trippy-jwt-secret
docker compose exec api rm /data/backup.db
```

Keep the copies somewhere private. The `.db` file holds everyone's trips, and the secret can sign in
as anyone. To run this nightly, put the same commands in a cron job.

**Restore:**

```sh
docker compose stop api
docker compose cp ./trippy-2026-01-31.db api:/data/trippy.db
docker compose cp ./trippy-jwt-secret api:/data/jwt-secret   # optional: keeps people signed in
# copied files keep your host owner; hand them back to the trippy user (uid 10001)
docker compose run --rm --user root --entrypoint chown api -R 10001:10001 /data
docker compose start api
```

`docker compose cp` works on a stopped container. If you bind-mounted a host folder instead
(`TRIPPY_DATA=./trippy-data`), you can copy the files there directly. Then run
`sudo chown -R 10001:10001 ./trippy-data` before you start the server again. If you skip
the `chown`, the container exits and its log tells you what to run.

**Move to a new server:** restore the backup there, then change the address in the app.

## Upgrade

```sh
cd trippy
# back up first (see above)
git pull
docker compose up -d --build      # or ./install.sh
docker compose ps                 # wait for "healthy"
```

Migrations run automatically when the container starts. If one fails, the container keeps
restarting and `docker compose logs api` shows the error. To go back:

1. `git checkout <previous tag or commit>`
2. Restore the backup.
3. Run `docker compose up -d --build`.

## Email-in (forward bookings)

Optional and **off by default**. When it's on, people on your server forward booking emails to an
address and Trippy files them on the right trip in the background. It reads the email body and these
attachments: calendar invites (`.ics`), Apple Wallet boarding passes (`.pkpass`), PDF receipts and
forwarded `.eml` files. Anything else is ignored and never opened. HTML is only converted to text;
nothing in an email is rendered, run or fetched.

There is no central Trippy mailbox. You point your server at a mailbox you already control.

### What happens to each email

1. **Who is it for?** Trippy looks for a per-user address in `Delivered-To`, `X-Original-To`, `To`
   and `Cc` (or the SMTP envelope). If there isn't one, it can fall back to the sender: mail **From** a
   user's account email is accepted when your mail provider's `Authentication-Results` header shows
   SPF, DKIM or DMARC passing for that domain (so a forged From is refused). Mail matching neither is
   ignored and not stored.
2. **What's in it?** The same importers as the app's Import screen run on the body and each attachment.
3. **Where does it go?** Each booking joins your trip whose dates cover it (preferring one at the same
   place). Bookings with no trip become a new trip named after the places, such as "Lisbon (email)".
   Bookings already in Trippy are skipped, and the same message (by `Message-ID`) is never read twice.
4. **The log.** Each person sees their own **Forwarded emails** list in the app (Profile), with what was
   added, what was skipped, and Retry/Delete. A badge shows new entries. Trippy never replies by email and
   sends no push notifications. The original message is kept for 30 days so Retry works, then dropped.

Limits: 15 MB per message (`TRIPPY_INBOUND_MAX_BYTES`), 10 attachments of up to 5 MB each, and 60 messages
per user per hour (`TRIPPY_INBOUND_MAX_PER_HOUR`; extra messages are logged as failed and can be retried).

### Mode 1: IMAP polling (recommended, no open ports)

Trippy logs in to an IMAP mailbox every few minutes, reads unread mail, marks it read and moves it to
`Trippy-Processed` (created if missing; set `TRIPPY_INBOUND_IMAP_PROCESSED_FOLDER=` to only mark it read).
Use a mailbox just for this, not your personal inbox.

```sh
./install.sh --email-in imap      # asks for the server, user, password and address scheme
# or set the TRIPPY_INBOUND_* lines in .env (see .env.example) and run: docker compose up -d
```

| Provider | `IMAP_HOST` | Security / port | Password | Per-user addresses |
|---|---|---|---|---|
| Gmail / Google Workspace | `imap.gmail.com` | `ssl` / 993 | [App password](https://myaccount.google.com/apppasswords) (needs 2-Step Verification) | `you+{token}@gmail.com` |
| Outlook.com / Microsoft 365 | `outlook.office365.com` | `ssl` / 993 | App password where your tenant still allows IMAP basic auth | `you+{token}@outlook.com` |
| Fastmail | `imap.fastmail.com` | `ssl` / 993 | App password | `you+{token}@fastmail.com`, or a catch-all domain |
| Proton Mail | `127.0.0.1` (Proton Bridge) | `starttls` or `none` / 1143 | Bridge password | `you+{token}@proton.me` |
| Your own Dovecot | your host | `ssl` / 993 | account password | plus-addressing or catch-all |

When Trippy runs in Docker, `127.0.0.1` is the container itself: for a bridge on the host use the host's LAN
address or `host.docker.internal` (add `extra_hosts: ["host.docker.internal:host-gateway"]` to the service).

**Address scheme** (`TRIPPY_INBOUND_ADDRESS_TEMPLATE`, `{token}` is replaced by each person's private code):

- Plus-addressing: `trips+{token}@example.com`. Mail to it lands in the `trips@example.com` mailbox.
- Catch-all on a domain: `{token}@trips.example.com`, with every address on that domain delivered to the mailbox.
- Empty: no per-user addresses. Everyone forwards to the one mailbox address you share with them, and mail
  is matched by sender only. The app then tells people to forward from their account email.

The app's Profile screen shows each person's address with Copy and Regenerate (the old address stops
working). Treat it like a password: anyone who knows it can add bookings to that account.

### Mode 2: built-in SMTP receiver (advanced, off by default)

`TRIPPY_INBOUND_MODE=smtp` makes Trippy accept mail itself on container port 2525. It only accepts mail for
addresses that match your template (no relaying) and refuses everything else with `550`. It has no TLS,
spam filtering or retry queue of its own.

To get mail from the internet you need all of:

- an MX record for the domain in your template pointing at this host,
- inbound port **25** forwarded from your router or firewall to the published port (many home ISPs block 25),
- `docker compose -f docker-compose.yml -f docker-compose.smtp.yml up -d` with `TRIPPY_INBOUND_SMTP_BIND=0.0.0.0`.

That puts an SMTP port on the open internet, where it will be scanned and spammed. Prefer IMAP mode, or
keep the receiver on `127.0.0.1` and have a mail server you already run hand mail to it.

### Alternative: Cloudflare Email Routing

If your domain is on Cloudflare you can avoid opening port 25: turn on
[Email Routing](https://developers.cloudflare.com/email-routing/) with a catch-all rule, and either forward to
a mailbox Trippy polls over IMAP (simplest), or send it to an
[Email Worker](https://developers.cloudflare.com/email-routing/email-workers/) that relays the raw message to
your Trippy SMTP receiver over a Cloudflare Tunnel or Tailscale. Trippy doesn't include that Worker.

### Checking it

`GET /health` includes an `inbound` field, for example
`{"enabled": true, "mode": "imap", "addresses": "per-user", "last_poll": "2026-10-31T04:05:00Z", "ok": true}`.
`ok: false` means the last poll failed; the reason is in `docker compose logs api` (it isn't shown on the
public health endpoint). To turn email-in off, set `TRIPPY_INBOUND_MODE=off` and run `docker compose up -d`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Log says `can't read and write /data/... as uid 10001` | The files are owned by someone else, usually after a restore or with a root-owned bind mount. Run the `chown` command printed in the log. |
| App says "Can't reach the server" | From the phone's network, try `curl http://<address>/health`. Check `TRIPPY_BIND`, the firewall, and Tailscale. |
| App says "isn't a Trippy server" | The address points at something else, such as the proxy's default page. Check the port or path. |
| "This server is invite-only" | Add them to a trip and share an invite code, or add the email to `TRIPPY_SIGNUP_ALLOWLIST`. |
| "You've been invited. Enter the invite code…" | Someone added that email to a trip. Share an invite code from the trip's traveler list. |
| Everyone got signed out | The JWT secret changed. Restore `jwt-secret`, or set `TRIPPY_JWT_SECRET` and keep it. |
| Forwarded emails don't show up | Check `/health` → `inbound`. `enabled: false` means a setting is missing. `ok: false`: see `docker compose logs api` (wrong password, app password needed, IMAP turned off at the provider). Mail From an address without SPF/DKIM pass needs a per-user address. |
| Building on a Pi is slow | Build once elsewhere with `docker buildx build --platform linux/arm64 -t you/trippy-api --push .` and set `TRIPPY_IMAGE`. |


## Live flight status (optional, off by default)

Trippy can show the gate, terminal, delay and baggage belt for a flight from a third-party provider.
It's off until you set a provider **and** a key; without them the app shows "Live status isn't configured
on this server". Add these to `~/trippy-stack/.env` (mode 600) and run `docker compose -p trippy up -d`:

| Variable | Meaning |
| --- | --- |
| `TRIPPY_FLIGHT_STATUS_PROVIDER` | `aerodatabox` (recommended), `aviationstack`, or `aeroapi`. Empty = off. |
| `TRIPPY_FLIGHT_STATUS_API_KEY` | The provider's key. Never logged or sent to the app. |
| `TRIPPY_FLIGHT_STATUS_BASE_URL` | Optional. For AeroDataBox through API.market instead of RapidAPI, use `https://prod.api.market/api/v1/aedbx/aerodatabox`. |
| `TRIPPY_FLIGHT_STATUS_CACHE_SECONDS` | How long one answer is reused for everyone (default `900`). |

Endpoint: `GET /flights/{id}/status` (signed in, same visibility as the flight). It answers
`{"configured", "provider", "status", "message"}`. The server only asks the provider about a flight from two
days before departure until a day after it, and caches each answer, so a small free quota lasts.

| Provider | Free tier (checked Oct 2026) | Notes |
| --- | --- | --- |
| AeroDataBox (RapidAPI / API.market) | about 400 units a month; one status lookup costs about 2 | Gates, terminals, revised times, baggage belt. |
| AviationStack | 100 requests a month | The free plan is **HTTP only**, so the key crosses the network unencrypted. Paid plans support HTTPS (set the base URL to `https://api.aviationstack.com/v1`). |
| FlightAware AeroAPI | Pay per query; needs a card on file | Most complete data. |
| OpenSky Network | Free | **Not supported**: it has live positions by transponder only, with no schedules, gates or delays. |

The server reaches only the provider host; no URL comes from users.


AeroDataBox channels: RapidAPI is the default gateway. For a key bought directly from aerodatabox.com, set `TRIPPY_FLIGHT_STATUS_BASE_URL=https://api.aerodatabox.com` (key sent as `X-Api-Key`). For API.Market, set `TRIPPY_FLIGHT_STATUS_BASE_URL=https://prod.api.market/api/v1/aedbx/aerodatabox` (key sent as `x-api-market-key`).
