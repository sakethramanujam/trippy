"""/auth/* and /me endpoints."""
from __future__ import annotations

import re
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import auth, invites, mailer, models, schemas
from .auth import RateLimiter, get_current_user
from .database import get_db

router = APIRouter()

signup_limit = RateLimiter("signup", limit=10, window_seconds=3600)
login_limit = RateLimiter("login", limit=10, window_seconds=300)
refresh_limit = RateLimiter("refresh", limit=60, window_seconds=300)
redeem_limit = RateLimiter("redeem", limit=10, window_seconds=900)
forgot_limit = RateLimiter("forgot", limit=5, window_seconds=900)
reset_limit = RateLimiter("reset", limit=10, window_seconds=900)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
IATA_RE = re.compile(r"^[A-Z]{3}$")


def profile(user: models.User) -> schemas.Profile:
    return schemas.Profile(id=user.id, email=user.email, name=user.display_name or user.username,
                           initials=auth.initials(user), home_airport=user.home_airport,
                           created_at=user.created_at)


def _auth_response(user: models.User, claimed: list[str] | None = None) -> dict:
    return {**auth.issue_tokens(user), "user": profile(user), "claimed": claimed or []}


def _clean_airport(code: str | None) -> str | None:
    if code is None:
        return None
    code = code.strip().upper()
    if not code:
        return None
    if not IATA_RE.match(code):
        raise HTTPException(status_code=400, detail="Home airport should be a 3-letter code like SFO")
    return code


def _unique_username(db: Session, base: str) -> str:
    base = re.sub(r"[^a-z0-9]+", ".", base.lower()).strip(".") or "traveler"
    name, n = base, 2
    while db.query(models.User).filter(func.lower(models.User.username) == name).first():
        name, n = f"{base}{n}", n + 1
    return name


def _by_email(db: Session, email: str) -> models.User | None:
    return db.query(models.User).filter(func.lower(models.User.email) == email).first()


@router.post("/auth/signup", response_model=schemas.AuthResponse, status_code=201,
             dependencies=[Depends(signup_limit)])
def signup(body: schemas.SignUp, db: Session = Depends(get_db)):
    email = auth.normalize_email(body.email)
    name = body.name.strip()
    if not EMAIL_RE.match(email) or email.endswith(auth.PLACEHOLDER_DOMAIN):
        raise HTTPException(status_code=400, detail="Enter a valid email address")
    if not name:
        raise HTTPException(status_code=400, detail="Enter your name")
    auth.check_password_strength(body.password)
    airport = _clean_airport(body.home_airport)

    claimed: list[str] = []
    user = _by_email(db, email)
    if user is not None and not user.is_placeholder:
        raise HTTPException(status_code=409, detail="An account with that email already exists. Log in instead.")
    mode = auth.signup_mode()
    allowlisted = auth.signup_allowlisted(email)
    invite = invites.find(db, body.invite_code) if body.invite_code else None
    if body.invite_code and invite is None:
        raise HTTPException(status_code=403, detail="That invite code isn't valid or has expired. Ask for a new one.")
    if invite is not None and mode == "closed" and not allowlisted:
        raise HTTPException(status_code=403, detail="Sign-ups are closed on this server.")
    if invite is not None:
        # The code names the traveler being claimed; a different placeholder with this email would clash.
        if user is not None and user.id != invite.user_id:
            raise HTTPException(status_code=409, detail="That email belongs to a different invite. "
                                                        "Sign up with the email you were invited with.")
        user = db.get(models.User, invite.user_id)
    elif user is not None and not allowlisted:
        # Taking over a placeholder hands over every trip/expense attached to it. Knowing the
        # address isn't proof of owning it, so a one-time invite code (or the allowlist) is required.
        raise HTTPException(status_code=403, detail="You've been invited. Enter the invite code from the "
                                                    "person who added you to sign up.")
    if user is not None:
        # This account takes over the invited traveler and everything attached to it.
        invites.mark_claimed(db, user.id)
        claimed.append(f"{len(user.trips) + len(user.participating_trips)} trip(s) you were invited to")
    else:
        has_accounts = db.query(models.User).filter(models.User.is_placeholder.is_(False)).first() is not None
        if has_accounts and mode != "open" and not allowlisted:
            detail = ("This server is invite-only. Ask someone on it to add you to a trip and share an invite code."
                      if mode == "invite" else "Sign-ups are closed on this server.")
            raise HTTPException(status_code=403, detail=detail)
        legacy = db.query(models.User).filter(models.User.legacy_owner.is_(True),
                                              models.User.is_placeholder.is_(True)).first()
        if legacy is not None and not has_accounts and auth.first_signup_claims_legacy():
            user = legacy
            claimed.append("existing Trippy data (first account on this server)")
        else:
            user = models.User(username=_unique_username(db, email.split("@")[0]))
            db.add(user)
    user.email = email
    user.display_name = name
    if airport:
        user.home_airport = airport
    user.hashed_password = auth.hash_password(body.password)
    user.is_placeholder = False
    user.token_version = (user.token_version or 0) + 1
    if user.created_at is None:
        user.created_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return _auth_response(user, claimed)


