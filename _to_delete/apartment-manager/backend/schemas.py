"""Pydantic request/response models."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from .models import (
    BookingStatus,
    Channel,
    ChargeType,
    ExpenseCategory,
    HousekeepingStatus,
    InvoiceStatus,
    LeaseStatus,
    PaymentMethod,
    PersonType,
    Priority,
    PropertyType,
    Role,
    TicketStatus,
    UnitStatus,
    UnitType,
)

ORM = ConfigDict(from_attributes=True)


# ------------------------------- auth ------------------------------------- #
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserBase(BaseModel):
    email: EmailStr
    full_name: str
    role: Role = Role.staff


class UserCreate(UserBase):
    password: str = Field(min_length=8)


class UserOut(UserBase):
    model_config = ORM
    id: int
    is_active: bool
    created_at: datetime


# ----------------------------- properties --------------------------------- #
class PropertyBase(BaseModel):
    name: str
    code: str
    type: PropertyType = PropertyType.apartment
    address_line1: str | None = None
    city: str | None = None
    postcode: str | None = None
    country: str | None = None
    currency: str = "GBP"
    purchase_price: float | None = None
    notes: str | None = None


class PropertyCreate(PropertyBase):
    pass


class PropertyUpdate(BaseModel):
    name: str | None = None
    type: PropertyType | None = None
    address_line1: str | None = None
    city: str | None = None
    postcode: str | None = None
    country: str | None = None
    currency: str | None = None
    purchase_price: float | None = None
    notes: str | None = None


class PropertyOut(PropertyBase):
    model_config = ORM
    id: int
    created_at: datetime
    unit_count: int = 0


# -------------------------------- units ----------------------------------- #
class BedBase(BaseModel):
    label: str
    nightly_rate: float | None = None
    status: UnitStatus = UnitStatus.available


class BedCreate(BedBase):
    unit_id: int


class BedOut(BedBase):
    model_config = ORM
    id: int
    unit_id: int


class UnitBase(BaseModel):
    name: str
    type: UnitType = UnitType.apartment
    floor: int | None = None
    bedrooms: int = 1
    bathrooms: float = 1.0
    size_sqm: float | None = None
    capacity: int = 1
    market_rent: float | None = None
    nightly_rate: float | None = None
    status: UnitStatus = UnitStatus.available
    housekeeping: HousekeepingStatus = HousekeepingStatus.clean
    amenities: str | None = None
    notes: str | None = None


class UnitCreate(UnitBase):
    property_id: int
    bed_count: int = 0  # auto-generate this many beds for a dorm


class UnitUpdate(BaseModel):
    name: str | None = None
    type: UnitType | None = None
    floor: int | None = None
    bedrooms: int | None = None
    bathrooms: float | None = None
    size_sqm: float | None = None
    capacity: int | None = None
    market_rent: float | None = None
    nightly_rate: float | None = None
    status: UnitStatus | None = None
    housekeeping: HousekeepingStatus | None = None
    amenities: str | None = None
    notes: str | None = None


class UnitOut(UnitBase):
    model_config = ORM
    id: int
    property_id: int
    property_name: str | None = None
    beds: list[BedOut] = []


# ------------------------------- people ----------------------------------- #
class PersonBase(BaseModel):
    type: PersonType = PersonType.tenant
    full_name: str
    email: EmailStr | None = None
    phone: str | None = None
    nationality: str | None = None
    id_document: str | None = None
    date_of_birth: date | None = None
    emergency_contact: str | None = None
    screening_status: str | None = None
    notes: str | None = None


class PersonCreate(PersonBase):
    pass


class PersonUpdate(BaseModel):
    type: PersonType | None = None
    full_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    nationality: str | None = None
    id_document: str | None = None
    date_of_birth: date | None = None
    emergency_contact: str | None = None
    screening_status: str | None = None
    notes: str | None = None


class PersonOut(PersonBase):
    model_config = ORM
    id: int
    created_at: datetime
    balance: float = 0.0


# ------------------------------- leases ----------------------------------- #
class LeaseBase(BaseModel):
    unit_id: int
    person_id: int
    start_date: date
    end_date: date | None = None
    rent_amount: float
    billing_day: int = 1
    deposit_amount: float = 0
    deposit_scheme_ref: str | None = None
    status: LeaseStatus = LeaseStatus.active
    notice_date: date | None = None
    notes: str | None = None

    @field_validator("billing_day")
    @classmethod
    def _valid_day(cls, v: int) -> int:
        if not 1 <= v <= 28:
            raise ValueError("billing_day must be between 1 and 28")
        return v


class LeaseCreate(LeaseBase):
    pass


class LeaseUpdate(BaseModel):
    end_date: date | None = None
    rent_amount: float | None = None
    billing_day: int | None = None
    deposit_amount: float | None = None
    status: LeaseStatus | None = None
    notice_date: date | None = None
    notes: str | None = None


class LeaseOut(LeaseBase):
    model_config = ORM
    id: int
    created_at: datetime
    tenant_name: str | None = None
    unit_name: str | None = None
    property_name: str | None = None
    balance: float = 0.0


# ------------------------------ bookings ---------------------------------- #
class BookingBase(BaseModel):
    unit_id: int
    bed_id: int | None = None
    person_id: int
    check_in: date
    check_out: date
    guests: int = 1
    nightly_rate: float
    channel: Channel = Channel.direct
    commission_rate: float = 0.0
    status: BookingStatus = BookingStatus.confirmed
    notes: str | None = None

    @field_validator("check_out")
    @classmethod
    def _after_check_in(cls, v: date, info):
        ci = info.data.get("check_in")
        if ci and v <= ci:
            raise ValueError("check_out must be after check_in")
        return v


class BookingCreate(BookingBase):
    pass


class BookingUpdate(BaseModel):
    check_in: date | None = None
    check_out: date | None = None
    bed_id: int | None = None
    guests: int | None = None
    nightly_rate: float | None = None
    channel: Channel | None = None
    commission_rate: float | None = None
    status: BookingStatus | None = None
    notes: str | None = None


class BookingOut(BookingBase):
    model_config = ORM
    id: int
    reference: str
    total_amount: float
    nights: int = 0
    created_at: datetime
    guest_name: str | None = None
    unit_name: str | None = None
    bed_label: str | None = None
    property_name: str | None = None
    balance: float = 0.0


class AvailabilityQuery(BaseModel):
    property_id: int | None = None
    check_in: date
    check_out: date


class AvailableUnit(BaseModel):
    unit_id: int
    unit_name: str
    property_name: str
    type: UnitType
    nightly_rate: float | None
    free_beds: list[BedOut] = []
    whole_unit_available: bool = True


# ------------------------------- billing ---------------------------------- #
class InvoiceBase(BaseModel):
    person_id: int
    property_id: int | None = None
    lease_id: int | None = None
    booking_id: int | None = None
    charge_type: ChargeType = ChargeType.rent
    description: str | None = None
    issue_date: date
    due_date: date
    period_start: date | None = None
    period_end: date | None = None
    amount: float
    tax_amount: float = 0
    status: InvoiceStatus = InvoiceStatus.open


class InvoiceCreate(InvoiceBase):
    pass


class InvoiceOut(InvoiceBase):
    model_config = ORM
    id: int
    number: str
    total: float = 0
    paid: float = 0
    balance: float = 0
    person_name: str | None = None


class PaymentCreate(BaseModel):
    invoice_id: int
    amount: float = Field(gt=0)
    paid_on: date
    method: PaymentMethod = PaymentMethod.bank_transfer
    reference: str | None = None


class PaymentOut(PaymentCreate):
    model_config = ORM
    id: int
    created_at: datetime


class RentRunRequest(BaseModel):
    """Generate rent invoices for every active lease for a given month."""

    year: int
    month: int = Field(ge=1, le=12)
    property_id: int | None = None


class RentRunResult(BaseModel):
    created: int
    skipped: int
    total_billed: float
    invoice_ids: list[int] = []


# ----------------------------- maintenance -------------------------------- #
class TicketBase(BaseModel):
    property_id: int
    unit_id: int | None = None
    reported_by_id: int | None = None
    title: str
    description: str | None = None
    category: str | None = None
    priority: Priority = Priority.medium
    status: TicketStatus = TicketStatus.open
    assignee: str | None = None
    cost: float = 0
    reported_at: date
    resolved_at: date | None = None


class TicketCreate(TicketBase):
    pass


class TicketUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    category: str | None = None
    priority: Priority | None = None
    status: TicketStatus | None = None
    assignee: str | None = None
    cost: float | None = None
    resolved_at: date | None = None


class TicketOut(TicketBase):
    model_config = ORM
    id: int
    property_name: str | None = None
    unit_name: str | None = None
    days_open: int = 0


# ------------------------------ expenses ---------------------------------- #
class ExpenseBase(BaseModel):
    property_id: int
    category: ExpenseCategory = ExpenseCategory.other
    vendor: str | None = None
    description: str | None = None
    amount: float
    spent_on: date


class ExpenseCreate(ExpenseBase):
    pass


class ExpenseOut(ExpenseBase):
    model_config = ORM
    id: int
    property_name: str | None = None


# ------------------------------ analytics --------------------------------- #
class KpiSummary(BaseModel):
    as_of: date
    currency: str
    total_properties: int
    total_units: int
    total_beds: int
    occupied_units: int
    occupancy_rate: float
    long_stay_occupancy: float
    short_stay_occupancy: float
    monthly_recurring_revenue: float
    billed_this_month: float
    collected_this_month: float
    collection_rate: float
    outstanding_balance: float
    overdue_invoices: int
    adr: float
    revpar: float
    open_tickets: int
    urgent_tickets: int
    expenses_this_month: float
    net_operating_income: float
    active_leases: int
    leases_expiring_60d: int
    arrivals_today: int
    departures_today: int


class TrendPoint(BaseModel):
    period: str
    revenue: float = 0
    collected: float = 0
    expenses: float = 0
    occupancy: float = 0


class NamedValue(BaseModel):
    label: str
    value: float
    secondary: float = 0


class PropertyPerformance(BaseModel):
    property_id: int
    property_name: str
    type: PropertyType
    units: int
    occupancy_rate: float
    revenue_ytd: float
    collected_ytd: float
    expenses_ytd: float
    noi_ytd: float
    arrears: float
    avg_rent: float


class ArrearsRow(BaseModel):
    person_id: int
    person_name: str
    email: str | None = None
    phone: str | None = None
    current: float = 0
    d1_30: float = 0
    d31_60: float = 0
    d61_90: float = 0
    d90_plus: float = 0
    total: float = 0


class Recommendation(BaseModel):
    severity: str          # info | warning | critical
    area: str              # pricing | occupancy | collections | maintenance | channel
    title: str
    detail: str
    impact_estimate: float = 0


Token.model_rebuild()
