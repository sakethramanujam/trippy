from pydantic import BaseModel, ConfigDict, computed_field
from typing import List, Optional
from datetime import datetime

class ActivityBase(BaseModel):
    title: str
    description: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    location_map_link: Optional[str] = None

class ActivityCreate(ActivityBase):
    pass

class Activity(ActivityBase):
    id: int
    trip_id: int
    model_config = ConfigDict(from_attributes=True)

class DocumentBase(BaseModel):
    title: str
    url: str

class DocumentCreate(DocumentBase):
    pass

class Document(DocumentBase):
    id: int
    trip_id: int
    model_config = ConfigDict(from_attributes=True)

class ExpenseSplitBase(BaseModel):
    user_id: int
    amount_owed: float
    is_settled: bool = False

class ExpenseSplitCreate(BaseModel):
    user_id: int
    amount_owed: float

class ExpenseSplit(ExpenseSplitBase):
    id: int
    expense_id: int
    amount_cents: Optional[int] = None
    share: Optional[float] = None
    model_config = ConfigDict(from_attributes=True)

class ExpenseBase(BaseModel):
    amount: float
    description: str
    native_receipt_link: Optional[str] = None
    date: Optional[datetime] = None
    currency: str = "USD"

class ExpenseCreate(ExpenseBase):
    payer_id: int

class SplitValue(BaseModel):
    """Per-person value for exact ($), percent (%), or shares (weight) splits."""
    user_id: int
    value: float

class ExpenseUpdate(BaseModel):
    amount: Optional[float] = None
    description: Optional[str] = None
    payer_id: Optional[int] = None
    currency: Optional[str] = None
    date: Optional[datetime] = None
    # Any of these re-splits the expense (amount/payer changes re-split too).
    split_mode: Optional[str] = None
    split_among: Optional[List[int]] = None
    splits: Optional[List[SplitValue]] = None

class Expense(ExpenseBase):
    id: int
    trip_id: Optional[int] = None
    group_id: Optional[int] = None
    payer_id: int
    amount_cents: Optional[int] = None
    split_mode: Optional[str] = None
    splits: List[ExpenseSplit] = []
    
    model_config = ConfigDict(from_attributes=True)

class ExpenseSplitCreateRequest(BaseModel):
    amount: float
    description: str
    payer_id: int
    # equal: split_among only. exact/percent/shares: `splits` values (split_among optional).
    split_among: List[int] = []
    split_mode: str = "equal"
    splits: Optional[List[SplitValue]] = None
    currency: str = "USD"
    date: Optional[datetime] = None

class FlightBase(BaseModel):
    airline: str
    flight_number: str
    departure_airport: str
    arrival_airport: str
    departure_time: datetime
    arrival_time: datetime
    
    # Advanced Flight Tracking
    aircraft_type: Optional[str] = None
    aircraft_model: Optional[str] = None
    aircraft_manufacturer: Optional[str] = None
    delay_minutes: int = 0
    status: str = "Scheduled"

    # Passport / receipt enrichment
    confirmation_number: Optional[str] = None
    distance_miles: Optional[float] = None
    duration_minutes: Optional[int] = None
    cost: Optional[float] = None
    currency: str = "USD"
    seat: Optional[str] = None
    cabin_class: Optional[str] = None
    booking_source: Optional[str] = None

class FlightCreate(FlightBase):
    pass

class Flight(FlightBase):
    id: int
    trip_id: Optional[int] = None
    owner_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)

    @computed_field
    @property
    def distance_km(self) -> Optional[float]:
        """Derived from canonical distance_miles; not stored in DB."""
        if self.distance_miles is None:
            return None
        return self.distance_miles * 1.609344

