from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, require_manager, require_staff
from ..models import (
    HousekeepingStatus,
    MaintenanceTicket,
    Person,
    Priority,
    Property,
    TicketStatus,
    Unit,
    UnitStatus,
    User,
)
from ..schemas import TicketCreate, TicketOut, TicketUpdate

router = APIRouter(prefix="/api/maintenance", tags=["maintenance"])


def _to_out(db: Session, t: MaintenanceTicket) -> TicketOut:
    out = TicketOut.model_validate(t)
    prop = db.get(Property, t.property_id)
    out.property_name = prop.name if prop else None
    if t.unit_id:
        unit = db.get(Unit, t.unit_id)
        out.unit_name = unit.name if unit else None
    end = t.resolved_at or date.today()
    out.days_open = max((end - t.reported_at).days, 0)
    return out


@router.get("", response_model=list[TicketOut])
def list_tickets(
    status: TicketStatus | None = None,
    priority: Priority | None = None,
    property_id: int | None = None,
    open_only: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(MaintenanceTicket)
    if status:
        q = q.filter(MaintenanceTicket.status == status)
    if priority:
        q = q.filter(MaintenanceTicket.priority == priority)
    if property_id:
        q = q.filter(MaintenanceTicket.property_id == property_id)
    if open_only:
        q = q.filter(
            MaintenanceTicket.status.in_(
                [TicketStatus.open, TicketStatus.in_progress, TicketStatus.on_hold]
            )
        )
    rows = q.order_by(MaintenanceTicket.reported_at.desc()).all()
    return [_to_out(db, t) for t in rows]


@router.get("/{ticket_id}", response_model=TicketOut)
def get_ticket(ticket_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    t = db.get(MaintenanceTicket, ticket_id)
    if not t:
        raise HTTPException(404, "Ticket not found")
    return _to_out(db, t)


@router.post("", response_model=TicketOut, status_code=201)
def create_ticket(
    payload: TicketCreate, db: Session = Depends(get_db), _: User = Depends(require_staff)
):
    if not db.get(Property, payload.property_id):
        raise HTTPException(404, "Property not found")
    if payload.unit_id and not db.get(Unit, payload.unit_id):
        raise HTTPException(404, "Unit not found")
    if payload.reported_by_id and not db.get(Person, payload.reported_by_id):
        raise HTTPException(404, "Reporter not found")
    t = MaintenanceTicket(**payload.model_dump())
    db.add(t)

    # An urgent ticket takes the unit off sale until resolved.
    if t.unit_id and t.priority == Priority.urgent:
        unit = db.get(Unit, t.unit_id)
        if unit:
            unit.status = UnitStatus.maintenance
            unit.housekeeping = HousekeepingStatus.out_of_service

    db.commit()
    db.refresh(t)
    return _to_out(db, t)


@router.patch("/{ticket_id}", response_model=TicketOut)
def update_ticket(
    ticket_id: int,
    payload: TicketUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
):
    t = db.get(MaintenanceTicket, ticket_id)
    if not t:
        raise HTTPException(404, "Ticket not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(t, field, value)

    if t.status in (TicketStatus.resolved, TicketStatus.closed):
        t.resolved_at = t.resolved_at or date.today()
        if t.unit_id:
            unit = db.get(Unit, t.unit_id)
            if unit and unit.status == UnitStatus.maintenance:
                unit.status = UnitStatus.available
                unit.housekeeping = HousekeepingStatus.dirty

    db.commit()
    db.refresh(t)
    return _to_out(db, t)


@router.delete("/{ticket_id}", status_code=204)
def delete_ticket(ticket_id: int, db: Session = Depends(get_db), _: User = Depends(require_manager)):
    t = db.get(MaintenanceTicket, ticket_id)
    if not t:
        raise HTTPException(404, "Ticket not found")
    db.delete(t)
    db.commit()
