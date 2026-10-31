# iOS API base URL

The app talks to one Trippy server. People pick it in the app. Builds ship with a default.

## Resolution order (`APIConfig.baseURL`)

1. Process environment variable `TRIPPY_API_BASE_URL` (Xcode scheme or `simctl launch`). Wins when set.
2. In-app choice. Tap the **Server** row on the welcome, sign-up, or log-in screen, or go to **Profile > Server**. This value is stored in UserDefaults key `TrippyAPIBaseURLOverride`. **Reset to default** clears it.
3. Info.plist key `TRIPPY_API_BASE_URL`, from the `TRIPPY_API_BASE_URL` build setting: empty in `ios-xcode/Base.xcconfig`, set yours in the gitignored `ios-xcode/Local.xcconfig` (copy `Local.xcconfig.example`).
4. `APIConfig.defaultBaseURL`: `http://localhost:8000`. This matches `docker compose up` on the Mac running the Simulator.

Trailing slashes are stripped. A missing scheme becomes `http://`.

## Server check

The Server row and **Test connection** call `GET /health`. They accept the server only if the response is
`{"status":"healthy","service":"trippy",...}`. They then show the server's `version` and `signup` mode.
On invite-only or closed servers, the sign-up screen explains who can sign up. The forgot-password screen
says where the code goes, based on `password_reset` (`email` or `server-log`).

## ATS (plain HTTP)

`project.yml` sets `NSAllowsLocalNetworking`, which allows plain HTTP to `.local` hosts, unqualified
hostnames, and IP addresses. There are no per-host exceptions. Public and Tailscale
servers should use HTTPS. See `SELF_HOSTING.md` for Caddy, Cloudflare Tunnel, and `tailscale serve`.
`NSLocalNetworkUsageDescription` is set, so iOS asks for Local Network access the first time.

## Running the server

See `SELF_HOSTING.md`.
