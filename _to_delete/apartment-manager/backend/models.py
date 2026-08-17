"""SQLAlchemy ORM models.

The schema deliberately unifies two businesses that most products split apart:

* long-stay residential lettings (apartments -> units -> leases -> recurring rent)
* short-stay hostel operation   (hostels -> dorms -> beds -> bookings -> nightly rate)

Both revenue streams settle into the same Invoice/Payment ledger, which is what
makes portfolio-wide analytics possible.
"""
from __future__ import annotations

import enum
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #
class Role(str, enum.Enum):
    admin = "admin"
    manager = "manager"
    staff = "staff"
    viewer = "viewer"


class PropertyType(str, enum.Enum):
    apartment = "apartment"
    hostel = "hostel"
    mixed = "mixed"


class UnitType(str, enum.Enum):
    apartment = "apartment"          # long stay, whole unit
    studio = "studio"
    private_room = "private_room"    # short stay, whole room
    dorm = "dorm"                    # short stay, sold per bed


class UnitStatus(str, enum.Enum):
    available = "available"
    occupied = "occupied"
    reserved = "reserved"
    maintenance = "maintenance"
    offline = "offline"


class HousekeepingStatus(str, enum.Enum):
    clean = "clean"
    dirty = "dirty"
    inspected = "inspected"
    out_of_service = "out_of_service"


class PersonType(str, enum.Enum):
    tenant = "tenant"
    guest = "guest"
    prospect = "prospect"


class LeaseStatus(str, enum.Enum):
    draft = "draft"
    active = "active"
    notice_given = "notice_given"
    ended = "ended"
    terminated = "terminated"


