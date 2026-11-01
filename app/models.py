from sqlalchemy import Boolean, Column, ForeignKey, Index, Integer, LargeBinary, String, Float, DateTime, Table, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from .database import Base
from datetime import datetime

# Association table for Trip Participants (Many-to-Many)
trip_participants = Table(
    "trip_participants",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("trip_id", Integer, ForeignKey("trips.id"), primary_key=True)
)

# Association table for Group members (Many-to-Many)
group_members = Table(
    "group_members",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("group_id", Integer, ForeignKey("groups.id"), primary_key=True)
)

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)

    # Accounts (v3). Placeholders are people added to trips/groups who haven't signed up;
    # signing up with their email claims the placeholder and everything linked to it.
    display_name = Column(String, nullable=True)
    home_airport = Column(String(4), nullable=True)
    is_placeholder = Column(Boolean, nullable=False, default=False)
    legacy_owner = Column(Boolean, nullable=False, default=False)  # owned the pre-accounts data
    token_version = Column(Integer, nullable=False, default=0)  # bump to revoke all tokens
    inbound_token = Column(String, nullable=True, unique=True, index=True)  # mailbox+<token>@domain
    created_at = Column(DateTime, nullable=True, default=datetime.utcnow)

    trips = relationship("Trip", back_populates="owner")
    participating_trips = relationship("Trip", secondary=trip_participants, back_populates="participants")
    expenses = relationship("Expense", back_populates="payer")

class Trip(Base):
    __tablename__ = "trips"
    pinned = False  # not a column: set per caller from trip_pins (access.mark_pinned)

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    # True while the title is generated from the trip's route (… (auto) / (flights) / (email));
    # a title the user edits by hand is never rewritten.
    title_auto = Column(Boolean, nullable=False, default=False, server_default="0")
    description = Column(String, nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"))
    
    # Store native OS photo album IDs or deep links instead of blobs
    native_album_id = Column(String, nullable=True)

    # Explicit trip window for matching & Passport UI
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=True)
    # Journeys (v4): a trip can be one leg of a longer journey. Linking never changes the trip.
    journey_id = Column(Integer, ForeignKey("journeys.id"), nullable=True, index=True)
    journey_position = Column(Integer, nullable=True)  # manual order inside the journey (else by date)
    # Recently Deleted (v5): a deleted trip is hidden everywhere for 30 days, then purged.
    deleted_at = Column(DateTime, nullable=True, index=True)
    trash_json = Column(Text, nullable=True)  # what restore puts back: story edits, journey slot

    owner = relationship("User", back_populates="trips")
    journey = relationship("Journey", back_populates="trips")
    group = relationship("Group", back_populates="trips")
    participants = relationship("User", secondary=trip_participants, back_populates="participating_trips")
    flights = relationship("Flight", back_populates="trip")
    expenses = relationship("Expense", back_populates="trip")
    activities = relationship("Activity", back_populates="trip")
    documents = relationship("Document", back_populates="trip")
    rental_cars = relationship("RentalCar", back_populates="trip")
    lodgings = relationship("Lodging", back_populates="trip")

class Flight(Base):
    __tablename__ = "flights"

    id = Column(Integer, primary_key=True, index=True)
    trip_id = Column(Integer, ForeignKey("trips.id"))
    airline = Column(String)
    flight_number = Column(String)
    departure_airport = Column(String)
    arrival_airport = Column(String)
    departure_time = Column(DateTime)
    arrival_time = Column(DateTime)
    
    # Advanced Flight Tracking
    aircraft_type = Column(String, nullable=True)
    aircraft_model = Column(String, nullable=True)
    aircraft_manufacturer = Column(String, nullable=True)
    delay_minutes = Column(Integer, default=0)
    status = Column(String, default="Scheduled")

    # Passport / receipt enrichment (v1)
    confirmation_number = Column(String, nullable=True, index=True)
    distance_miles = Column(Float, nullable=True)  # canonical; derive km in API
    duration_minutes = Column(Integer, nullable=True)
    cost = Column(Float, nullable=True)
    currency = Column(String(3), default="USD")
    seat = Column(String, nullable=True)
    cabin_class = Column(String, nullable=True)  # economy / premium_economy / business / first
    booking_source = Column(String, nullable=True)  # manual / ingestion / api
    # Who owns a flight that isn't on a trip (imports); trip flights follow the trip.
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    external_id = Column(String, nullable=True, index=True)
    
    trip = relationship("Trip", back_populates="flights")

