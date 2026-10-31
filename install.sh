#!/usr/bin/env sh
# Trippy API installer: writes .env (once), builds the image and starts it with Docker Compose.
# Usage:  ./install.sh [--port 8000] [--lan] [--signup open|invite|closed]
#                     [--email-in off|imap|smtp] [--imap-host H] [--imap-user U] [--imap-port 993]
#                     [--imap-security ssl|starttls|none] [--imap-folder INBOX] [--address-template T]
# Run it again any time to rebuild and upgrade; your .env and data are kept.
# --email-in imap asks for anything you left out (the password is never taken as a flag;
# it's read from TRIPPY_INBOUND_IMAP_PASSWORD or typed at the prompt). See SELF_HOSTING.md → Email-in.
set -eu
cd "$(dirname "$0")"

PORT=""; BIND=""; SIGNUP=""
EMAIL_IN=""; IMAP_HOST=""; IMAP_USER=""; IMAP_PORT=""; IMAP_SECURITY=""; IMAP_FOLDER=""; ADDR_TEMPLATE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --lan) BIND="0.0.0.0"; shift ;;
    --signup) SIGNUP="$2"; shift 2 ;;
    --email-in) EMAIL_IN="$2"; shift 2 ;;
    --imap-host) IMAP_HOST="$2"; shift 2 ;;
    --imap-user) IMAP_USER="$2"; shift 2 ;;
    --imap-port) IMAP_PORT="$2"; shift 2 ;;
    --imap-security) IMAP_SECURITY="$2"; shift 2 ;;
    --imap-folder) IMAP_FOLDER="$2"; shift 2 ;;
    --address-template) ADDR_TEMPLATE="$2"; shift 2 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

command -v docker >/dev/null 2>&1 || { echo "Docker isn't installed: https://docs.docker.com/engine/install/" >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "Docker Compose v2 is required (docker compose ...)." >&2; exit 1; }

set_var() {  # set_var KEY VALUE  -> replaces KEY=... in .env
  tmp=$(mktemp); grep -v "^$1=" .env > "$tmp" || true; echo "$1=$2" >> "$tmp"; mv "$tmp" .env
}

if [ ! -f .env ]; then
  cp .env.example .env
  if command -v openssl >/dev/null 2>&1; then secret=$(openssl rand -hex 32)
  else secret=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'); fi
  set_var TRIPPY_JWT_SECRET "$secret"
  chmod 600 .env
  echo "Created .env (keep it private; it holds the signing key)."
fi
[ -n "$PORT" ] && set_var TRIPPY_PORT "$PORT"
[ -n "$BIND" ] && set_var TRIPPY_BIND "$BIND"
[ -n "$SIGNUP" ] && set_var TRIPPY_SIGNUP_MODE "$SIGNUP"

ask() {  # ask VAR "Question" default  -> only when a terminal is attached and VAR is empty
  eval "cur=\${$1}"
  if [ -z "$cur" ] && [ -t 0 ]; then
    printf "%s [%s]: " "$2" "$3"; read -r ans; eval "$1=\${ans:-\$3}"
  elif [ -z "$cur" ]; then eval "$1=\$3"; fi
}
case "$EMAIL_IN" in
  "") ;;
  off) set_var TRIPPY_INBOUND_MODE off; echo "Email-in is off." ;;
  imap)
    ask IMAP_HOST "IMAP server (e.g. imap.fastmail.com, imap.gmail.com, 127.0.0.1 for Proton Bridge)" ""
    ask IMAP_USER "Mailbox user name" ""
    ask IMAP_SECURITY "Security: ssl, starttls or none" "ssl"
    if [ "$IMAP_SECURITY" = "ssl" ]; then dp=993; else dp=143; fi
    ask IMAP_PORT "Port" "$dp"
    ask IMAP_FOLDER "Folder to read" "INBOX"
    ask ADDR_TEMPLATE "Per-user address, {token} is replaced (empty = match senders only), e.g. trips+{token}@example.com" ""
    [ -n "$IMAP_HOST" ] && [ -n "$IMAP_USER" ] || { echo "--email-in imap needs --imap-host and --imap-user" >&2; exit 2; }
    pw="${TRIPPY_INBOUND_IMAP_PASSWORD:-}"
    if [ -z "$pw" ] && [ -t 0 ]; then
      printf "Mailbox password (an app password; input hidden, Enter keeps the saved one): "
      stty -echo; read -r pw; stty echo; echo
    fi
    set_var TRIPPY_INBOUND_MODE imap
    set_var TRIPPY_INBOUND_IMAP_HOST "$IMAP_HOST"
    set_var TRIPPY_INBOUND_IMAP_USERNAME "$IMAP_USER"
    set_var TRIPPY_INBOUND_IMAP_SECURITY "$IMAP_SECURITY"
    set_var TRIPPY_INBOUND_IMAP_PORT "$IMAP_PORT"
    set_var TRIPPY_INBOUND_IMAP_FOLDER "$IMAP_FOLDER"
    set_var TRIPPY_INBOUND_ADDRESS_TEMPLATE "$ADDR_TEMPLATE"
    [ -n "$pw" ] && set_var TRIPPY_INBOUND_IMAP_PASSWORD "$pw"
    chmod 600 .env
    echo "Email-in: polling $IMAP_USER on $IMAP_HOST. Processed mail is marked read and moved to Trippy-Processed." ;;
  smtp)
    ask ADDR_TEMPLATE "Per-user address on a domain whose MX points here, e.g. {token}@trips.example.com" ""
    set_var TRIPPY_INBOUND_MODE smtp
    set_var TRIPPY_INBOUND_ADDRESS_TEMPLATE "$ADDR_TEMPLATE"
    echo "Email-in: built-in SMTP receiver on container port 2525. To receive internet mail you must publish it"
    echo "(docker-compose.smtp.yml) and forward port 25 to it; read SELF_HOSTING.md → Email-in first." ;;
  *) echo "--email-in must be off, imap or smtp" >&2; exit 2 ;;
esac

if grep -q '^TRIPPY_INBOUND_MODE=smtp' .env && [ -f docker-compose.smtp.yml ]; then
  docker compose -f docker-compose.yml -f docker-compose.smtp.yml up -d --build
else
  docker compose up -d --build
fi

port=$(grep '^TRIPPY_PORT=' .env | cut -d= -f2); port=${port:-8000}
printf "Waiting for the API on port %s" "$port"
i=0
while [ $i -lt 60 ]; do
  if curl -fsS "http://127.0.0.1:$port/health" >/dev/null 2>&1; then
    echo; echo "Trippy is up: http://127.0.0.1:$port/health"
    echo "In the app, tap the Server row on the welcome screen and enter this server's address."
    echo "The first account you create becomes the first user of this server."
    exit 0
  fi
  printf "."; sleep 2; i=$((i + 1))
done
echo; echo "The API didn't answer. Check: docker compose logs api" >&2
exit 1
