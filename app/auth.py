"""Accounts: argon2 password hashing, JWT access/refresh tokens, rate limits, current user.

Environment:
  TRIPPY_JWT_SECRET            signing key; otherwise read/created at TRIPPY_SECRET_FILE
  TRIPPY_SECRET_FILE           default ./trippy-jwt-secret (Docker: /data/jwt-secret)
  TRIPPY_DEV_MODE=1            password-reset tokens are returned in the API response
  TRIPPY_DEV_AUTH_BYPASS=1     requests without a token act as the dev user (screenshots only!)
  TRIPPY_DEV_USER_EMAIL        which account the bypass uses (default: the legacy owner)
  TRIPPY_FIRST_SIGNUP_CLAIMS_LEGACY=1
                               the first account created claims the pre-accounts data
  TRIPPY_SIGNUP_MODE           open (default) | invite | closed. The first account can always sign up.
  TRIPPY_SIGNUP_ALLOWLIST      comma-separated emails or @domains that may sign up in any mode
"""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import models
from .database import get_db

log = logging.getLogger("trippy.auth")

ACCESS_TTL = timedelta(minutes=30)
REFRESH_TTL = timedelta(days=60)
RESET_TTL = timedelta(hours=1)
ALGORITHM = "HS256"
PLACEHOLDER_DOMAIN = "@travelers.trippy.local"

_hasher = PasswordHasher()
_bearer = HTTPBearer(auto_error=False)


def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def dev_mode() -> bool:
    return _flag("TRIPPY_DEV_MODE")


_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def dev_bypass() -> bool:
    if not _flag("TRIPPY_DEV_AUTH_BYPASS"):
        return False
    bind = os.getenv("TRIPPY_BIND", "127.0.0.1").strip()
    if bind and bind not in _LOOPBACK_HOSTS:
        raise RuntimeError(f"TRIPPY_DEV_AUTH_BYPASS=1 is refused when TRIPPY_BIND={bind!r} (loopback only)")
    for addr in os.getenv("TRIPPY_LISTEN", "").split(","):
        host = addr.strip().rsplit(":", 1)[0].strip("[]")
        if host and host not in _LOOPBACK_HOSTS:
            raise RuntimeError(f"TRIPPY_DEV_AUTH_BYPASS=1 is refused when TRIPPY_LISTEN includes {addr.strip()!r}")
    return True


def first_signup_claims_legacy() -> bool:
    return _flag("TRIPPY_FIRST_SIGNUP_CLAIMS_LEGACY")


SIGNUP_MODES = ("open", "invite", "closed")


def signup_mode() -> str:
    """open: anyone can sign up. invite: only emails someone added to a trip (or the allowlist).
    closed: nobody but the allowlist, after the first account."""
    mode = os.getenv("TRIPPY_SIGNUP_MODE", "open").strip().lower() or "open"
    if mode not in SIGNUP_MODES:
        raise RuntimeError(f"TRIPPY_SIGNUP_MODE must be one of {', '.join(SIGNUP_MODES)}, not {mode!r}")
    return mode


def signup_allowlisted(email: str) -> bool:
    for entry in os.getenv("TRIPPY_SIGNUP_ALLOWLIST", "").split(","):
        entry = entry.strip().lower()
        if entry and (email == entry or (entry.startswith("@") and email.endswith(entry))):
            return True
    return False


def first_signup_allowed(email: str) -> bool:
    """When TRIPPY_SIGNUP_ALLOWLIST is set, even the first account on an empty server must match it."""
    raw = os.getenv("TRIPPY_SIGNUP_ALLOWLIST", "").strip()
    if not raw:
        return True
    return signup_allowlisted(email)


_secret_cache: Optional[str] = None


def secret_key() -> str:
    global _secret_cache
    if _secret_cache:
        return _secret_cache
    env = os.getenv("TRIPPY_JWT_SECRET", "").strip()
    if env:
        _secret_cache = env
        return env
    path = os.getenv("TRIPPY_SECRET_FILE", "./trippy-jwt-secret")
    try:
        with open(path) as f:
            value = f.read().strip()
    except FileNotFoundError:
        value = ""
    if len(value) < 32:
        value = secrets.token_urlsafe(48)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(value)
    _secret_cache = value
    return value


# --- Passwords --------------------------------------------------------------

def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(hashed: Optional[str], password: str) -> bool:
    if not hashed or not hashed.startswith("$argon2"):
        return False
    try:
        return _hasher.verify(hashed, password)
    except (VerificationError, InvalidHashError):
        return False


def check_password_strength(password: str) -> None:
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Use at least 8 characters for your password")
    if len(password) > 256:
        raise HTTPException(status_code=400, detail="That password is too long")


# --- Tokens -----------------------------------------------------------------

_used_refresh_jtis: dict[str, int] = {}
_refresh_lock = threading.Lock()
_MAX_USED_REFRESH_JTIS = 4096


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _encode(user: models.User, kind: str, ttl: timedelta) -> str:
    now = _now()
    payload = {"sub": str(user.id), "type": kind, "ver": user.token_version or 0,
               "iat": now, "exp": now + ttl, "jti": uuid.uuid4().hex}
    return jwt.encode(payload, secret_key(), algorithm=ALGORITHM)


def issue_tokens(user: models.User) -> dict:
    return {
        "access_token": _encode(user, "access", ACCESS_TTL),
        "refresh_token": _encode(user, "refresh", REFRESH_TTL),
        "token_type": "bearer",
        "expires_in": int(ACCESS_TTL.total_seconds()),
    }


