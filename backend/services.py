"""Business rules shared by routers: numbering, availability, occupancy, invoicing."""
from __future__ import annotations

import calendar
import random
import string
from datetime import date, timedelta

from sqlalchemy import Integer, cast, func, or_
from sqlalchemy.orm import Session

from .models import (
    Bed,
    Booking,
    BookingStatus,
    ChargeType,
    Invoice,
    InvoiceStatus,
    Lease,
    LeaseStatus,
    Unit,
    UnitType,
)

BLOCKING_BOOKING_STATUSES = (
    BookingStatus.pending,
    BookingStatus.confirmed,
    BookingStatus.checked_in,
)


# --------------------------------------------------------------------------- #
# Numbering
# --------------------------------------------------------------------------- #
def next_invoice_number(db: Session, when: date | None = None) -> str:
    """Next free number for the month: highest existing sequence + 1.

    Counting rows would hand out a number that is already taken as soon as an invoice
    has been deleted, or when numbers came from another sequence (as the demo seed's do).
    """
    when = when or date.today()
    prefix = f"INV-{when:%Y%m}-"
    highest = (
        db.query(func.max(cast(func.substr(Invoice.number, len(prefix) + 1), Integer)))
        .filter(Invoice.number.like(f"{prefix}%"))
        .scalar()
    )
    return f"{prefix}{(highest or 0) + 1:04d}"


def new_booking_reference(db: Session) -> str:
    alphabet = string.ascii_uppercase + string.digits
    while True:
        ref = "BK-" + "".join(random.choices(alphabet, k=6))
        if not db.query(Booking.id).filter(Booking.reference == ref).first():
            return ref


# --------------------------------------------------------------------------- #
# Date helpers
# --------------------------------------------------------------------------- #
def month_bounds(year: int, month: int) -> tuple[date, date]:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def overlaps(a_start: date, a_end: date, b_start: date, b_end: date) -> bool:
    """Half-open interval overlap: [start, end)."""
    return a_start < b_end and b_start < a_end


def daterange_nights(start: date, end: date):
    d = start
    while d < end:
        yield d
        d += timedelta(days=1)


# --------------------------------------------------------------------------- #
# Availability
# --------------------------------------------------------------------------- #
def conflicting_bookings(
    db: Session,
    check_in: date,
    check_out: date,
    unit_ids: list[int] | None = None,
    exclude_booking_id: int | None = None,
) -> list[Booking]:
    q = db.query(Booking).filter(
        Booking.status.in_(BLOCKING_BOOKING_STATUSES),
        Booking.check_in < check_out,
        Booking.check_out > check_in,
    )
    if unit_ids:
        q = q.filter(Booking.unit_id.in_(unit_ids))
    if exclude_booking_id:
        q = q.filter(Booking.id != exclude_booking_id)
    return q.all()


def is_slot_free(
    db: Session,
    unit_id: int,
    check_in: date,
    check_out: date,
    bed_id: int | None = None,
    exclude_booking_id: int | None = None,
) -> bool:
    """A bed booking clashes only with the same bed; a whole-unit booking clashes with anything."""
    clashes = conflicting_bookings(db, check_in, check_out, [unit_id], exclude_booking_id)
    if bed_id is None:
        return not clashes
    return not any(b.bed_id == bed_id or b.bed_id is None for b in clashes)


def available_inventory(
    db: Session, check_in: date, check_out: date, property_id: int | None = None
) -> list[dict]:
    """Return short-stay units with their free beds for the requested window."""
    q = db.query(Unit).filter(Unit.type.in_([UnitType.dorm, UnitType.private_room]))
    if property_id:
        q = q.filter(Unit.property_id == property_id)
    units = q.all()
    unit_ids = [u.id for u in units]
    clashes = conflicting_bookings(db, check_in, check_out, unit_ids)

    taken_beds: dict[int, set[int]] = {}
    whole_unit_taken: set[int] = set()
    for b in clashes:
        if b.bed_id is None:
            whole_unit_taken.add(b.unit_id)
        else:
            taken_beds.setdefault(b.unit_id, set()).add(b.bed_id)

    result = []
    for u in units:
        beds = [b for b in u.beds if b.id not in taken_beds.get(u.id, set())]
        whole_free = u.id not in whole_unit_taken and not taken_beds.get(u.id)
        if u.type == UnitType.dorm:
            if u.id in whole_unit_taken or not beds:
                continue
        elif not whole_free:
            continue
        result.append(
            {
                "unit_id": u.id,
                "unit_name": u.name,
                "property_name": u.property.name if u.property else "",
                "type": u.type,
                "nightly_rate": float(u.nightly_rate) if u.nightly_rate else None,
                "free_beds": beds,
                "whole_unit_available": whole_free,
            }
        )
    return result


