#!/bin/sh
# Bring the schema up to date (Alembic), then serve on port 8000.
set -e
cd /srv/trippy

if [ "${TRIPPY_DATABASE_URL#sqlite:}" != "$TRIPPY_DATABASE_URL" ]; then
  DB_FILE="${TRIPPY_DATABASE_URL#sqlite:///}"
  DATA_DIR=$(dirname "$DB_FILE")
  for f in "$DATA_DIR" "$DB_FILE" "${TRIPPY_SECRET_FILE:-}"; do
    [ -n "$f" ] && [ -e "$f" ] || continue
    if ! [ -w "$f" ] || ! [ -r "$f" ]; then
      echo "trippy: can't read and write $f as uid $(id -u)." >&2
      echo "trippy: bind mount: sudo chown -R $(id -u):$(id -g) /path/to/trippy-data" >&2
      echo "trippy: named volume (e.g. after docker compose cp): docker compose run --rm --user root --entrypoint chown api -R $(id -u):$(id -g) /data" >&2
      exit 1
    fi
  done
fi

alembic upgrade head
# Behind a reverse proxy on another host or container, set TRIPPY_FORWARDED_ALLOW_IPS to its address
# (or "*" if only the proxy can reach this port) so rate limits see real client IPs.
if [ -n "${TRIPPY_LISTEN:-}" ]; then
  # Host networking, specific addresses that may appear late (see app/listen.py).
  exec python -m app.listen
fi
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-server-header \
  --proxy-headers --forwarded-allow-ips "${TRIPPY_FORWARDED_ALLOW_IPS:-127.0.0.1}"