class Expense(Base):
    __tablename__ = "expenses"

    id = Column(Integer, primary_key=True, index=True)
    trip_id = Column(Integer, ForeignKey("trips.id"))
    payer_id = Column(Integer, ForeignKey("users.id"))
    amount = Column(Float)
    description = Column(String)
    date = Column(DateTime, default=datetime.utcnow)
    currency = Column(String(3), default="USD")
    # Exact amount in cents; `amount` is kept in sync for older clients.
    amount_cents = Column(Integer, nullable=True)
    # equal / exact / percent / shares
    split_mode = Column(String, nullable=True, default="equal")
    # Standalone expenses/debts live in a group instead of a trip.
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=True)
    
    # Link to a native receipt image instead of storing it on S3
    native_receipt_link = Column(String, nullable=True)

    trip = relationship("Trip", back_populates="expenses")
    group = relationship("Group", back_populates="expenses")
    payer = relationship("User", back_populates="expenses")
    splits = relationship("ExpenseSplit", back_populates="expense", cascade="all, delete-orphan")

class Activity(Base):
    __tablename__ = "activities"

    id = Column(Integer, primary_key=True, index=True)
    trip_id = Column(Integer, ForeignKey("trips.id"))
    title = Column(String)
    description = Column(String, nullable=True)
    start_time = Column(DateTime, nullable=True)
    end_time = Column(DateTime, nullable=True)
    
    # Store map deep links or coordinates
    location_map_link = Column(String, nullable=True)
    
    trip = relationship("Trip", back_populates="activities")

class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    trip_id = Column(Integer, ForeignKey("trips.id"))
    title = Column(String)
    url = Column(String) # Link to Google Docs, Sheets, Lists, etc.

    trip = relationship("Trip", back_populates="documents")