_DUMMY_HASH = auth.hash_password("dummy-password-for-timing-only")


@router.post("/auth/login", response_model=schemas.AuthResponse, dependencies=[Depends(login_limit)])
def login(body: schemas.LogIn, db: Session = Depends(get_db)):
    user = _by_email(db, auth.normalize_email(body.email))
    if user is None or user.is_placeholder:
        auth.verify_password(_DUMMY_HASH, body.password)  # same argon2 cost: no timing hint the account exists
        raise HTTPException(status_code=401, detail="Email or password is incorrect")
    if not auth.verify_password(user.hashed_password, body.password):
        raise HTTPException(status_code=401, detail="Email or password is incorrect")
    return _auth_response(user)


@router.post("/auth/refresh", response_model=schemas.AuthResponse, dependencies=[Depends(refresh_limit)])
def refresh(body: schemas.RefreshRequest, db: Session = Depends(get_db)):
    user = auth.user_from_token(db, body.refresh_token, "refresh")
    return _auth_response(user)


@router.post("/auth/logout", status_code=204)
def logout(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Signs out everywhere: every token issued so far stops working."""
    user.token_version = (user.token_version or 0) + 1
    db.commit()


@router.post("/auth/forgot", dependencies=[Depends(forgot_limit)])
def forgot(body: schemas.ForgotPassword, background: BackgroundTasks, db: Session = Depends(get_db)):
    email = auth.normalize_email(body.email)
    user = _by_email(db, email)
    delivery = "email" if mailer.configured() else "server-log"
    out = {"ok": True, "detail": "If that email has an account, a reset code is on its way.", "delivery": delivery}
    if user is not None and not user.is_placeholder:
        token = auth.create_reset_token(db, user)
        if mailer.configured():
            background.add_task(mailer.send_reset_code, email, token)
        else:
            auth.log_reset_token(email, token)
        if auth.dev_mode():
            out["dev_reset_token"] = token
    return out


@router.post("/auth/reset", response_model=schemas.AuthResponse, dependencies=[Depends(reset_limit)])
def reset(body: schemas.ResetPassword, db: Session = Depends(get_db)):
    auth.check_password_strength(body.password)
    user = auth.consume_reset_token(db, body.token)
    if user is None or user.is_placeholder:
        raise HTTPException(status_code=400, detail="That reset code is invalid or has expired")
    user.hashed_password = auth.hash_password(body.password)
    user.token_version = (user.token_version or 0) + 1  # sign out other devices
    db.commit()
    db.refresh(user)
    return _auth_response(user)


# TODO(Sign in with Apple): needs a paid Apple Developer account (Services ID + key). Add
# POST /auth/apple that verifies the identity token against Apple's JWKS and links by `sub`.


@router.get("/me", response_model=schemas.Profile)
def me(user: models.User = Depends(get_current_user)):
    return profile(user)


@router.patch("/me", response_model=schemas.Profile)
def update_me(body: schemas.ProfileUpdate, user: models.User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    if body.name is not None:
        if not body.name.strip():
            raise HTTPException(status_code=400, detail="Name can't be empty")
        user.display_name = body.name.strip()
    if body.home_airport is not None:
        user.home_airport = _clean_airport(body.home_airport)
    db.commit()
    db.refresh(user)
    return profile(user)


@router.post("/me/password", response_model=schemas.AuthResponse, dependencies=[Depends(login_limit)])
def change_password(body: schemas.ChangePassword, user: models.User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    if not auth.verify_password(user.hashed_password, body.current_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    auth.check_password_strength(body.new_password)
    user.hashed_password = auth.hash_password(body.new_password)
    user.token_version = (user.token_version or 0) + 1
    db.commit()
    db.refresh(user)
    return _auth_response(user)


@router.delete("/me", status_code=204, dependencies=[Depends(login_limit)])
def delete_me(body: schemas.DeleteAccount, user: models.User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    """Deletes your trips, rentals, flights and stays. Shared expenses stay on other people's
    ledgers under "Former member" so their balances don't change."""
    from . import crud

    if not auth.verify_password(user.hashed_password, body.password):
        raise HTTPException(status_code=400, detail="Password is incorrect")
    for trip in list(user.trips):
        crud.delete_trip(db, trip)  # commits
    for model in (models.RentalCar, models.Flight, models.Lodging):
        db.query(model).filter(model.owner_id == user.id, model.trip_id.is_(None)).delete()
        db.query(model).filter(model.owner_id == user.id).update({model.owner_id: None})
    db.query(models.Group).filter(models.Group.owner_id == user.id).update({models.Group.owner_id: None})
    db.query(models.PasswordReset).filter(models.PasswordReset.user_id == user.id).delete()
    db.query(models.InboundEmail).filter(models.InboundEmail.user_id == user.id).delete()
    db.query(models.Journey).filter(models.Journey.owner_id == user.id).delete()
    db.query(models.TripPin).filter(models.TripPin.user_id == user.id).delete()
    db.query(models.DismissedSuggestion).filter(models.DismissedSuggestion.user_id == user.id).delete()
    db.query(models.TripStory).filter(models.TripStory.user_id == user.id).delete()
    db.query(models.Drive).filter(models.Drive.owner_id == user.id).delete()
    db.query(models.TripPhoto).filter(models.TripPhoto.user_id == user.id).delete(synchronize_session=False)
    db.query(models.TripInvite).filter(models.TripInvite.invited_by_id == user.id).update(
        {models.TripInvite.invited_by_id: None})
    user.email = f"deleted-{user.id}{auth.PLACEHOLDER_DOMAIN}"
    user.username = f"former.member.{user.id}"
    user.display_name = "Former member"
    user.home_airport = None
    user.inbound_token = None
    user.hashed_password = "!deleted"
    user.is_placeholder = True
    user.legacy_owner = False
    user.token_version = (user.token_version or 0) + 1
    db.commit()


@router.post("/invites/redeem", response_model=schemas.InviteRedeemed, dependencies=[Depends(redeem_limit)])
def redeem_invite(body: schemas.InviteRedeem, me: models.User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    """Someone who already has an account joins a trip with an invite code: they take the invited
    traveler's place (trips, groups, expenses). Nothing is linked to an account without its consent."""
    invite = invites.find(db, body.code)
    if invite is None:
        raise HTTPException(status_code=404, detail="That invite code isn't valid or has expired. Ask for a new one.")
    trip_id = invite.trip_id
    joined = invites.absorb(db, db.get(models.User, invite.user_id), me)
    return {"trip_id": trip_id, "joined": joined}
