import os
from datetime import datetime, timedelta

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import access, auth, crud, inbound, invites, mailer, models, money, schemas, titles, trash, trash_routes
from .auth import get_current_user
from .auth_routes import router as auth_router
from .database import SessionLocal, engine, get_db
from .import_routes import router as import_router
from .inbound_routes import router as inbound_router
from .flight_status_routes import router as flight_status_router
from .drive_routes import router as drive_router
from .photo_routes import router as photo_router
from .journey_routes import router as journey_router
from .money_routes import router as money_router
from .story_routes import router as story_router

models.Base.metadata.create_all(bind=engine)

_DOCS = os.getenv("TRIPPY_DOCS", "1") == "1"  # set TRIPPY_DOCS=0 to hide /docs, /redoc, /openapi.json

app = FastAPI(
    title="Trippy API",
    description="API for the Trippy travel companion application (Flight tracking, reservations, shared expenses, media)",
    version="0.2.0",
    docs_url="/docs" if _DOCS else None,
    redoc_url="/redoc" if _DOCS else None,
    openapi_url="/openapi.json" if _DOCS else None,
)

MAX_BODY = int(os.getenv("TRIPPY_MAX_BODY_BYTES", str(8 * 1024 * 1024)))  # > 5 MB import + base64 overhead
# Google Maps Timeline exports are bigger than other imports; only the preview endpoint gets more room.
MAX_IMPORT_BODY = int(os.getenv("TRIPPY_MAX_IMPORT_BODY_BYTES", str(28 * 1024 * 1024)))
_BIG_BODY_PATHS = ("/import/preview",)


class _BodyLimit:
    """Reject request bodies over MAX_BODY before FastAPI buffers them (auth runs after the body is read)."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        cap = max(MAX_BODY, MAX_IMPORT_BODY) if scope.get("path") in _BIG_BODY_PATHS else MAX_BODY
        for k, v in scope.get("headers", []):
            if k == b"content-length" and v.isdigit() and int(v) > cap:
                return await _too_large(send)
        seen = 0

        async def limited():
            nonlocal seen
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > cap:
                    raise HTTPException(status_code=413, detail="Request body too large")
            return msg
        return await self.app(scope, limited, send)


async def _too_large(send):
    await send({"type": "http.response.start", "status": 413,
                "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": b'{"detail":"Request body too large"}'})

def _allowed_origins() -> list[str]:
    """TRIPPY_ALLOWED_ORIGINS: comma-separated web origins allowed to call the API from a browser.
    The iOS app isn't a browser, so it works with any value. Default: none (no browser access)."""
    raw = os.getenv("TRIPPY_ALLOWED_ORIGINS", "")
    return [o.strip().rstrip("/") for o in raw.split(",") if o.strip() and o.strip() != "*"]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
app.add_middleware(_BodyLimit)


