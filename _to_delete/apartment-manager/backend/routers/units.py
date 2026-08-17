from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..deps import get_current_user, require_manager, require_staff
from ..models import Bed, Property, Unit, UnitStatus, UnitType, User
from ..schemas import BedCreate, BedOut, UnitCreate, UnitOut, UnitUpdate

router = APIRouter(prefix="/api/units", tags=["units"])


def _to_out(unit: Unit) -> UnitOut:
    out = UnitOut.model_validate(unit)
    out.property_name = unit.property.name if unit.property else None
    return out


@router.get("", response_model=list[UnitOut])
def list_units(
    property_id: int | None = None,
    type: UnitType | None = None,
    status: UnitStatus | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(Unit).options(joinedload(Unit.property), joinedload(Unit.beds))
    if property_id:
        q = q.filter(Unit.property_id == property_id)
    if type:
        q = q.filter(Unit.type == type)
    if status:
        q = q.filter(Unit.status == status)
    return [_to_out(u) for u in q.order_by(Unit.property_id, Unit.name).all()]


@router.get("/{unit_id}", response_model=UnitOut)
def get_unit(unit_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    unit = db.get(Unit, unit_id)
    if not unit:
        raise HTTPException(404, "Unit not found")
    return _to_out(unit)


@router.post("", response_model=UnitOut, status_code=201)
def create_unit(
    payload: UnitCreate, db: Session = Depends(get_db), _: User = Depends(require_manager)
):
    if not db.get(Property, payload.property_id):
        raise HTTPException(404, "Property not found")
    data = payload.model_dump(exclude={"bed_count"})
    unit = Unit(**data)
    db.add(unit)
    db.flush()

    if payload.bed_count > 0:
        for i in range(1, payload.bed_count + 1):
            db.add(Bed(unit_id=unit.id, label=f"{unit.name}-{i:02d}", nightly_rate=unit.nightly_rate))
        unit.capacity = max(unit.capacity, payload.bed_count)

    db.commit()
    db.refresh(unit)
    return _to_out(unit)


@router.patch("/{unit_id}", response_model=UnitOut)
def update_unit(
    unit_id: int,
    payload: UnitUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
):
    unit = db.get(Unit, unit_id)
    if not unit:
        raise HTTPException(404, "Unit not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(unit, field, value)
    db.commit()
    db.refresh(unit)
    return _to_out(unit)


@router.delete("/{unit_id}", status_code=204)
def delete_unit(unit_id: int, db: Session = Depends(get_db), _: User = Depends(require_manager)):
    unit = db.get(Unit, unit_id)
    if not unit:
        raise HTTPException(404, "Unit not found")
    db.delete(unit)
    db.commit()


# ------------------------------- beds ------------------------------------- #
@router.get("/{unit_id}/beds", response_model=list[BedOut])
def list_beds(unit_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(Bed).filter(Bed.unit_id == unit_id).order_by(Bed.label).all()


@router.post("/beds", response_model=BedOut, status_code=201)
def create_bed(payload: BedCreate, db: Session = Depends(get_db), _: User = Depends(require_manager)):
    if not db.get(Unit, payload.unit_id):
        raise HTTPException(404, "Unit not found")
    bed = Bed(**payload.model_dump())
    db.add(bed)
    db.commit()
    db.refresh(bed)
    return bed


@router.delete("/beds/{bed_id}", status_code=204)
def delete_bed(bed_id: int, db: Session = Depends(get_db), _: User = Depends(require_manager)):
    bed = db.get(Bed, bed_id)
    if not bed:
        raise HTTPException(404, "Bed not found")
    db.delete(bed)
    db.commit()