# --------------------------------------------------------------------------- #
# Occupancy
# --------------------------------------------------------------------------- #
def leases_active_on(db: Session, day: date) -> list[Lease]:
    return (
        db.query(Lease)
        .filter(
            Lease.status.in_([LeaseStatus.active, LeaseStatus.notice_given]),
            Lease.start_date <= day,
            or_(Lease.end_date.is_(None), Lease.end_date >= day),
        )
        .all()
    )


def bookings_on(db: Session, day: date) -> list[Booking]:
    return (
        db.query(Booking)
        .filter(
            Booking.status.in_([BookingStatus.confirmed, BookingStatus.checked_in, BookingStatus.checked_out]),
            Booking.check_in <= day,
            Booking.check_out > day,
        )
        .all()
    )


def occupancy_on(db: Session, day: date) -> dict:
    """Occupancy split by long-stay units and short-stay beds."""
    long_units = db.query(Unit).filter(Unit.type.in_([UnitType.apartment, UnitType.studio])).all()
    short_units = db.query(Unit).filter(Unit.type.in_([UnitType.dorm, UnitType.private_room])).all()

    long_total = len(long_units)
    long_occupied = len({l.unit_id for l in leases_active_on(db, day)})

    short_capacity = 0
    for u in short_units:
        short_capacity += len(u.beds) if u.beds else max(u.capacity, 1)

    short_sold = 0
    for b in bookings_on(db, day):
        if b.bed_id is not None:
            short_sold += 1
        else:
            unit = b.unit
            short_sold += len(unit.beds) if (unit and unit.beds) else 1

    return {
        "long_total": long_total,
        "long_occupied": long_occupied,
        "long_rate": round(long_occupied / long_total * 100, 1) if long_total else 0.0,
        "short_capacity": short_capacity,
        "short_sold": min(short_sold, short_capacity) if short_capacity else 0,
        "short_rate": round(min(short_sold, short_capacity) / short_capacity * 100, 1)
        if short_capacity
        else 0.0,
    }


# --------------------------------------------------------------------------- #
# Invoicing
# --------------------------------------------------------------------------- #
def refresh_invoice_status(invoice: Invoice, today: date | None = None) -> None:
    today = today or date.today()
    if invoice.status == InvoiceStatus.void:
        return
    if invoice.balance <= 0.005:
        invoice.status = InvoiceStatus.paid
    elif invoice.paid > 0:
        invoice.status = InvoiceStatus.partial if invoice.due_date >= today else InvoiceStatus.overdue
    else:
        invoice.status = InvoiceStatus.open if invoice.due_date >= today else InvoiceStatus.overdue


def sync_all_invoice_statuses(db: Session, today: date | None = None) -> int:
    today = today or date.today()
    changed = 0
    for inv in db.query(Invoice).filter(Invoice.status != InvoiceStatus.void).all():
        before = inv.status
        refresh_invoice_status(inv, today)
        if inv.status != before:
            changed += 1
    if changed:
        db.commit()
    return changed


def generate_rent_invoices(
    db: Session, year: int, month: int, property_id: int | None = None
) -> tuple[list[Invoice], int]:
    """Idempotent monthly rent run for active leases. Returns (created, skipped)."""
    period_start, period_end = month_bounds(year, month)
    created: list[Invoice] = []
    skipped = 0

    leases = (
        db.query(Lease)
        .filter(Lease.status.in_([LeaseStatus.active, LeaseStatus.notice_given]))
        .all()
    )
    for lease in leases:
        if property_id and lease.unit.property_id != property_id:
            continue
        # Lease must be live at some point during the month.
        if lease.start_date > period_end:
            continue
        if lease.end_date and lease.end_date < period_start:
            continue

        exists = (
            db.query(Invoice)
            .filter(
                Invoice.lease_id == lease.id,
                Invoice.charge_type == ChargeType.rent,
                Invoice.period_start == period_start,
            )
            .first()
        )
        if exists:
            skipped += 1
            continue

        due_day = min(lease.billing_day, calendar.monthrange(year, month)[1])
        invoice = Invoice(
            number=next_invoice_number(db, period_start),
            person_id=lease.person_id,
            property_id=lease.unit.property_id,
            lease_id=lease.id,
            charge_type=ChargeType.rent,
            description=f"Rent {period_start:%b %Y} - {lease.unit.property.name} {lease.unit.name}",
            issue_date=period_start,
            due_date=date(year, month, due_day),
            period_start=period_start,
            period_end=period_end,
            amount=float(lease.rent_amount),
            status=InvoiceStatus.open,
        )
        db.add(invoice)
        db.flush()
        created.append(invoice)

    db.commit()
    return created, skipped