@app.middleware("http")
async def _security_headers(request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Cache-Control", "no-store")
    return resp
app.include_router(auth_router)
app.include_router(money_router)
app.include_router(import_router)
app.include_router(story_router)
app.include_router(journey_router)
app.include_router(inbound_router)
app.include_router(trash_routes.router)
app.include_router(flight_status_router)
app.include_router(drive_router)
app.include_router(photo_router)

Me = Depends(get_current_user)


@app.on_event("startup")
def start_email_in():
    """IMAP poller or SMTP receiver, only when the admin configured TRIPPY_INBOUND_MODE."""
    inbound.start(SessionLocal)


@app.on_event("startup")
def start_trash_purge():
    """Permanently delete trips that have been in Recently Deleted for more than 30 days."""
    trash.start(SessionLocal)


@app.on_event("startup")
def seed_data():
    """Demo data for an empty database, only when TRIPPY_SEED_DEMO=1 (tests and screenshots)."""
    if not auth._flag("TRIPPY_SEED_DEMO"):
        return
    db = next(get_db())
    if not db.query(models.User).first():
        # Seed User
        user = crud.create_user(db, schemas.UserCreate(email="test@example.com", username="tester", password="password"))
        # Seed Trip
        trip_start = datetime.utcnow() + timedelta(days=5)
        trip_end = datetime.utcnow() + timedelta(days=10)
        trip = crud.create_user_trip(
            db,
            schemas.TripCreate(
                title="London Getaway",
                description="A fun trip to London",
                start_date=trip_start,
                end_date=trip_end,
            ),
            user_id=user.id,
        )
        # Seed Flight
        flight = schemas.FlightCreate(
            airline="Delta Air Lines", flight_number="DL 1234",
            departure_airport="JFK", arrival_airport="LHR",
            departure_time=trip_start,
            arrival_time=trip_start + timedelta(hours=5, minutes=30),
            aircraft_type="Narrow-body", aircraft_model="Boeing 737", aircraft_manufacturer="Boeing", delay_minutes=0, status="Scheduled",
            confirmation_number="ABC123",
            distance_miles=3459.0,
            duration_minutes=330,
            cost=780.0,
            currency="USD",
            cabin_class="economy",
            booking_source="manual",
        )
        crud.create_trip_flight(db, flight, trip_id=trip.id)
        
        # Seed Expense
        expense = schemas.ExpenseCreate(amount=45.0, description="Taxi ride to hotel", payer_id=user.id, currency="USD")
        crud.create_trip_expense(db, expense, trip_id=trip.id)

        # Seed second expense on first trip
        expense2 = schemas.ExpenseCreate(amount=120.0, description="Hertz car rental", payer_id=user.id, currency="USD")
        crud.create_trip_expense(db, expense2, trip_id=trip.id)

        # Seed Activity on first trip
        activity = schemas.ActivityCreate(
            title="Big Ben Tour",
            description="Walking tour of Westminster",
        )
        crud.create_trip_activity(db, activity, trip_id=trip.id)

        # Seed Rental Car on first trip
        rental_car = schemas.RentalCarCreate(
            rental_company="Hertz",
            car_model="Tesla Model 3",
            pickup_location="LHR Airport",
            dropoff_location="LHR Airport",
            pickup_time=trip_start,
            dropoff_time=trip_end,
            mileage_driven=312.0,
            confirmation_number="H987654",
            cost=420.0,
            currency="USD",
            vehicle_class="full_size",
            fuel_type="electric",
            pickup_odometer=12040.0,
            dropoff_odometer=12352.0,
            booking_source="manual",
        )
        crud.create_trip_rental_car(db, rental_car, trip_id=trip.id)

        # Seed second user
        user2 = crud.create_user(db, schemas.UserCreate(email="sarah@example.com", username="sarah", password="password"))

        # Add both users as participants to trip 1
        crud.add_trip_participant(db, trip_id=trip.id, user_id=user.id)
        crud.add_trip_participant(db, trip_id=trip.id, user_id=user2.id)

        # Seed split expense: Dinner at The Ivy, user 1 paid $300, split between both
        money.create_expense(
            db, amount=300.0, description="Dinner at The Ivy", payer_id=user.id,
            split_among=[user.id, user2.id], trip_id=trip.id,
        )

        # Seed split expense: Museum tickets, user 2 paid $200, split equally
        money.create_expense(
            db, amount=200.0, description="Museum tickets", payer_id=user2.id,
            split_among=[user.id, user2.id], trip_id=trip.id,
        )

        # Seed second trip
        trip2_start = datetime.utcnow() + timedelta(days=30)
        trip2 = crud.create_user_trip(
            db,
            schemas.TripCreate(
                title="Tokyo 2027",
                description="Cherry blossom season adventure",
                start_date=trip2_start,
                end_date=trip2_start + timedelta(days=14),
            ),
            user_id=user.id,
        )

        # Seed flight on second trip
        flight2 = schemas.FlightCreate(
            airline="United", flight_number="UA 837",
            departure_airport="SFO", arrival_airport="NRT",
            departure_time=trip2_start,
            arrival_time=trip2_start + timedelta(hours=11),
            aircraft_type="Wide-body", aircraft_model="Boeing 787 Dreamliner", aircraft_manufacturer="Boeing", delay_minutes=0, status="Scheduled",
            confirmation_number="UA998877",
            distance_miles=5130.0,
            duration_minutes=660,
            cost=1120.0,
            currency="USD",
            cabin_class="premium_economy",
            booking_source="manual",
        )
        crud.create_trip_flight(db, flight2, trip_id=trip2.id)


@app.get("/")
def read_root():
    return {"message": "Welcome to the Trippy API. Please check /docs for the API documentation."}

@app.get("/health")
def health_check():
    """Unauthenticated. The app's Server field calls this to check it's talking to Trippy."""
    return {"status": "healthy", "service": "trippy", "version": app.version,
            "auth": "dev-bypass" if auth.dev_bypass() else "required", "signup": auth.signup_mode(),
            "password_reset": "email" if mailer.configured() else "server-log",
            "inbound": inbound.status()}

# --- People -------------------------------------------------------------------
# Accounts are created with POST /auth/signup; people you travel with are added to trips.

@app.get("/users/", response_model=list[schemas.User])
def read_users(skip: int = 0, limit: int = 100, user: models.User = Me, db: Session = Depends(get_db)):
    """You plus everyone you share a trip or group with."""
    ids = access.known_user_ids(db, user)
    return (db.query(models.User).filter(models.User.id.in_(ids)).order_by(models.User.id)
            .offset(skip).limit(limit).all())

@app.get("/users/{user_id}", response_model=schemas.User)
def read_user(user_id: int, user: models.User = Me, db: Session = Depends(get_db)):
    return access.user_or_404(db, user_id, user)

# --- Trips --------------------------------------------------------------------

@app.post("/trips/", response_model=schemas.Trip, status_code=201)
def create_trip(trip: schemas.TripCreate, user: models.User = Me, db: Session = Depends(get_db)):
    return crud.create_user_trip(db=db, trip=trip, user_id=user.id)

@app.post("/users/{user_id}/trips/", response_model=schemas.Trip)
def create_trip_for_user(user_id: int, trip: schemas.TripCreate, user: models.User = Me,
                         db: Session = Depends(get_db)):
    """Older clients: only works for yourself. Prefer POST /trips/."""
    if user_id != user.id:
        raise HTTPException(status_code=403, detail="You can only create trips for yourself")
    return crud.create_user_trip(db=db, trip=trip, user_id=user.id)

@app.get("/trips/", response_model=list[schemas.Trip])
def read_trips(skip: int = 0, limit: int = 100, user: models.User = Me, db: Session = Depends(get_db)):
    rows = access.trips(db, user).order_by(models.Trip.id).offset(skip).limit(limit).all()
    titles.refresh(db, rows)  # auto titles follow the route as items are added or moved
    return access.mark_pinned(db, user, rows)

@app.get("/trips/{trip_id}", response_model=schemas.Trip)
def read_trip(trip_id: int, user: models.User = Me, db: Session = Depends(get_db)):
    trip = access.trip_or_404(db, trip_id, user)
    titles.refresh(db, [trip])
    return access.mark_pinned(db, user, [trip])[0]

@app.patch("/trips/{trip_id}", response_model=schemas.Trip)
def update_trip(trip_id: int, patch: schemas.TripUpdate, user: models.User = Me, db: Session = Depends(get_db)):
    """Rename a trip (owner only). A renamed trip keeps its title: auto-titling stops for it."""
    trip = access.owned_trip_or_404(db, trip_id, user)
    changes = patch.model_dump(exclude_unset=True)
    if "title" in changes:
        title = (changes["title"] or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="A trip needs a title")
        if title != trip.title:
            trip.title = title
            trip.title_auto = False
    if "description" in changes:
        trip.description = changes["description"]
    db.commit()
    db.refresh(trip)
    return access.mark_pinned(db, user, [trip])[0]

@app.post("/trips/{trip_id}/flights/", response_model=schemas.Flight)
def create_flight_for_trip(trip_id: int, flight: schemas.FlightCreate, user: models.User = Me,
                           db: Session = Depends(get_db)):
    access.trip_or_404(db, trip_id, user)
    return crud.create_trip_flight(db=db, flight=flight, trip_id=trip_id, owner_id=user.id)

@app.post("/trips/{trip_id}/expenses/", response_model=schemas.Expense)
def create_expense_for_trip(trip_id: int, expense: schemas.ExpenseCreate, user: models.User = Me,
                            db: Session = Depends(get_db)):
    trip = access.trip_or_404(db, trip_id, user)
    if expense.payer_id not in {trip.owner_id, *(p.id for p in trip.participants)}:
        raise HTTPException(status_code=400, detail="Payer must be on this trip")
    return crud.create_trip_expense(db=db, expense=expense, trip_id=trip_id)

@app.post("/trips/{trip_id}/activities/", response_model=schemas.Activity)
def create_activity_for_trip(trip_id: int, activity: schemas.ActivityCreate, user: models.User = Me,
                             db: Session = Depends(get_db)):
    access.trip_or_404(db, trip_id, user)
    return crud.create_trip_activity(db=db, activity=activity, trip_id=trip_id)

@app.post("/trips/{trip_id}/documents/", response_model=schemas.Document)
def create_document_for_trip(trip_id: int, document: schemas.DocumentCreate, user: models.User = Me,
                             db: Session = Depends(get_db)):
    access.trip_or_404(db, trip_id, user)
    return crud.create_trip_document(db=db, document=document, trip_id=trip_id)

@app.post("/trips/{trip_id}/rental_cars/", response_model=schemas.RentalCar)
def create_rental_car_for_trip(trip_id: int, rental_car: schemas.RentalCarCreate, user: models.User = Me,
                               db: Session = Depends(get_db)):
    access.trip_or_404(db, trip_id, user)
    return crud.create_trip_rental_car(db=db, rental_car=rental_car, trip_id=trip_id, owner_id=user.id)

# --- Rental Car Endpoints (standalone rental tracker) ---

@app.get("/rental_cars/", response_model=list[schemas.RentalCar])
def read_rental_cars(
    year: int | None = None,
    trip_id: int | None = None,
    company: str | None = None,
    skip: int = 0,
    limit: int = 500,
    user: models.User = Me,
    db: Session = Depends(get_db),
):
    """Your rentals and rentals on trips you're on, newest pickup first."""
    return crud.get_rental_cars(db, year=year, trip_id=trip_id, company=company, skip=skip, limit=limit,
                                base=access.rentals(db, user))

@app.get("/rental_cars/{rental_id}", response_model=schemas.RentalCar)
def read_rental_car(rental_id: int, user: models.User = Me, db: Session = Depends(get_db)):
    return access.rental_or_404(db, rental_id, user)

@app.post("/rental_cars/", response_model=schemas.RentalCar)
def create_rental_car(rental_car: schemas.RentalCarCreate, user: models.User = Me, db: Session = Depends(get_db)):
    """Create a rental that may or may not belong to a trip."""
    if rental_car.trip_id is not None:
        access.trip_or_404(db, rental_car.trip_id, user)
    return crud.create_rental_car(db, rental_car, owner_id=user.id)

@app.put("/rental_cars/external/{external_id}", response_model=schemas.RentalCar)
def upsert_rental_car(external_id: str, rental_car: schemas.RentalCarCreate, user: models.User = Me,
                      db: Session = Depends(get_db)):
    """Idempotent import: create or replace your rental with this source id."""
    if rental_car.trip_id is not None:
        access.trip_or_404(db, rental_car.trip_id, user)
    db_rental, _created = crud.upsert_rental_car_by_external_id(db, external_id, rental_car, owner_id=user.id)
    return db_rental

@app.patch("/rental_cars/{rental_id}", response_model=schemas.RentalCar)
def update_rental_car(rental_id: int, patch: schemas.RentalCarUpdate, user: models.User = Me,
                      db: Session = Depends(get_db)):
    db_rental = access.editable_rental_or_404(db, rental_id, user)
    changes = patch.model_dump(exclude_unset=True)
    if changes.get("trip_id") is not None:
        access.trip_or_404(db, changes["trip_id"], user)
    return crud.update_rental_car(db, db_rental, changes)

@app.delete("/rental_cars/{rental_id}", status_code=204)
def delete_rental_car(rental_id: int, user: models.User = Me, db: Session = Depends(get_db)):
    crud.delete_rental_car(db, access.editable_rental_or_404(db, rental_id, user))

# --- Stays (hotels / rental homes) ---

@app.post("/trips/{trip_id}/lodgings/", response_model=schemas.Lodging)
def create_lodging_for_trip(trip_id: int, lodging: schemas.LodgingCreate, user: models.User = Me,
                            db: Session = Depends(get_db)):
    access.trip_or_404(db, trip_id, user)
    return crud.create_lodging(db, lodging, owner_id=user.id, trip_id=trip_id)

@app.get("/lodgings/", response_model=list[schemas.Lodging])
def read_lodgings(
    year: int | None = None,
    trip_id: int | None = None,
    brand: str | None = None,
    status: str | None = None,
    skip: int = 0,
    limit: int = 500,
    user: models.User = Me,
    db: Session = Depends(get_db),
):
    """Your stays and stays on trips you're on, newest check-in first."""
    return crud.get_lodgings(db, year=year, trip_id=trip_id, brand=brand, status=status, skip=skip, limit=limit,
                             base=access.lodgings(db, user))

@app.get("/lodgings/{lodging_id}", response_model=schemas.Lodging)
def read_lodging(lodging_id: int, user: models.User = Me, db: Session = Depends(get_db)):
    return access.lodging_or_404(db, lodging_id, user)

@app.post("/lodgings/", response_model=schemas.Lodging)
def create_lodging(lodging: schemas.LodgingCreate, user: models.User = Me, db: Session = Depends(get_db)):
    """Create a stay that may or may not belong to a trip."""
    if lodging.trip_id is not None:
        access.trip_or_404(db, lodging.trip_id, user)
    return crud.create_lodging(db, lodging, owner_id=user.id)

@app.put("/lodgings/external/{external_id}", response_model=schemas.Lodging)
def upsert_lodging(external_id: str, lodging: schemas.LodgingCreate, user: models.User = Me,
                   db: Session = Depends(get_db)):
    """Idempotent import: create or replace your stay with this source id."""
    if lodging.trip_id is not None:
        access.trip_or_404(db, lodging.trip_id, user)
    row, _created = crud.upsert_lodging_by_external_id(db, external_id, lodging, owner_id=user.id)
    return row

@app.patch("/lodgings/{lodging_id}", response_model=schemas.Lodging)
def update_lodging(lodging_id: int, patch: schemas.LodgingUpdate, user: models.User = Me,
                   db: Session = Depends(get_db)):
    row = access.editable_lodging_or_404(db, lodging_id, user)
    changes = patch.model_dump(exclude_unset=True)
    if changes.get("trip_id") is not None:
        access.trip_or_404(db, changes["trip_id"], user)
    return crud.update_lodging(db, row, changes)

@app.delete("/lodgings/{lodging_id}", status_code=204)
def delete_lodging(lodging_id: int, user: models.User = Me, db: Session = Depends(get_db)):
    crud.delete_lodging(db, access.editable_lodging_or_404(db, lodging_id, user))

# --- Travelers and invites ---

@app.post("/trips/{trip_id}/participants/{user_id}", response_model=schemas.Trip)
def add_participant_to_trip(trip_id: int, user_id: int, user: models.User = Me, db: Session = Depends(get_db)):
    """Add someone you already share a trip or group with."""
    access.trip_or_404(db, trip_id, user)
    access.user_or_404(db, user_id, user)
    return crud.add_trip_participant(db=db, trip_id=trip_id, user_id=user_id)

@app.post("/trips/{trip_id}/travelers", response_model=schemas.Trip)
def add_traveler_to_trip(trip_id: int, body: schemas.TravelerCreate, user: models.User = Me,
                         db: Session = Depends(get_db)):
    """Add a person by name (+ optional email).

    With an email: an existing account is linked directly; otherwise a pending invite is
    created and claimed when that email signs up. Without an email: a placeholder person.
    """
    trip = access.trip_or_404(db, trip_id, user)
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")
    email = auth.normalize_email(body.email or "") or None
    if email and email.endswith(auth.PLACEHOLDER_DOMAIN):
        email = None
    person = crud.find_or_create_traveler(db, body.name, email, known_ids=access.known_user_ids(db, user))
    if email and person.is_placeholder:
        exists = db.query(models.TripInvite).filter(models.TripInvite.trip_id == trip.id,
                                                    models.TripInvite.user_id == person.id).first()
        if exists is None:
            db.add(models.TripInvite(trip_id=trip.id, email=email, user_id=person.id, invited_by_id=user.id))
            db.commit()
    return crud.add_trip_participant(db=db, trip_id=trip_id, user_id=person.id)

@app.post("/trips/{trip_id}/travelers/{user_id}/invite-code", response_model=schemas.InviteCode)
def create_invite_code(trip_id: int, user_id: int, user: models.User = Me, db: Session = Depends(get_db)):
    """A one-time code (valid 14 days) that lets this not-yet-signed-up traveler claim their spot.
    Share it yourself (message, in person); asking again replaces the previous code."""
    trip = access.trip_or_404(db, trip_id, user)
    person = db.get(models.User, user_id)
    if person is None:
        raise HTTPException(status_code=404, detail="That person isn't on this trip")
    code, expires = invites.issue(db, trip, person, user)
    return {"code": code, "expires_at": expires, "trip_id": trip.id, "user_id": person.id,
            "name": person.display_name or person.username}

@app.get("/trips/{trip_id}/invites", response_model=list[schemas.TripInvite])
def read_trip_invites(trip_id: int, user: models.User = Me, db: Session = Depends(get_db)):
    access.trip_or_404(db, trip_id, user)
    return db.query(models.TripInvite).filter(models.TripInvite.trip_id == trip_id).all()

@app.delete("/trips/{trip_id}/participants/{user_id}", response_model=schemas.Trip)
def remove_participant_from_trip(trip_id: int, user_id: int, force: bool = False, user: models.User = Me,
                                 db: Session = Depends(get_db)):
    trip = access.trip_or_404(db, trip_id, user)
    if user_id == trip.owner_id:
        raise HTTPException(status_code=400, detail="The trip's owner can't be removed")
    if user_id != user.id and trip.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the trip's owner can remove other travelers")
    if not force:
        net = money.person_net(money.trip_ledger(db, trip), user_id)
        if net:
            side = "is owed" if net > 0 else "owes"
            raise HTTPException(
                status_code=409,
                detail=f"This person {side} ${abs(net) / 100:.2f} on this trip. Settle up first, or pass force=true.",
            )
    result = crud.remove_trip_participant(db=db, trip_id=trip_id, user_id=user_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Trip or User not found")
    return result

@app.get("/flights/", response_model=list[schemas.Flight])
def read_flights(skip: int = 0, limit: int = 100, user: models.User = Me, db: Session = Depends(get_db)):
    return access.flights(db, user).order_by(models.Flight.id).offset(skip).limit(limit).all()

@app.get("/expenses/", response_model=list[schemas.Expense])
def read_expenses(skip: int = 0, limit: int = 100, user: models.User = Me, db: Session = Depends(get_db)):
    return access.expenses(db, user).order_by(models.Expense.id).offset(skip).limit(limit).all()

@app.get("/stats/", response_model=schemas.StatsResponse)
def read_stats(year: int | None = None, user: models.User = Me, db: Session = Depends(get_db)):
    """Your flight/rental Passport stats. Optional calendar year filter (SQLite strftime)."""
    return crud.get_trip_stats(db=db, year=year, user=user)


@app.get("/stats/years", response_model=schemas.StatsYearsResponse)
def read_stats_years(user: models.User = Me, db: Session = Depends(get_db)):
    """Distinct years from your flight departures and rental pickups."""
    return {"years": crud.get_stats_years(db=db, user=user)}

@app.put("/splits/{split_id}/settle", response_model=schemas.ExpenseSplit)
def settle_split(split_id: int, user: models.User = Me, db: Session = Depends(get_db)):
    """Legacy: flag one split as settled. New clients record settlements via /trips/{id}/settle."""
    split = db.get(models.ExpenseSplit, split_id)
    if split is None:
        raise HTTPException(status_code=404, detail="Split not found")
    access.expense_or_404(db, split.expense_id, user)
    return crud.settle_split(db, split_id=split_id)

@app.get("/trips/{trip_id}/timeline")
def get_trip_timeline(trip_id: int, user: models.User = Me, db: Session = Depends(get_db)):
    access.trip_or_404(db, trip_id, user)
    return crud.get_trip_timeline(db, trip_id=trip_id)


@app.delete("/trips/{trip_id}", status_code=204)
def delete_trip(trip_id: int, force: bool = False, permanent: bool = False, user: models.User = Me,
                db: Session = Depends(get_db)):
    """Delete a trip (owner only). It moves to Recently Deleted for 30 days with everything on it
    and can be restored; permanent=true skips that. See GET /trips/{id}/delete-preview first.
    `force` is accepted for older clients (a delete no longer needs it)."""
    trash_routes.delete_one(db, access.owned_trip_or_404(db, trip_id, user), permanent)