class LodgingBase(BaseModel):
    """A hotel (or rental home) stay. Times are local wall clock at the property; *_tz names the zone."""
    name: str
    address: Optional[str] = None
    check_in: Optional[datetime] = None
    check_out: Optional[datetime] = None
    confirmation_number: Optional[str] = None
    cost: Optional[float] = None          # total paid, taxes included
    currency: Optional[str] = "USD"
    booking_source: Optional[str] = None  # "direct" or the OTA, e.g. "Booking.com", "Airbnb"
    notes: Optional[str] = None

    brand: Optional[str] = None
    property_type: Optional[str] = None   # hotel / motel / rental / hostel
    city: Optional[str] = None
    country: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    check_in_tz: Optional[str] = None
    check_out_tz: Optional[str] = None
    time_approx: Optional[bool] = False   # only dates were known; the times are usual hours
    nights: Optional[int] = None
    room_type: Optional[str] = None
    rooms: Optional[int] = None
    guests: Optional[int] = None
    taxes_fees: Optional[float] = None
    loyalty_program: Optional[str] = None
    loyalty_points: Optional[int] = None
    status: Optional[str] = None          # booked / completed / cancelled (None = infer from dates)
    source_email_ref: Optional[str] = None

class LodgingCreate(LodgingBase):
    # Standalone stays (POST /lodgings/) may set these; trip-scoped POST ignores trip_id.
    trip_id: Optional[int] = None
    external_id: Optional[str] = None

class LodgingUpdate(BaseModel):
    """Partial update: only fields that are sent are changed."""
    trip_id: Optional[int] = None
    name: Optional[str] = None
    address: Optional[str] = None
    check_in: Optional[datetime] = None
    check_out: Optional[datetime] = None
    confirmation_number: Optional[str] = None
    cost: Optional[float] = None
    currency: Optional[str] = None
    booking_source: Optional[str] = None
    notes: Optional[str] = None
    external_id: Optional[str] = None
    brand: Optional[str] = None
    property_type: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    check_in_tz: Optional[str] = None
    check_out_tz: Optional[str] = None
    time_approx: Optional[bool] = None
    nights: Optional[int] = None
    room_type: Optional[str] = None
    rooms: Optional[int] = None
    guests: Optional[int] = None
    taxes_fees: Optional[float] = None
    loyalty_program: Optional[str] = None
    loyalty_points: Optional[int] = None
    status: Optional[str] = None
    source_email_ref: Optional[str] = None

class Lodging(LodgingBase):
    id: int
    trip_id: Optional[int] = None
    owner_id: Optional[int] = None
    external_id: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)

    @computed_field
    @property
    def stay_status(self) -> str:
        """status if set, else completed once check-out has passed, else booked."""
        if self.status:
            return self.status
        end = self.check_out or self.check_in
        return "completed" if end and end < datetime.now() else "booked"

    @computed_field
    @property
    def night_count(self) -> Optional[int]:
        if self.nights is not None:
            return self.nights
        if self.check_in and self.check_out:
            return max(0, (self.check_out.date() - self.check_in.date()).days)
        return None

class TripBase(BaseModel):
    title: str
    description: Optional[str] = None
    native_album_id: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None

class TripCreate(TripBase):
    pass

class TripUpdate(BaseModel):
    """Rename a trip. A title set here is the user's: it is never auto-retitled again."""
    title: Optional[str] = None
    description: Optional[str] = None

class Trip(TripBase):
    id: int
    owner_id: int
    group_id: Optional[int] = None
    journey_id: Optional[int] = None
    title_auto: bool = False  # the title follows the route until the user renames the trip
    pinned: bool = False  # for the caller only; set by GET /trips/ and GET /trips/{id}
    journey_position: Optional[int] = None
    flights: List[Flight] = []
    expenses: List[Expense] = []
    activities: List[Activity] = []
    documents: List[Document] = []
    rental_cars: List["RentalCar"] = []
    lodgings: List[Lodging] = []
    participants: List["User"] = []
    
    model_config = ConfigDict(from_attributes=True)

    @computed_field
    @property
    def stay_cost_by_currency(self) -> dict[str, float]:
        """What the trip's (non-cancelled) stays cost, per currency."""
        out: dict[str, float] = {}
        for h in self.lodgings:
            if h.cost and (h.status or "").lower() != "cancelled":
                code = (h.currency or "USD").upper()
                out[code] = round(out.get(code, 0.0) + h.cost, 2)
        return out

class UserBase(BaseModel):
    username: str
    email: str

class UserCreate(UserBase):
    password: str

