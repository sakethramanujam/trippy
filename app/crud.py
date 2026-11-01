from sqlalchemy.orm import Session, Query
from sqlalchemy import func, distinct
from collections import Counter, defaultdict
from typing import List, Optional
from . import models, schemas

MILES_TO_KM = 1.609344


def _apply_year(query: Query, column, year: Optional[int]) -> Query:
    """Restrict to calendar year on a DateTime column; NULL timestamps excluded when year is set."""
    if year is None:
        return query
    return query.filter(column.isnot(None), func.strftime("%Y", column) == str(year))


def _top_counts(query: Query, name_col, limit: int = 20) -> List[dict]:
    rows = (
        query.filter(name_col.isnot(None))
        .group_by(name_col)
        .order_by(func.count().desc())
        .limit(limit)
        .all()
    )
    return [{"name": row[0], "count": row[1]} for row in rows]


def _sum_cost_by_currency(rows) -> dict[str, float]:
    """rows: iterable of (cost, currency) where cost may be None."""
    totals: dict[str, float] = defaultdict(float)
    for cost, currency in rows:
        if cost is None:
            continue
        code = (currency or "USD").upper()
        totals[code] += float(cost)
    return dict(totals)

def get_user(db: Session, user_id: int):
    return db.query(models.User).filter(models.User.id == user_id).first()

def get_user_by_email(db: Session, email: str):
    return db.query(models.User).filter(models.User.email == email).first()

def get_users(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.User).offset(skip).limit(limit).all()

def create_user(db: Session, user: schemas.UserCreate):
    from .auth import hash_password
    db_user = models.User(email=user.email.strip().lower(), username=user.username,
                          display_name=user.username, hashed_password=hash_password(user.password))
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def get_trips(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.Trip).offset(skip).limit(limit).all()

def create_user_trip(db: Session, trip: schemas.TripCreate, user_id: int):
    from .titles import is_auto_title
    db_trip = models.Trip(**trip.model_dump(), owner_id=user_id, title_auto=is_auto_title(trip.title))
    db.add(db_trip)
    db.commit()
    db.refresh(db_trip)
    return db_trip

def get_trip(db: Session, trip_id: int):
    return db.query(models.Trip).filter(models.Trip.id == trip_id).first()

def create_trip_flight(db: Session, flight: schemas.FlightCreate, trip_id: int, owner_id: Optional[int] = None):
    db_flight = models.Flight(**flight.model_dump(), trip_id=trip_id, owner_id=owner_id)
    db.add(db_flight)
    db.commit()
    db.refresh(db_flight)
    return db_flight

def create_trip_expense(db: Session, expense: schemas.ExpenseCreate, trip_id: int):
    """An unsplit expense (the payer's own cost)."""
    from .ledger import to_cents
    db_expense = models.Expense(**expense.model_dump(), trip_id=trip_id,
                                amount_cents=to_cents(expense.amount), split_mode="equal")
    db.add(db_expense)
    db.commit()
    db.refresh(db_expense)
    return db_expense

def create_trip_activity(db: Session, activity: schemas.ActivityCreate, trip_id: int):
    db_activity = models.Activity(**activity.model_dump(), trip_id=trip_id)
    db.add(db_activity)
    db.commit()
    db.refresh(db_activity)
    return db_activity

def create_trip_document(db: Session, document: schemas.DocumentCreate, trip_id: int):
    db_document = models.Document(**document.model_dump(), trip_id=trip_id)
    db.add(db_document)
    db.commit()
    db.refresh(db_document)
    return db_document

def create_trip_rental_car(db: Session, rental_car: schemas.RentalCarCreate, trip_id: int,
                           owner_id: Optional[int] = None):
    data = rental_car.model_dump(exclude={"trip_id"})
    db_rental_car = models.RentalCar(**data, trip_id=trip_id, owner_id=owner_id)
    db.add(db_rental_car)
    db.commit()
    db.refresh(db_rental_car)
    return db_rental_car

def add_trip_participant(db: Session, trip_id: int, user_id: int):
    trip = db.query(models.Trip).filter(models.Trip.id == trip_id).first()
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not trip or not user:
        return None
    if user not in trip.participants:
        trip.participants.append(user)
        db.commit()
        db.refresh(trip)
    return trip

def remove_trip_participant(db: Session, trip_id: int, user_id: int):
    trip = db.query(models.Trip).filter(models.Trip.id == trip_id).first()
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not trip or not user:
        return None
    if user in trip.participants:
        trip.participants.remove(user)
        db.commit()
        db.refresh(trip)
    return trip