def _decode_token_payload(db: Session, token: str, kind: str) -> tuple[models.User, dict]:
    try:
        payload = jwt.decode(token, secret_key(), algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired",
                            headers={"WWW-Authenticate": "Bearer"})
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token", headers={"WWW-Authenticate": "Bearer"})
    if payload.get("type") != kind:
        raise HTTPException(status_code=401, detail="Wrong token type", headers={"WWW-Authenticate": "Bearer"})
    user = db.get(models.User, int(payload.get("sub", 0)))
    if user is None or user.is_placeholder or (user.token_version or 0) != payload.get("ver"):
        raise HTTPException(status_code=401, detail="Session is no longer valid",
                            headers={"WWW-Authenticate": "Bearer"})
    return user, payload


def user_from_token(db: Session, token: str, kind: str) -> models.User:
    user, _ = _decode_token_payload(db, token, kind)
    return user


def consume_refresh_token(db: Session, token: str) -> models.User:
    """Validate and rotate a refresh token. Replaying an already-consumed refresh token revokes
    all sessions for that user (reuse detection)."""
    user, payload = _decode_token_payload(db, token, "refresh")
    jti = payload.get("jti")
    if jti:
        with _refresh_lock:
            if jti in _used_refresh_jtis:
                user.token_version = (user.token_version or 0) + 1
                db.commit()
                raise HTTPException(status_code=401, detail="Session is no longer valid",
                                    headers={"WWW-Authenticate": "Bearer"})
            while len(_used_refresh_jtis) >= _MAX_USED_REFRESH_JTIS:
                _used_refresh_jtis.pop(next(iter(_used_refresh_jtis)))
            _used_refresh_jtis[jti] = user.id
    return user


def _dev_user(db: Session) -> Optional[models.User]:
    email = os.getenv("TRIPPY_DEV_USER_EMAIL", "").strip()
    q = db.query(models.User)
    if email:
        return q.filter(func.lower(models.User.email) == email.lower()).first()
    return (q.filter(models.User.legacy_owner.is_(True)).first()
            or q.filter(models.User.is_placeholder.is_(False)).order_by(models.User.id).first()
            or q.order_by(models.User.id).first())


def get_current_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
                     db: Session = Depends(get_db)) -> models.User:
    if creds is None or not creds.credentials:
        if dev_bypass():
            user = _dev_user(db)
            if user is not None:
                return user
        raise HTTPException(status_code=401, detail="Not signed in", headers={"WWW-Authenticate": "Bearer"})
    return user_from_token(db, creds.credentials, "access")


# --- Password reset ---------------------------------------------------------

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_reset_token(db: Session, user: models.User) -> str:
    # Short, typeable code (no mail sender yet, so people copy it from the server log).
    token = "-".join(secrets.token_hex(3).upper() for _ in range(3))
    db.add(models.PasswordReset(user_id=user.id, token_hash=_hash_token(token),
                                expires_at=datetime.utcnow() + RESET_TTL))
    db.commit()
    return token


def consume_reset_token(db: Session, token: str) -> Optional[models.User]:
    row = (db.query(models.PasswordReset)
           .filter(models.PasswordReset.token_hash == _hash_token(token.strip().upper())).first())
    if row is None or row.used_at is not None or row.expires_at < datetime.utcnow():
        return None
    row.used_at = datetime.utcnow()
    return db.get(models.User, row.user_id)


# --- Rate limiting (in-process; one container) ------------------------------

class RateLimiter:
    """Sliding-window limit per client IP (and optional secondary key like email) and bucket. Raises 429 with Retry-After."""

    MAX_KEYS = 4096
    _hits: dict[tuple[str, str], deque] = defaultdict(deque)
    _lock = threading.Lock()

    def __init__(self, bucket: str, limit: int, window_seconds: int):
        self.bucket, self.limit, self.window = bucket, limit, window_seconds

    def hit(self, subject: str) -> None:
        key = (self.bucket, subject or "unknown")
        now = time.monotonic()
        with self._lock:
            q = self._hits.get(key)
            if q is not None:
                while q and now - q[0] > self.window:
                    q.popleft()
                if not q:
                    self._hits.pop(key, None)
                    q = None
            if q is None:
                if len(self._hits) >= self.MAX_KEYS:
                    # Sweep expired entries first; if still full, evict oldest inserted key.
                    expired = [k for k, dq in self._hits.items() if not dq or now - dq[-1] > self.window]
                    for k in expired:
                        self._hits.pop(k, None)
                    while len(self._hits) >= self.MAX_KEYS:
                        self._hits.pop(next(iter(self._hits)))
                q = self._hits[key]
            if len(q) >= self.limit:
                retry = int(self.window - (now - q[0])) + 1
                raise HTTPException(status_code=429, detail="Too many attempts. Try again in a minute.",
                                    headers={"Retry-After": str(retry)})
            q.append(now)

    def __call__(self, request: Request) -> None:
        ip = request.client.host if request.client else "unknown"
        self.hit(ip)

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._hits.clear()


# --- Helpers ----------------------------------------------------------------

def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def initials(user: models.User) -> str:
    name = (user.display_name or user.username or user.email or "?").strip()
    parts = [p for p in name.replace(".", " ").split() if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    return name[:2].upper()


def log_reset_token(email: str, token: str) -> None:
    # Used when SMTP isn't configured: the code goes to the server log (docker logs trippy-api).
    log.warning("Password reset code for %s: %s (valid %d min)", email, token, RESET_TTL.seconds // 60)