class User(UserBase):
    id: int
    display_name: Optional[str] = None
    # True for people added to a trip who haven't signed up (yet).
    is_placeholder: bool = False
    model_config = ConfigDict(from_attributes=True)

class RentalCarBase(BaseModel):
    rental_company: str
    car_model: Optional[str] = None
    pickup_location: str
    dropoff_location: str
    pickup_time: datetime
    # Optional: receipts sometimes only record the pickup (or an approximate date).
    dropoff_time: Optional[datetime] = None
    mileage_driven: Optional[float] = 0.0
    confirmation_number: Optional[str] = None
    cost: Optional[float] = None
    currency: Optional[str] = "USD"
    vehicle_class: Optional[str] = None
    fuel_type: Optional[str] = None
    pickup_odometer: Optional[float] = None
    dropoff_odometer: Optional[float] = None
    booking_source: Optional[str] = None

    # Rental tracker (v2)
    external_id: Optional[str] = None
    agreement_number: Optional[str] = None
    vehicle_make: Optional[str] = None
    vehicle_year: Optional[int] = None
    vehicle_color: Optional[str] = None
    license_plate: Optional[str] = None
    photo_url: Optional[str] = None
    pickup_code: Optional[str] = None
    pickup_city: Optional[str] = None
    pickup_lat: Optional[float] = None
    pickup_lng: Optional[float] = None
    dropoff_code: Optional[str] = None
    dropoff_city: Optional[str] = None
    dropoff_lat: Optional[float] = None
    dropoff_lng: Optional[float] = None
    date_approx: Optional[bool] = False
    notes: Optional[str] = None

class RentalCarCreate(RentalCarBase):
    # Standalone rentals (POST /rental_cars/) may set this; trip-scoped POST ignores it.
    trip_id: Optional[int] = None

class RentalCarUpdate(BaseModel):
    """Partial update: only fields that are sent are changed."""
    trip_id: Optional[int] = None
    rental_company: Optional[str] = None
    car_model: Optional[str] = None
    pickup_location: Optional[str] = None
    dropoff_location: Optional[str] = None
    pickup_time: Optional[datetime] = None
    dropoff_time: Optional[datetime] = None
    mileage_driven: Optional[float] = None
    confirmation_number: Optional[str] = None
    cost: Optional[float] = None
    currency: Optional[str] = None
    vehicle_class: Optional[str] = None
    fuel_type: Optional[str] = None
    pickup_odometer: Optional[float] = None
    dropoff_odometer: Optional[float] = None
    booking_source: Optional[str] = None
    external_id: Optional[str] = None
    agreement_number: Optional[str] = None
    vehicle_make: Optional[str] = None
    vehicle_year: Optional[int] = None
    vehicle_color: Optional[str] = None
    license_plate: Optional[str] = None
    photo_url: Optional[str] = None
    pickup_code: Optional[str] = None
    pickup_city: Optional[str] = None
    pickup_lat: Optional[float] = None
    pickup_lng: Optional[float] = None
    dropoff_code: Optional[str] = None
    dropoff_city: Optional[str] = None
    dropoff_lat: Optional[float] = None
    dropoff_lng: Optional[float] = None
    date_approx: Optional[bool] = None
    notes: Optional[str] = None

class RentalCar(RentalCarBase):
    id: int
    trip_id: Optional[int] = None
    owner_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


# --- Stats / Passport ---

class StatItem(BaseModel):
    name: str
    count: int


class FlightStatsBlock(BaseModel):
    count: int
    airports: int
    distance_miles: float
    distance_km: float
    duration_minutes: int
    total_cost_by_currency: dict[str, float]
    top_aircraft: List[StatItem]
    top_airlines: List[StatItem]


class RentalStatsBlock(BaseModel):
    count: int
    mileage_driven: float
    duration_days: float
    total_cost_by_currency: dict[str, float]
    top_cars: List[StatItem]
    top_rental_companies: List[StatItem]
    top_vehicle_classes: List[StatItem]


class StayStatsBlock(BaseModel):
    count: int
    nights: int
    total_cost_by_currency: dict[str, float]
    top_brands: List[StatItem]
    top_booking_sources: List[StatItem]
    cities: int


