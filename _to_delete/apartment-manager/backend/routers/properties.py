from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, require_manager
from ..models import Property, Unit, User
from ..schemas import PropertyCreate, PropertyOut, PropertyUpdate

router = APIRouter(prefix="/api/properties", tags=["properties"])


def _to_out(prop: Property, unit_count: int) -> PropertyOut:
    data = PropertyOut.model_validate(prop)
    data.unit_count = unit_count
    return data


@router.get("", response_model=list[PropertyOut])
def list_properties(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    counts = dict(
        db.query(Unit.property_id, func.count(Unit.id)).group_by(Unit.property_id).all()
    )
    props = db.query(Property).order_by(Property.name).all()
    return [_to_out(p, counts.get(p.id, 0)) for p in props]


@router.get("/{property_id}", response_model=PropertyOut)
def get_property(property_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    prop = db.get(Property, property_id)
    if not prop:
        raise HTTPException(404, "Property not found")
    count = db.query(func.count(Unit.id)).filter(Unit.property_id == property_id).scalar() or 0
    return _to_out(prop, count)


@router.post("", response_model=PropertyOut, status_code=201)
def create_property(
    payload: PropertyCreate, db: Session = Depends(get_db), _: User = Depends(require_manager)
):
    if db.query(Property).filter(Property.code == payload.code).first():
        raise HTTPException(409, "Property code already in use")
    prop = Property(**payload.model_dump())
    db.add(prop)
    db.commit()
    db.refresh(prop)
    return _to_out(prop, 0)


@router.patch("/{property_id}", response_model=PropertyOut)
def update_property(
    property_id: int,
    payload: PropertyUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_manager),
):
    prop = db.get(Property, property_id)
    if not prop:
        raise HTTPException(404, "Property not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(prop, field, value)
    db.commit()
    db.refresh(prop)
    count = db.query(func.count(Unit.id)).filter(Unit.property_id == property_id).scalar() or 0
    return _to_out(prop, count)


@router.delete("/{property_id}", status_code=204)
def delete_property(
    property_id: int, db: Session = Depends(get_db), _: User = Depends(require_manager)
):
    prop = db.get(Property, property_id)
    if not prop:
        raise HTTPException(404, "Property not found")
    db.delete(prop)
    db.commit()
