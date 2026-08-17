from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..deps import get_current_user, require_manager, require_staff
from ..models import (
    Bed,
    Booking,
    BookingStatus,
    ChargeType,
    HousekeepingStatus,
    Invoice,
    InvoiceStatus,
    Person,
    Unit,
    User,
)
from ..schemas import AvailableUnit, BookingCreate, BookingOut, BookingUpdate
from ..services import is_slot_free, available_inventory, new_booking_reference, next_invoice_number

router = APIRouter(prefix="/api/bookings", tags=["bookings"])


def _to_out(db: Session, bk: Booking) -> BookingOut:
    out = BookingOut.model_validate(bk)
    out.nights = bk.nights
    out.guest_name = bk.person.full_name if bk.person else None
    out.unit_name = bk.unit.name if bk.unit else None
    out.bed_label = bk.bed.label if bk.bed else None
    out.property_name = bk.unit.property.name if bk.unit and bk.unit.property else None
    invoices = (
        db.query(Invoice)
        .filter(Invoice.booking_id == bk.id, Invoice.status != InvoiceStatus.void)
        .all()
    )
    out.balance = round(sum(i.balance for i in invoices), 2)
    return out


@router.get("/availability", response_model=list[AvailableUnit])
def availability(
    check_in: date,
    check_out: date,
    property_id: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    if check_out <= check_in:
        raise HTTPException(422, "check_out must be after check_in")
    return [AvailableUnit(**row) for row in available_inventory(db, check_in, check_out, property_id)]


@router.get("", response_model=list[BookingOut])
def list_bookings(
    status: BookingStatus | None = None,
    property_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 500,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(Booking).options(
        joinedload(Booking.unit).joinedload(Unit.property),
        joinedload(Booking.person),
        joinedload(Booking.bed),
    )
    if status:
        q = q.filter(Booking.status == status)
    if date_from:
        q = q.filter(Booking.check_out >= date_from)
    if date_to:
        q = q.filter(Booking.check_in <= date_to)
    rows = q.order_by(Booking.check_in.desc()).limit(limit).all()
    if property_id:
        rows = [b for b in rows if b.unit and b.unit.property_id == property_id]
    return [_to_out(db, b) for b in rows]


@router.get("/today")
def today_board(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Front-desk board: arrivals, departures and in-house guests for today."""
    today = date.today()
    # Everyone due in today, whether or not they have reached the desk yet.
    arrivals = db.query(Booking).filter(
        Booking.check_in == today,
        Booking.status.in_([BookingStatus.pending, BookingStatus.confirmed, BookingStatus.checked_in]),
    ).order_by(Booking.status).all()
    # Everyone due out today who has not been checked out.
    departures = db.query(Booking).filter(
        Booking.check_out == today,
        Booking.status.in_([BookingStatus.checked_in, BookingStatus.confirmed]),
    ).all()
    in_house = db.query(Booking).filter(
        Booking.status == BookingStatus.checked_in,
        Booking.check_in <= today,
        Booking.check_out > today,
    ).all()
    return {
        "date": today,
        "arrivals": [_to_out(db, b) for b in arrivals],
        "departures": [_to_out(db, b) for b in departures],
        "in_house": [_to_out(db, b) for b in in_house],
    }


@router.get("/{booking_id}", response_model=BookingOut)
def get_booking(booking_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    bk = db.get(Booking, booking_id)
    if not bk:
        raise HTTPException(404, "Booking not found")
    return _to_out(db, bk)


@router.post("", response_model=BookingOut, status_code=201)
def create_booking(
    payload: BookingCreate,
    auto_invoice: bool = Query(True, description="Raise an accommodation invoice on creation"),
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
):
    unit = db.get(Unit, payload.unit_id)
    if not unit:
        raise HTTPException(404, "Unit not found")
    if not db.get(Person, payload.person_id):
        raise HTTPException(404, "Guest not found")
    if payload.bed_id and not db.get(Bed, payload.bed_id):
        raise HTTPException(404, "Bed not found")

    if not is_slot_free(db, payload.unit_id, payload.check_in, payload.check_out, payload.bed_id):
        raise HTTPException(409, "That unit/bed is already booked for those dates")

    nights = (payload.check_out - payload.check_in).days
    bk = Booking(
        **payload.model_dump(),
        reference=new_booking_reference(db),
    )
    bk.total_amount = round(float(payload.nightly_rate) * nights, 2)
    db.add(bk)
    db.flush()

    if auto_invoice and bk.total_amount > 0:
        db.add(
            Invoice(
                number=next_invoice_number(db, payload.check_in),
                person_id=payload.person_id,
                property_id=unit.property_id,
                booking_id=bk.id,
                charge_type=ChargeType.accommodation,
                description=f"{nights} night(s) - {unit.name} ({bk.reference})",
                issue_date=date.today(),
                due_date=payload.check_in,
                period_start=payload.check_in,
                period_end=payload.check_out,
                amount=bk.total_amount,
                status=InvoiceStatus.open,
            )
        )

    db.commit()
    db.refresh(bk)
    return _to_out(db, bk)


@router.patch("/{booking_id}", response_model=BookingOut)
def update_booking(
    booking_id: int,
    payload: BookingUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
):
    bk = db.get(Booking, booking_id)
    if not bk:
        raise HTTPException(404, "Booking not found")

    data = payload.model_dump(exclude_unset=True)
    new_in = data.get("check_in", bk.check_in)
    new_out = data.get("check_out", bk.check_out)
    new_bed = data.get("bed_id", bk.bed_id)
    if new_out <= new_in:
        raise HTTPException(422, "check_out must be after check_in")

    moving = ("check_in" in data or "check_out" in data or "bed_id" in data)
    if moving and not is_slot_free(db, bk.unit_id, new_in, new_out, new_bed, exclude_booking_id=bk.id):
        raise HTTPException(409, "Conflicts with an existing booking")

    for field, value in data.items():
        setattr(bk, field, value)
    bk.total_amount = round(float(bk.nightly_rate) * bk.nights, 2)

    if bk.status == BookingStatus.checked_out and bk.unit:
        bk.unit.housekeeping = HousekeepingStatus.dirty

    db.commit()
    db.refresh(bk)
    return _to_out(db, bk)


@router.post("/{booking_id}/check-in", response_model=BookingOut)
def check_in(booking_id: int, db: Session = Depends(get_db), _: User = Depends(require_staff)):
    bk = db.get(Booking, booking_id)
    if not bk:
        raise HTTPException(404, "Booking not found")
    if bk.status in (BookingStatus.cancelled, BookingStatus.no_show):
        raise HTTPException(409, "Cannot check in a cancelled booking")
    bk.status = BookingStatus.checked_in
    db.commit()
    db.refresh(bk)
    return _to_out(db, bk)


@router.post("/{booking_id}/check-out", response_model=BookingOut)
def check_out(booking_id: int, db: Session = Depends(get_db), _: User = Depends(require_staff)):
    bk = db.get(Booking, booking_id)
    if not bk:
        raise HTTPException(404, "Booking not found")
    bk.status = BookingStatus.checked_out
    if bk.unit:
        bk.unit.housekeeping = HousekeepingStatus.dirty
    db.commit()
    db.refresh(bk)
    return _to_out(db, bk)


@router.delete("/{booking_id}", status_code=204)
def delete_booking(booking_id: int, db: Session = Depends(get_db), _: User = Depends(require_manager)):
    bk = db.get(Booking, booking_id)
    if not bk:
        raise HTTPException(404, "Booking not found")
    db.delete(bk)
    db.commit()