def get_trip_stats(db: Session, year: Optional[int] = None, user: Optional[models.User] = None) -> dict:
    """
    Peer flight + rental Passport stats.

    Scope: what `user` can see (global when user is None, e.g. scripts). When `year` is set, only rows whose
    primary timestamp falls in that calendar year are included (NULL times excluded).
    Flat aliases preserve pre-PR3 ApiStats field names; total_expenses is USD-only.
    """
    from . import access
    fq = access.flights(db, user) if user else db.query(models.Flight)
    rq = access.rentals(db, user) if user else db.query(models.RentalCar)
    eq = access.expenses(db, user) if user else db.query(models.Expense)
    lq = access.lodgings(db, user) if user else db.query(models.Lodging)
    stays = [h for h in _apply_year(lq, models.Lodging.check_in, year).all() if not is_cancelled(h)]
    flights = _apply_year(fq, models.Flight.departure_time, year).all()
    rentals = _apply_year(rq, models.RentalCar.pickup_time, year).all()
    expenses = _apply_year(eq, models.Expense.date, year).all()

    # --- Flights ---
    flight_count = len(flights)
    airports = set()
    distance_miles = 0.0
    duration_minutes = 0
    for f in flights:
        if f.departure_airport:
            airports.add(f.departure_airport)
        if f.arrival_airport:
            airports.add(f.arrival_airport)
        if f.distance_miles is not None:
            distance_miles += float(f.distance_miles)
        if f.duration_minutes is not None:
            duration_minutes += int(f.duration_minutes)
        elif f.departure_time and f.arrival_time:
            duration_minutes += max(
                0, int((f.arrival_time - f.departure_time).total_seconds() // 60)
            )

    flight_costs = _sum_cost_by_currency((f.cost, f.currency) for f in flights)

    top_aircraft = _top_counts(
        _apply_year(
            db.query(models.Flight.aircraft_model, func.count(models.Flight.id)),
            models.Flight.departure_time,
            year,
        ),
        models.Flight.aircraft_model,
    )
    top_airlines = _top_counts(
        _apply_year(
            db.query(models.Flight.airline, func.count(models.Flight.id)),
            models.Flight.departure_time,
            year,
        ),
        models.Flight.airline,
    )

    flights_block = {
        "count": flight_count,
        "airports": len(airports),
        "distance_miles": round(distance_miles, 2),
        "distance_km": round(distance_miles * MILES_TO_KM, 2),
        "duration_minutes": duration_minutes,
        "total_cost_by_currency": flight_costs,
        "top_aircraft": top_aircraft,
        "top_airlines": top_airlines,
    }

    # --- Rentals ---
    rental_count = len(rentals)
    mileage_driven = 0.0
    duration_days = 0.0
    for r in rentals:
        mileage_driven += float(r.mileage_driven or 0.0)
        if r.pickup_time and r.dropoff_time:
            duration_days += max(
                0.0, (r.dropoff_time - r.pickup_time).total_seconds() / 86400.0
            )

    rental_costs = _sum_cost_by_currency((r.cost, r.currency) for r in rentals)

    top_cars = _top_counts(
        _apply_year(
            db.query(models.RentalCar.car_model, func.count(models.RentalCar.id)),
            models.RentalCar.pickup_time,
            year,
        ),
        models.RentalCar.car_model,
    )
    top_rental_companies = _top_counts(
        _apply_year(
            db.query(models.RentalCar.rental_company, func.count(models.RentalCar.id)),
            models.RentalCar.pickup_time,
            year,
        ),
        models.RentalCar.rental_company,
    )
    top_vehicle_classes = _top_counts(
        _apply_year(
            db.query(models.RentalCar.vehicle_class, func.count(models.RentalCar.id)),
            models.RentalCar.pickup_time,
            year,
        ),
        models.RentalCar.vehicle_class,
    )

    rentals_block = {
        "count": rental_count,
        "mileage_driven": round(mileage_driven, 2),
        "duration_days": round(duration_days, 2),
        "total_cost_by_currency": rental_costs,
        "top_cars": top_cars,
        "top_rental_companies": top_rental_companies,
        "top_vehicle_classes": top_vehicle_classes,
    }

    # --- Stays ---
    stays_block = {
        "count": len(stays),
        "nights": sum(lodging_nights(h) for h in stays),
        "total_cost_by_currency": _sum_cost_by_currency((h.cost, h.currency) for h in stays),
        "top_brands": [{"name": n, "count": c} for n, c in Counter(h.brand for h in stays if h.brand).most_common(20)],
        "top_booking_sources": [{"name": n, "count": c} for n, c in
                                Counter(h.booking_source for h in stays if h.booking_source).most_common(20)],
        "cities": len({(h.city or "").lower() for h in stays if h.city}),
    }

    # --- Expenses (by currency; flat total_expenses is USD-only) ---
    expenses_by_currency: dict[str, float] = defaultdict(float)
    for e in expenses:
        code = (e.currency or "USD").upper()
        expenses_by_currency[code] += float(e.amount or 0.0)
    expenses_by_currency = dict(expenses_by_currency)
    total_expenses_usd = float(expenses_by_currency.get("USD", 0.0))

    # --- Trips ---
    if year is None:
        total_trips = db.query(func.count(models.Trip.id)).scalar() or 0
    else:
        trip_ids = ({f.trip_id for f in flights} | {r.trip_id for r in rentals} | {h.trip_id for h in stays}) - {None}
        for row in _apply_year(db.query(models.Trip.id), models.Trip.start_date, year).all():
            trip_ids.add(row[0])
        total_trips = len(trip_ids)

    return {
        "year": year,
        "flights": flights_block,
        "rentals": rentals_block,
        "stays": stays_block,
        "total_trips": total_trips,
        "total_expenses_by_currency": expenses_by_currency,
        "total_expenses": total_expenses_usd,
        "total_flights": flight_count,
        "total_airports": len(airports),
        "top_aircraft": top_aircraft,
        "top_airlines": top_airlines,
        "top_cars": top_cars,
        "top_rental_companies": top_rental_companies,
    }


def get_stats_years(db: Session, user: Optional[models.User] = None) -> List[int]:
    """Distinct calendar years from flight departures and rental pickups, descending."""
    from . import access
    fq = access.flights(db, user) if user else db.query(models.Flight)
    rq = access.rentals(db, user) if user else db.query(models.RentalCar)
    flight_years = (
        fq.with_entities(func.strftime("%Y", models.Flight.departure_time))
        .filter(models.Flight.departure_time.isnot(None))
        .distinct()
        .all()
    )
    rental_years = (
        rq.with_entities(func.strftime("%Y", models.RentalCar.pickup_time))
        .filter(models.RentalCar.pickup_time.isnot(None))
        .distinct()
        .all()
    )
    lq = access.lodgings(db, user) if user else db.query(models.Lodging)
    stay_years = (
        lq.with_entities(func.strftime("%Y", models.Lodging.check_in))
        .filter(models.Lodging.check_in.isnot(None))
        .distinct()
        .all()
    )
    years: set[int] = set()
    for (y,) in stay_years:
        if y is not None:
            years.add(int(y))
    for (y,) in flight_years:
        if y is not None:
            years.add(int(y))
    for (y,) in rental_years:
        if y is not None:
            years.add(int(y))
    return sorted(years, reverse=True)

def settle_split(db: Session, split_id: int):
    """Mark a single expense split as settled."""
    db_split = db.query(models.ExpenseSplit).filter(models.ExpenseSplit.id == split_id).first()
    if not db_split:
        return None
    db_split.is_settled = True
    db.commit()
    db.refresh(db_split)
    return db_split

def get_trip_timeline(db: Session, trip_id: int):
    """Return all events for a trip sorted chronologically.
    
    Merges flights, expenses, activities, and rental_cars into a unified list.
    """
    trip = db.query(models.Trip).filter(models.Trip.id == trip_id).first()
    if not trip:
        return None

    events = []

    for f in trip.flights:
        events.append({
            "type": "flight",
            "title": f"{f.airline} {f.flight_number}",
            "subtitle": f"{f.departure_airport} → {f.arrival_airport}",
            "date": f.departure_time.isoformat() if f.departure_time else None,
            "id": f.id,
        })

    for e in trip.expenses:
        events.append({
            "type": "expense",
            "title": e.description,
            "subtitle": f"${e.amount:.2f}",
            "date": e.date.isoformat() if e.date else None,
            "id": e.id,
        })

    for a in trip.activities:
        events.append({
            "type": "activity",
            "title": a.title,
            "subtitle": a.description or "",
            "date": a.start_time.isoformat() if a.start_time else None,
            "id": a.id,
        })

    for h in trip.lodgings:
        events.append({
            "type": "lodging",
            "title": h.name,
            "subtitle": h.address or h.city or "",
            "date": h.check_in.isoformat() if h.check_in else None,
            "id": h.id,
        })

    for r in trip.rental_cars:
        events.append({
            "type": "rental_car",
            "title": f"{r.rental_company} — {r.car_model or 'Car'}",
            "subtitle": f"{r.pickup_location} → {r.dropoff_location}",
            "date": r.pickup_time.isoformat() if r.pickup_time else None,
            "id": r.id,
        })

    # Sort by date, putting None-dated items at the end
    events.sort(key=lambda x: x["date"] or "9999-12-31")
    return events


# --- Stays (hotels / rental homes) ---


def _fill_nights(row: models.Lodging) -> None:
    if row.nights is None and row.check_in and row.check_out:
        row.nights = max(0, (row.check_out.date() - row.check_in.date()).days)


def get_lodgings(db: Session, year: Optional[int] = None, trip_id: Optional[int] = None,
                 brand: Optional[str] = None, status: Optional[str] = None, skip: int = 0, limit: int = 500,
                 base: Optional[Query] = None) -> List[models.Lodging]:
    q = base if base is not None else db.query(models.Lodging)
    q = _apply_year(q, models.Lodging.check_in, year)
    if trip_id is not None:
        q = q.filter(models.Lodging.trip_id == trip_id)
    if brand:
        q = q.filter(func.lower(models.Lodging.brand) == brand.lower())
    if status:
        q = q.filter(func.lower(models.Lodging.status) == status.lower())
    return q.order_by(models.Lodging.check_in.desc()).offset(skip).limit(limit).all()


def create_lodging(db: Session, lodging: schemas.LodgingCreate, owner_id: Optional[int] = None,
                   trip_id: Optional[int] = None) -> models.Lodging:
    data = lodging.model_dump()
    if trip_id is not None:
        data["trip_id"] = trip_id
    row = models.Lodging(**data, owner_id=owner_id)
    _fill_nights(row)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_lodging(db: Session, row: models.Lodging, patch: dict) -> models.Lodging:
    for key, value in patch.items():
        setattr(row, key, value)
    if "check_in" in patch or "check_out" in patch:
        if "nights" not in patch:
            row.nights = None
        _fill_nights(row)
    db.commit()
    db.refresh(row)
    return row


def upsert_lodging_by_external_id(db: Session, external_id: str, lodging: schemas.LodgingCreate,
                                  owner_id: Optional[int] = None) -> tuple[models.Lodging, bool]:
    """Idempotent import: create, or overwrite the owner's stay that has this external_id."""
    data = lodging.model_dump()
    data["external_id"] = external_id
    q = db.query(models.Lodging).filter(models.Lodging.external_id == external_id)
    if owner_id is not None:
        q = q.filter(models.Lodging.owner_id == owner_id)
    existing = q.first()
    if existing is None:
        return create_lodging(db, schemas.LodgingCreate(**data), owner_id=owner_id), True
    return update_lodging(db, existing, data), False


def delete_lodging(db: Session, row: models.Lodging) -> None:
    db.delete(row)
    db.commit()


def lodging_nights(h: models.Lodging) -> int:
    if h.nights is not None:
        return h.nights
    if h.check_in and h.check_out:
        return max(0, (h.check_out.date() - h.check_in.date()).days)
    return 0


def is_cancelled(h) -> bool:
    return (getattr(h, "status", None) or "").lower() == "cancelled"


# --- Rental cars (standalone tracker) ---

def get_rental_cars(db: Session, year: Optional[int] = None, trip_id: Optional[int] = None,
                    company: Optional[str] = None, skip: int = 0, limit: int = 500,
                    base: Optional[Query] = None):
    """Rentals newest pickup first. Optional year / trip / company filters."""
    q = _apply_year(base if base is not None else db.query(models.RentalCar), models.RentalCar.pickup_time, year)
    if trip_id is not None:
        q = q.filter(models.RentalCar.trip_id == trip_id)
    if company:
        q = q.filter(func.lower(models.RentalCar.rental_company) == company.lower())
    return (
        q.order_by(models.RentalCar.pickup_time.desc(), models.RentalCar.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_rental_car(db: Session, rental_id: int):
    return db.query(models.RentalCar).filter(models.RentalCar.id == rental_id).first()


def get_rental_car_by_external_id(db: Session, external_id: str, owner_id: Optional[int] = None):
    q = db.query(models.RentalCar).filter(models.RentalCar.external_id == external_id)
    if owner_id is not None:
        q = q.filter(models.RentalCar.owner_id == owner_id)
    return q.first()


def create_rental_car(db: Session, rental_car: schemas.RentalCarCreate, owner_id: Optional[int] = None):
    db_rental_car = models.RentalCar(**rental_car.model_dump(), owner_id=owner_id)
    db.add(db_rental_car)
    db.commit()
    db.refresh(db_rental_car)
    return db_rental_car


def update_rental_car(db: Session, db_rental_car: models.RentalCar, patch: dict):
    for key, value in patch.items():
        setattr(db_rental_car, key, value)
    db.commit()
    db.refresh(db_rental_car)
    return db_rental_car


def upsert_rental_car_by_external_id(db: Session, external_id: str, rental_car: schemas.RentalCarCreate,
                                     owner_id: Optional[int] = None):
    """Idempotent import: create, or overwrite the owner's rental that has this external_id."""
    data = rental_car.model_dump()
    data["external_id"] = external_id
    existing = get_rental_car_by_external_id(db, external_id, owner_id)
    if existing is None:
        return create_rental_car(db, schemas.RentalCarCreate(**data), owner_id=owner_id), True
    return update_rental_car(db, existing, data), False


def delete_rental_car(db: Session, db_rental_car: models.RentalCar):
    db.query(models.Drive).filter(models.Drive.rental_id == db_rental_car.id).update({models.Drive.rental_id: None})
    db.delete(db_rental_car)
    db.commit()


# --- Travelers (people on a trip) ---

def _slug(text: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", ".", text.lower()).strip(".") or "traveler"

def find_or_create_traveler(db: Session, name: str, email: Optional[str] = None,
                            known_ids: Optional[set] = None) -> models.User:
    """Match an existing user by email, then by case-insensitive username among `known_ids`
    (people the caller already shares trips/groups with); otherwise create a placeholder.

    People added from the app often have no email, so a unique placeholder address is
    generated (users.email is unique). Travelers get no usable password.
    """
    name = name.strip()
    email = (email or "").strip() or None
    user = None
    if email:
        user = db.query(models.User).filter(func.lower(models.User.email) == email.lower()).first()
        # A real account is linked by email only if the caller already shares a trip/group with it;
        # otherwise adding an email would reveal that the account exists and pull it into a trip
        # without consent. Unknown real accounts get a fresh placeholder instead.
        if user is not None and not user.is_placeholder and known_ids is not None and user.id not in known_ids:
            user = None
            email = None
    if user is None:
        q = db.query(models.User).filter(func.lower(models.User.username) == name.lower())
        if known_ids is not None:
            q = q.filter(models.User.id.in_(known_ids or {-1}))
        user = q.first()
    if user is not None:
        if email and user.is_placeholder and user.email.endswith("@travelers.trippy.local"):
            user.email = email
            db.commit()
        return user
    username = name
    n = 2
    while db.query(models.User).filter(models.User.username == username).first() is not None:
        username = f"{name} {n}"
        n += 1
    if email is None:
        base = _slug(name)
        email = f"{base}@travelers.trippy.local"
        n = 2
        while db.query(models.User).filter(models.User.email == email).first() is not None:
            email = f"{base}.{n}@travelers.trippy.local"
            n += 1
    user = models.User(username=username, display_name=name, email=email.lower(),
                       hashed_password="!traveler", is_placeholder=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

def delete_trip(db: Session, trip: models.Trip) -> None:
    """Delete a trip: rentals are unlinked (kept), participants detached, child rows removed."""
    for r in list(trip.rental_cars) + list(trip.lodgings):
        r.trip_id = None
    db.query(models.Drive).filter(models.Drive.trip_id == trip.id).update({models.Drive.trip_id: None})  # drives are kept
    db.query(models.TripInvite).filter(models.TripInvite.trip_id == trip.id).delete()
    db.query(models.TripStory).filter(models.TripStory.trip_id == trip.id).delete()
    db.query(models.TripPin).filter(models.TripPin.trip_id == trip.id).delete()
    trip.participants.clear()
    for e in list(trip.expenses):
        db.delete(e)  # splits cascade
    for st in db.query(models.Settlement).filter(models.Settlement.trip_id == trip.id).all():
        db.delete(st)
    for coll in (trip.flights, trip.activities, trip.documents):
        for row in list(coll):
            db.delete(row)
    db.delete(trip)
    db.commit()