class BookingStatus(str, enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    checked_in = "checked_in"
    checked_out = "checked_out"
    cancelled = "cancelled"
    no_show = "no_show"


class Channel(str, enum.Enum):
    direct = "direct"
    website = "website"
    walk_in = "walk_in"
    booking_com = "booking_com"
    hostelworld = "hostelworld"
    airbnb = "airbnb"
    agent = "agent"


class InvoiceStatus(str, enum.Enum):
    draft = "draft"
    open = "open"
    partial = "partial"
    paid = "paid"
    overdue = "overdue"
    void = "void"


class ChargeType(str, enum.Enum):
    rent = "rent"
    accommodation = "accommodation"
    deposit = "deposit"
    utilities = "utilities"
    late_fee = "late_fee"
    cleaning = "cleaning"
    extras = "extras"
    other = "other"


class PaymentMethod(str, enum.Enum):
    cash = "cash"
    card = "card"
    bank_transfer = "bank_transfer"
    online = "online"
    standing_order = "standing_order"


class Priority(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    urgent = "urgent"


class TicketStatus(str, enum.Enum):
    open = "open"
    in_progress = "in_progress"
    on_hold = "on_hold"
    resolved = "resolved"
    closed = "closed"


class ExpenseCategory(str, enum.Enum):
    repairs = "repairs"
    utilities = "utilities"
    cleaning = "cleaning"
    insurance = "insurance"
    taxes = "taxes"
    mortgage = "mortgage"
    marketing = "marketing"
    salaries = "salaries"
    supplies = "supplies"
    other = "other"


# --------------------------------------------------------------------------- #
# Core tables
# --------------------------------------------------------------------------- #
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.staff)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Property(Base):
    __tablename__ = "properties"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    type: Mapped[PropertyType] = mapped_column(Enum(PropertyType), default=PropertyType.apartment)
    address_line1: Mapped[str | None] = mapped_column(String(200), nullable=True)
    city: Mapped[str | None] = mapped_column(String(80), nullable=True)
    postcode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    country: Mapped[str | None] = mapped_column(String(80), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="GBP")
    purchase_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    units: Mapped[list["Unit"]] = relationship(back_populates="property", cascade="all, delete-orphan")


class Unit(Base):
    """A lettable space: a flat, a private room, or a dorm room."""

    __tablename__ = "units"
    __table_args__ = (UniqueConstraint("property_id", "name", name="uq_unit_per_property"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    type: Mapped[UnitType] = mapped_column(Enum(UnitType), default=UnitType.apartment)
    floor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bedrooms: Mapped[int] = mapped_column(Integer, default=1)
    bathrooms: Mapped[float] = mapped_column(Float, default=1.0)
    size_sqm: Mapped[float | None] = mapped_column(Float, nullable=True)
    capacity: Mapped[int] = mapped_column(Integer, default=1)
    market_rent: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)   # per month
    nightly_rate: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)  # per night
    status: Mapped[UnitStatus] = mapped_column(Enum(UnitStatus), default=UnitStatus.available)
    housekeeping: Mapped[HousekeepingStatus] = mapped_column(
        Enum(HousekeepingStatus), default=HousekeepingStatus.clean
    )
    amenities: Mapped[str | None] = mapped_column(Text, nullable=True)  # comma separated
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # NOTE: the attribute is called `property` for readability at call sites
    # (unit.property.name). That shadows the `property` builtin inside this
    # class body, so no @property descriptors may be declared below it.
    property: Mapped[Property] = relationship(back_populates="units")
    beds: Mapped[list["Bed"]] = relationship(back_populates="unit", cascade="all, delete-orphan")


class Bed(Base):
    """Individual bed inside a dorm - the sellable inventory for hostels."""

    __tablename__ = "beds"
    __table_args__ = (UniqueConstraint("unit_id", "label", name="uq_bed_per_unit"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(30))
    nightly_rate: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    status: Mapped[UnitStatus] = mapped_column(Enum(UnitStatus), default=UnitStatus.available)

    unit: Mapped[Unit] = relationship(back_populates="beds")


class Person(Base):
    """Tenants and guests share one contact record."""

    __tablename__ = "people"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[PersonType] = mapped_column(Enum(PersonType), default=PersonType.tenant)
    full_name: Mapped[str] = mapped_column(String(160), index=True)
    email: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    nationality: Mapped[str | None] = mapped_column(String(60), nullable=True)
    id_document: Mapped[str | None] = mapped_column(String(60), nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    emergency_contact: Mapped[str | None] = mapped_column(String(160), nullable=True)
    screening_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Lease(Base):
    """Long-stay residential agreement generating recurring monthly rent."""

    __tablename__ = "leases"

    id: Mapped[int] = mapped_column(primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    start_date: Mapped[date] = mapped_column(Date, index=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    rent_amount: Mapped[float] = mapped_column(Numeric(10, 2))
    billing_day: Mapped[int] = mapped_column(Integer, default=1)
    deposit_amount: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    deposit_scheme_ref: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[LeaseStatus] = mapped_column(Enum(LeaseStatus), default=LeaseStatus.active)
    notice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    unit: Mapped[Unit] = relationship()
    person: Mapped[Person] = relationship()


class Booking(Base):
    """Short-stay reservation against a unit or a specific bed."""

    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id", ondelete="CASCADE"), index=True)
    bed_id: Mapped[int | None] = mapped_column(ForeignKey("beds.id", ondelete="SET NULL"), nullable=True, index=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    check_in: Mapped[date] = mapped_column(Date, index=True)
    check_out: Mapped[date] = mapped_column(Date, index=True)
    guests: Mapped[int] = mapped_column(Integer, default=1)
    nightly_rate: Mapped[float] = mapped_column(Numeric(10, 2))
    total_amount: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    channel: Mapped[Channel] = mapped_column(Enum(Channel), default=Channel.direct)
    commission_rate: Mapped[float] = mapped_column(Float, default=0.0)  # 0.15 == 15%
    status: Mapped[BookingStatus] = mapped_column(Enum(BookingStatus), default=BookingStatus.confirmed)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    unit: Mapped[Unit] = relationship()
    bed: Mapped[Bed | None] = relationship()
    person: Mapped[Person] = relationship()

    @property
    def nights(self) -> int:
        return max((self.check_out - self.check_in).days, 0)


class Invoice(Base):
    """One ledger for rent and accommodation revenue alike."""

    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    property_id: Mapped[int | None] = mapped_column(ForeignKey("properties.id", ondelete="SET NULL"), nullable=True, index=True)
    lease_id: Mapped[int | None] = mapped_column(ForeignKey("leases.id", ondelete="SET NULL"), nullable=True, index=True)
    booking_id: Mapped[int | None] = mapped_column(ForeignKey("bookings.id", ondelete="SET NULL"), nullable=True, index=True)
    charge_type: Mapped[ChargeType] = mapped_column(Enum(ChargeType), default=ChargeType.rent)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    issue_date: Mapped[date] = mapped_column(Date, index=True)
    due_date: Mapped[date] = mapped_column(Date, index=True)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(10, 2))
    tax_amount: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    status: Mapped[InvoiceStatus] = mapped_column(Enum(InvoiceStatus), default=InvoiceStatus.open)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    person: Mapped[Person] = relationship()
    payments: Mapped[list["Payment"]] = relationship(back_populates="invoice", cascade="all, delete-orphan")

    @property
    def total(self) -> float:
        return float(self.amount or 0) + float(self.tax_amount or 0)

    @property
    def paid(self) -> float:
        return float(sum(float(p.amount) for p in self.payments))

    @property
    def balance(self) -> float:
        return round(self.total - self.paid, 2)


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    amount: Mapped[float] = mapped_column(Numeric(10, 2))
    paid_on: Mapped[date] = mapped_column(Date, index=True)
    method: Mapped[PaymentMethod] = mapped_column(Enum(PaymentMethod), default=PaymentMethod.bank_transfer)
    reference: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    invoice: Mapped[Invoice] = relationship(back_populates="payments")


class MaintenanceTicket(Base):
    __tablename__ = "maintenance_tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("units.id", ondelete="SET NULL"), nullable=True, index=True)
    reported_by_id: Mapped[int | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(60), nullable=True)
    priority: Mapped[Priority] = mapped_column(Enum(Priority), default=Priority.medium)
    status: Mapped[TicketStatus] = mapped_column(Enum(TicketStatus), default=TicketStatus.open)
    assignee: Mapped[str | None] = mapped_column(String(120), nullable=True)
    cost: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    reported_at: Mapped[date] = mapped_column(Date, index=True)
    resolved_at: Mapped[date | None] = mapped_column(Date, nullable=True)


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    category: Mapped[ExpenseCategory] = mapped_column(Enum(ExpenseCategory), default=ExpenseCategory.other)
    vendor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(10, 2))
    spent_on: Mapped[date] = mapped_column(Date, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