class RentalCar(Base):
    __tablename__ = "rental_cars"

    id = Column(Integer, primary_key=True, index=True)
    trip_id = Column(Integer, ForeignKey("trips.id"))
    rental_company = Column(String)
    car_model = Column(String, nullable=True)
    pickup_location = Column(String)
    dropoff_location = Column(String)
    pickup_time = Column(DateTime)
    dropoff_time = Column(DateTime)
    mileage_driven = Column(Float, default=0.0)

    # Passport / receipt enrichment (v1)
    confirmation_number = Column(String, nullable=True, index=True)
    cost = Column(Float, nullable=True)
    currency = Column(String(3), default="USD")
    vehicle_class = Column(String, nullable=True)  # compact / suv / full_size / …
    fuel_type = Column(String, nullable=True)
    pickup_odometer = Column(Float, nullable=True)
    dropoff_odometer = Column(Float, nullable=True)
    booking_source = Column(String, nullable=True)  # manual / ingestion / api

    # Rental tracker (v2): standalone rentals (trip_id may be NULL), richer
    # vehicle + station data for the Flighty-style rentals UI.
    external_id = Column(String, nullable=True, index=True)  # id from the importing source (idempotent upserts)
    agreement_number = Column(String, nullable=True)
    vehicle_make = Column(String, nullable=True)
    vehicle_year = Column(Integer, nullable=True)
    vehicle_color = Column(String, nullable=True)
    license_plate = Column(String, nullable=True)
    photo_url = Column(String, nullable=True)
    pickup_code = Column(String, nullable=True)  # IATA code when the station is at an airport
    pickup_city = Column(String, nullable=True)
    pickup_lat = Column(Float, nullable=True)
    pickup_lng = Column(Float, nullable=True)
    dropoff_code = Column(String, nullable=True)
    dropoff_city = Column(String, nullable=True)
    dropoff_lat = Column(Float, nullable=True)
    dropoff_lng = Column(Float, nullable=True)
    date_approx = Column(Boolean, nullable=True, default=False)  # dates inferred from a receipt
    notes = Column(Text, nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    trip = relationship("Trip", back_populates="rental_cars")

class ExpenseSplit(Base):
    __tablename__ = "expense_splits"

    id = Column(Integer, primary_key=True, index=True)
    expense_id = Column(Integer, ForeignKey("expenses.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    amount_owed = Column(Float)
    amount_cents = Column(Integer, nullable=True)
    # What the person typed for exact/percent/shares splits (dollars, %, or weight).
    share = Column(Float, nullable=True)
    # Legacy per-split flag. New settle-ups record a Settlement row instead.
    is_settled = Column(Boolean, default=False)

    expense = relationship("Expense", back_populates="splits")
    user = relationship("User")


class Group(Base):
    """A named set of people whose balances are combined across trips and standalone debts."""
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    members = relationship("User", secondary=group_members)
    trips = relationship("Trip", back_populates="group")
    expenses = relationship("Expense", back_populates="group")


class Settlement(Base):
    """A recorded payment: from_user paid to_user. Balances net it out; nothing is deleted."""
    __tablename__ = "settlements"

    id = Column(Integer, primary_key=True, index=True)
    from_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    to_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    amount_cents = Column(Integer, nullable=False)
    currency = Column(String(3), default="USD")
    trip_id = Column(Integer, ForeignKey("trips.id"), nullable=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=True)
    note = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Lodging(Base):
    """A hotel or other stay (from imports). trip_id is optional, like rentals."""
    __tablename__ = "lodgings"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    trip_id = Column(Integer, ForeignKey("trips.id"), nullable=True)
    name = Column(String, nullable=False)
    address = Column(String, nullable=True)
    check_in = Column(DateTime, nullable=True)
    check_out = Column(DateTime, nullable=True)
    confirmation_number = Column(String, nullable=True, index=True)
    cost = Column(Float, nullable=True)
    currency = Column(String(3), default="USD")
    booking_source = Column(String, nullable=True)
    external_id = Column(String, nullable=True, index=True)
    notes = Column(Text, nullable=True)

    # Hotel stays (v2): where, when (local wall clock + IANA zone), what was booked, what it cost.
    brand = Column(String, nullable=True)            # chain, e.g. "Marriott", "Hilton", "Airbnb"
    property_type = Column(String, nullable=True)    # hotel / motel / rental / hostel
    city = Column(String, nullable=True)
    country = Column(String, nullable=True)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    check_in_tz = Column(String, nullable=True)      # IANA, e.g. "America/Chicago"
    check_out_tz = Column(String, nullable=True)
    # The source only had dates: check_in/check_out hold the brand's usual hours, not booked ones.
    time_approx = Column(Boolean, nullable=False, default=False, server_default="0")
    nights = Column(Integer, nullable=True)
    room_type = Column(String, nullable=True)
    rooms = Column(Integer, nullable=True)
    guests = Column(Integer, nullable=True)
    taxes_fees = Column(Float, nullable=True)
    loyalty_program = Column(String, nullable=True)
    loyalty_points = Column(Integer, nullable=True)
    status = Column(String, nullable=True)           # booked / completed / cancelled
    source_email_ref = Column(String, nullable=True)

    trip = relationship("Trip", back_populates="lodgings")


class PasswordReset(Base):
    __tablename__ = "password_resets"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String, nullable=False, unique=True)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)


class TripInvite(Base):
    """An email invite to a trip. user_id is the (possibly placeholder) person it links to."""
    __tablename__ = "trip_invites"

    id = Column(Integer, primary_key=True)
    trip_id = Column(Integer, ForeignKey("trips.id"), nullable=False, index=True)
    email = Column(String, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    invited_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    claimed_at = Column(DateTime, nullable=True)
    code_hash = Column(String, nullable=True, index=True)  # sha256 of the one-time invite code
    code_expires_at = Column(DateTime, nullable=True)


class TripPin(Base):
    """A trip one user pinned to the top of their own Trips list (pins are per user)."""
    __tablename__ = "trip_pins"
    __table_args__ = (UniqueConstraint("trip_id", "user_id", name="uq_trip_pin_user"),)

    id = Column(Integer, primary_key=True)
    trip_id = Column(Integer, ForeignKey("trips.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class TripStory(Base):
    """One user's edits to the auto-generated story for a trip (title, order, hidden items,
    notes, photo ids). The story itself is regenerated from the trip on every read."""
    __tablename__ = "trip_stories"
    __table_args__ = (UniqueConstraint("trip_id", "user_id", name="uq_trip_story_user"),)

    id = Column(Integer, primary_key=True)
    trip_id = Column(Integer, ForeignKey("trips.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String, nullable=True)
    subtitle = Column(String, nullable=True)
    theme = Column(String, nullable=True)
    cover_photo = Column(String, nullable=True)
    order_json = Column(Text, nullable=True)   # JSON list of item keys
    items_json = Column(Text, nullable=True)   # JSON {key: {hidden, note, photos}}
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Journey(Base):
    """Several trips linked into one long trip. Non-destructive: unlinking leaves every trip as it was.
    Dates, places, cost and nights are computed from the child trips on read."""
    __tablename__ = "journeys"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(String, nullable=True)
    cover_photo = Column(String, nullable=True)  # native photo id, like story covers
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    trips = relationship("Trip", back_populates="journey")


class DismissedSuggestion(Base):
    """A journey suggestion the user dismissed (key = sorted trip ids, e.g. "3,4")."""
    __tablename__ = "dismissed_suggestions"
    __table_args__ = (UniqueConstraint("user_id", "trip_key", name="uq_dismissed_suggestion"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    trip_key = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class InboundEmail(Base):
    """One forwarded email (IMAP inbox) and what happened to it. Idempotent by Message-ID."""
    __tablename__ = "inbound_emails"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    message_id = Column(String, nullable=False, index=True)  # unique per user (uq_inbound_emails_user_message)
    sender = Column(String, nullable=True)
    subject = Column(String, nullable=True)
    received_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, nullable=False, default="pending")  # pending / imported / duplicate / nothing_found / failed / ignored
    routed_by = Column(String, nullable=True)  # token / sender
    error = Column(String, nullable=True)
    result_json = Column(Text, nullable=True)  # {created:[{kind,id,trip_id,summary}], skipped:[...], trips_created:[...]}
    raw = Column(LargeBinary, nullable=True)  # the message (size-capped) so retry can re-run the importers
    seen = Column(Boolean, nullable=False, default=False)  # for the in-app badge
    attempts = Column(Integer, nullable=False, default=0)
    __table_args__ = (Index("uq_inbound_emails_user_message", "user_id", "message_id", unique=True),)


class Drive(Base):
    """A drive from Google Maps Timeline (or another location history). Only its owner sees it.

    Times are local wall-clock (like the rest of Trippy) with the UTC offset kept alongside, so
    a drive across a time zone line still reads right. `path_json` is a downsampled polyline
    [[lat, lng], …]; `stops_json` lists short stops that were merged into the drive."""
    __tablename__ = "drives"
    __table_args__ = (Index("uq_drives_owner_external", "owner_id", "external_id", unique=True),)

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    trip_id = Column(Integer, ForeignKey("trips.id"), nullable=True, index=True)
    journey_id = Column(Integer, ForeignKey("journeys.id"), nullable=True, index=True)
    rental_id = Column(Integer, ForeignKey("rental_cars.id"), nullable=True, index=True)  # accepted suggestion
    source = Column(String, nullable=False, default="google_timeline")
    external_id = Column(String, nullable=False)
    start_time = Column(DateTime, nullable=False, index=True)
    end_time = Column(DateTime, nullable=False)
    start_utc_offset = Column(Integer, nullable=True)  # minutes east of UTC
    end_utc_offset = Column(Integer, nullable=True)
    distance_miles = Column(Float, nullable=False, default=0.0)
    duration_minutes = Column(Integer, nullable=True)
    start_name = Column(String, nullable=True)
    start_lat = Column(Float, nullable=True)
    start_lng = Column(Float, nullable=True)
    end_name = Column(String, nullable=True)
    end_lat = Column(Float, nullable=True)
    end_lng = Column(Float, nullable=True)
    path_json = Column(Text, nullable=True)
    stops_json = Column(Text, nullable=True)
    dismissed_rentals_json = Column(Text, nullable=True)  # rental ids whose match you said no to
    created_at = Column(DateTime, default=datetime.utcnow)

    trip = relationship("Trip")
    rental = relationship("RentalCar")


class TripPhoto(Base):
    """A photo you attached to a trip. The full photo never leaves your device: the server keeps a
    small JPEG thumbnail (≤512 px) and the device's own id for the asset, so the app can open the
    original on the phone it came from. Only the person who added it sees it."""
    __tablename__ = "trip_photos"
    __table_args__ = (Index("uq_trip_photos_asset", "user_id", "trip_id", "device_id", "asset_id", unique=True),)

    id = Column(Integer, primary_key=True, index=True)
    trip_id = Column(Integer, ForeignKey("trips.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    device_id = Column(String, nullable=False)
    asset_id = Column(String, nullable=False)
    taken_at = Column(DateTime, nullable=True, index=True)  # local wall-clock, like the rest of Trippy
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    width = Column(Integer, nullable=False)   # of the thumbnail
    height = Column(Integer, nullable=False)
    thumb = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    trip = relationship("Trip")
