# Accounts and sharing

## Sign-in
- Email + password. Passwords are hashed with Argon2id (argon2-cffi) and must be 8–256 characters.
- `POST /auth/signup`, `/auth/login` and `/auth/refresh` return an access token (JWT, HS256, 30 minutes) and a refresh token (60 days). The iOS app keeps both in the Keychain and refreshes automatically on a 401.
- `POST /auth/logout` and every password change or reset end **all** sessions (a per-user `token_version` claim).
- The signing key comes from `TRIPPY_JWT_SECRET`, or else a file (`TRIPPY_SECRET_FILE`, `/data/jwt-secret` in Docker) created on first start with mode 600.
- Rate limits per IP, in-process: signup 10/hour, login 10 per 5 min, refresh 60 per 5 min, forgot 5 per 15 min, reset 10 per 15 min, URL imports 20 per 5 min. Over the limit you get 429 with Retry-After.
- **Forgot password**: `POST /auth/forgot` always answers the same way. The reset code (`XXXXXX-XXXXXX-XXXXXX`, valid 1 hour, single use, stored hashed) is written to the server log (`docker logs trippy-api`), because there is no email sender yet (TODO: SMTP). With `TRIPPY_DEV_MODE=1` the code is also returned in the response.
- **Sign in with Apple**: TODO. It needs a paid Apple Developer account for the capability.
- **Delete account** (`DELETE /me` with your password): deletes trips you own and bookings that aren't on a trip. On trips and groups shared with others you stay in their ledgers as "Former member", so their balances don't change. Your email can be used again.

## Who sees what
- **Trips**: the owner and the travelers on it. Anything else returns 404, so ids don't leak.
- **Flights, rental cars, hotels**: their owner, plus everyone on the trip they're attached to.
- **Expenses**: the payer, people in the split, and members of the trip or group it belongs to.
- **Groups, IOUs and settlements**: group members.
- **People** (`/users/`): you plus everyone you share a trip or group with.
- Only the trip owner can delete a trip or remove other travelers. Anyone can leave a trip.

## Inviting people
On a trip, Add traveler with a name and email:
- If that email has an account, the person joins the trip right away.
- If not, a pending invite is created (`GET /trips/{id}/invites`). When someone signs up with that email, they take over that person and see the trip and their share of expenses.
- Without an email, the person is a placeholder (like Maya and Sam) who can't log in. Add an email later to invite them.

There's no email verification yet. Anyone who signs up with an invited address gets the invite, so only share the server with people you trust until SMTP and verification exist.

## Existing data
The `d3a7c1e5f202` migration marks every existing person as a placeholder. The person who owns the most trips becomes the **legacy owner**, and standalone flights, rentals and groups are assigned to them. On a server started with `TRIPPY_FIRST_SIGNUP_CLAIMS_LEGACY=1` (set in docker-compose.yml), the **first** account created takes over the legacy owner and all its data. Everyone else stays a placeholder until invited.

## Development
- `TRIPPY_DEV_AUTH_BYPASS=1`: requests without a token act as the dev user (`TRIPPY_DEV_USER_EMAIL`, else the legacy owner). Only for local screenshots; never on a shared network.
- `TRIPPY_SEED_DEMO=1`: seed demo data on an empty database.
