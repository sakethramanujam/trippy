# Trippy API (FastAPI + SQLite). Self-hosting guide: SELF_HOSTING.md
#
# Multi-arch: python:3.12-slim and every dependency ship amd64 and arm64 builds, so this works on
# x86 servers, Raspberry Pi 4/5 and Apple Silicon. Build both at once with:
#   docker buildx build --platform linux/amd64,linux/arm64 -t trippy-api .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TRIPPY_DATABASE_URL=sqlite:////data/trippy.db \
    TRIPPY_SECRET_FILE=/data/jwt-secret

WORKDIR /srv/trippy
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .
# The email importer reuses the rental mapper from this script.
COPY scripts/import_rentals.py ./scripts/import_rentals.py
COPY scripts/retitle_trips.py ./scripts/retitle_trips.py
COPY deploy/entrypoint.sh /usr/local/bin/trippy-entrypoint

# Runs as an unprivileged user. Everything it writes (database, JWT secret) lives in /data.
ARG TRIPPY_UID=10001
RUN chmod 755 /usr/local/bin/trippy-entrypoint \
 && groupadd --system --gid "${TRIPPY_UID}" trippy \
 && useradd --system --uid "${TRIPPY_UID}" --gid trippy --home-dir /srv/trippy --shell /usr/sbin/nologin trippy \
 && mkdir -p /data && chown trippy:trippy /data
USER trippy

EXPOSE 8000
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"
ENTRYPOINT ["trippy-entrypoint"]
