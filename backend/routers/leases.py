from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..deps import get_current_user, require_manager, require_staff
from ..models import Invoice, InvoiceStatus, Lease, LeaseStatus, Person, Unit, UnitStatus, User
from ..schemas import LeaseCreate, LeaseOut, LeaseUpdate

router = APIRouter(prefix="/api/leases", tags=["leases"])


def _to_out(db: Session, lease: Lease) -> LeaseOut:
    out = LeaseOut.model_validate(lease)
    out.tenant_name = lease.person.full_name if lease.person else None
    out.unit_name = lease.unit.name if lease.unit else None
    out.property_name = lease.unit.property.name if lease.unit and lease.unit.property else None
    invoices = (
        db.query(Invoice)
        .filter(Invoice.lease_id == lease.id, Invoice.status != InvoiceStatus.void)
        .all()
    )
    out.balance = round(sum(i.balance for i in invoices), 2)
    return out


@router.get("", response_model=list[LeaseOut])
def list_leases(
    status: LeaseStatus | None = None,
    property_id: int | None = None,
    person_id: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(Lease).options(joinedload(Lease.unit).joinedload(Unit.property), joinedload(Lease.person))
    if status:
        q = q.filter(Lease.status == status)
    if person_id:
        q = q.filter(Lease.person_id == person_id)
    leases = q.order_by(Lease.start_date.desc()).all()
    if property_id:
        leases = [l for l in leases if l.unit and l.unit.property_id == property_id]
    return [_to_out(db, l) for l in leases]


@router.get("/expiring", response_model=list[LeaseOut])
def expiring_leases(
    days: int = 60, db: Session = Depends(get_db), _: User = Depends(get_current_user)
):
    from datetime import timedelta

    horizon = date.today() + timedelta(days=days)
    leases = (
        db.query(Lease)
        .filter(
            Lease.status.in_([LeaseStatus.active, LeaseStatus.notice_given]),
            Lease.end_date.isnot(None),
            Lease.end_date <= horizon,
            Lease.end_date >= date.today(),
        )
        .order_by(Lease.end_date)
        .all()
    )
    return [_to_out(db, l) for l in leases]


@router.get("/{lease_id}", response_model=LeaseOut)
def get_lease(lease_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    lease = db.get(Lease, lease_id)
    if not lease:
        raise HTTPException(404, "Lease not found")
    return _to_out(db, lease)


@router.post("", response_model=LeaseOut, status_code=201)
def create_lease(
    payload: LeaseCreate, db: Session = Depends(get_db), _: User = Depends(require_staff)
):
    unit = db.get(Unit, payload.unit_id)
    if not unit:
        raise HTTPException(404, "Unit not found")
    if not db.get(Person, payload.person_id):
        raise HTTPException(404, "Tenant not found")

    # Reject overlapping active tenancies on the same unit.
    if payload.status in (LeaseStatus.active, LeaseStatus.notice_given):
        existing = (
            db.query(Lease)
            .filter(
                Lease.unit_id == payload.unit_id,
                Lease.status.in_([LeaseStatus.active, LeaseStatus.notice_given]),
            )
            .all()
        )
        new_end = payload.end_date or date(9999, 12, 31)
        for l in existing:
            cur_end = l.end_date or date(9999, 12, 31)
            if payload.start_date <= cur_end and l.start_date <= new_end:
                raise HTTPException(
                    409, f"Unit already let under lease #{l.id} ({l.start_date} to {l.end_date or 'open'})"
                )

    lease = Lease(**payload.model_dump())
    db.add(lease)
    if lease.status in (LeaseStatus.active, LeaseStatus.notice_given):
        unit.status = UnitStatus.occupied
    db.commit()
    db.refresh(lease)
    return _to_out(db, lease)


@router.patch("/{lease_id}", response_model=LeaseOut)
def update_lease(
    lease_id: int,
    payload: LeaseUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
):
    lease = db.get(Lease, lease_id)
    if not lease:
        raise HTTPException(404, "Lease not found")
    data = payload.model_dump(exclude_unset=True)
    end = data.get("end_date", lease.end_date)
    if end and end < lease.start_date:
        raise HTTPException(422, "end_date must be on or after start_date")
    for field, value in data.items():
        setattr(lease, field, value)
    if lease.status in (LeaseStatus.ended, LeaseStatus.terminated) and lease.unit:
        lease.unit.status = UnitStatus.available
    db.commit()
    db.refresh(lease)
    return _to_out(db, lease)


@router.delete("/{lease_id}", status_code=204)
def delete_lease(lease_id: int, db: Session = Depends(get_db), _: User = Depends(require_manager)):
    lease = db.get(Lease, lease_id)
    if not lease:
        raise HTTPException(404, "Lease not found")
    db.delete(lease)
    db.commit()