class StatsResponse(BaseModel):
    year: Optional[int] = None
    flights: FlightStatsBlock
    rentals: RentalStatsBlock
    stays: Optional[StayStatsBlock] = None
    total_trips: int
    total_expenses_by_currency: dict[str, float]
    # Deprecated flat aliases — identical names to pre-PR3 ApiStats
    total_expenses: float  # USD-only
    total_flights: int
    total_airports: int
    top_aircraft: List[StatItem]
    top_airlines: List[StatItem]
    top_cars: List[StatItem]
    top_rental_companies: List[StatItem]


class StatsYearsResponse(BaseModel):
    years: List[int]


class TravelerCreate(BaseModel):
    """Add a person to a trip by name (and optional email); the user is created if needed."""
    name: str
    email: Optional[str] = None

class SettleRequest(BaseModel):
    from_user_id: int
    to_user_id: int
    # Defaults to what from_user owes to_user in `mode`'s view of the balances.
    amount: Optional[float] = None
    note: Optional[str] = None
    mode: str = "simplified"  # or "pairwise"


class Settlement(BaseModel):
    id: int
    from_user_id: int
    to_user_id: int
    amount_cents: int
    currency: Optional[str] = "USD"
    trip_id: Optional[int] = None
    group_id: Optional[int] = None
    note: Optional[str] = None
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

    @computed_field
    @property
    def amount(self) -> float:
        return self.amount_cents / 100


class GroupCreate(BaseModel):
    name: str
    member_ids: List[int] = []
    trip_ids: List[int] = []


class GroupUpdate(BaseModel):
    name: Optional[str] = None


class GroupMemberAdd(BaseModel):
    """Add an existing user by id, or a person by name (created if needed)."""
    user_id: Optional[int] = None
    name: Optional[str] = None
    email: Optional[str] = None


class GroupFromTrip(BaseModel):
    name: Optional[str] = None


class TripGroupLink(BaseModel):
    group_id: Optional[int] = None


class DebtCreate(BaseModel):
    """A standalone IOU: from_user owes to_user `amount` (e.g. "Sam already owes Maya $30")."""
    from_user_id: int
    to_user_id: int
    amount: float
    description: str = "IOU"
    currency: str = "USD"


class GroupTripRef(BaseModel):
    id: int
    title: str
    model_config = ConfigDict(from_attributes=True)


class Group(BaseModel):
    id: int
    name: str
    created_at: Optional[datetime] = None
    members: List[User] = []
    trips: List[GroupTripRef] = []
    model_config = ConfigDict(from_attributes=True)


# --- Accounts ---

class SignUp(BaseModel):
    email: str
    password: str
    name: str
    home_airport: Optional[str] = None
    invite_code: Optional[str] = None  # one-time code from a trip invite (claims that traveler)

class InviteCode(BaseModel):
    code: str
    expires_at: datetime
    trip_id: int
    user_id: int
    name: str

class InviteRedeem(BaseModel):
    code: str

class InviteRedeemed(BaseModel):
    trip_id: int
    joined: int

class LogIn(BaseModel):
    email: str
    password: str

class RefreshRequest(BaseModel):
    refresh_token: str

class ForgotPassword(BaseModel):
    email: str

class ResetPassword(BaseModel):
    token: str
    password: str

class ChangePassword(BaseModel):
    current_password: str
    new_password: str

class DeleteAccount(BaseModel):
    password: str

class Profile(BaseModel):
    id: int
    email: str
    name: str
    initials: str
    home_airport: Optional[str] = None
    created_at: Optional[datetime] = None

class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    home_airport: Optional[str] = None

class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: Profile
    claimed: List[str] = []  # what signing up linked to this account (invites, legacy data)

class TripInvite(BaseModel):
    id: int
    trip_id: int
    email: str
    user_id: int
    created_at: Optional[datetime] = None
    claimed_at: Optional[datetime] = None
    code_expires_at: Optional[datetime] = None  # an unused invite code exists until then
    model_config = ConfigDict(from_attributes=True)
