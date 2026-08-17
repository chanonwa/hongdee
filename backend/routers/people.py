from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, require_staff
from ..models import Invoice, InvoiceStatus, Payment, Person, PersonType, User
from ..schemas import PersonCreate, PersonOut, PersonUpdate

router = APIRouter(prefix="/api/people", tags=["people"])


def _balances(db: Session, person_ids: list[int]) -> dict[int, float]:
    """Outstanding balance per person across all non-void invoices."""
    if not person_ids:
        return {}
    rows = (
        db.query(Invoice)
        .filter(Invoice.person_id.in_(person_ids), Invoice.status != InvoiceStatus.void)
        .all()
    )
    out: dict[int, float] = {}
    for inv in rows:
        out[inv.person_id] = round(out.get(inv.person_id, 0.0) + inv.balance, 2)
    return out


@router.get("", response_model=list[PersonOut])
def list_people(
    type: PersonType | None = None,
    q: str | None = Query(None, description="Search name, email or phone"),
    limit: int = 200,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = db.query(Person)
    if type:
        query = query.filter(Person.type == type)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(Person.full_name.ilike(like), Person.email.ilike(like), Person.phone.ilike(like))
        )
    people = query.order_by(Person.full_name).limit(limit).all()
    bal = _balances(db, [p.id for p in people])
    result = []
    for p in people:
        out = PersonOut.model_validate(p)
        out.balance = bal.get(p.id, 0.0)
        result.append(out)
    return result


@router.get("/{person_id}", response_model=PersonOut)
def get_person(person_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    person = db.get(Person, person_id)
    if not person:
        raise HTTPException(404, "Person not found")
    out = PersonOut.model_validate(person)
    out.balance = _balances(db, [person_id]).get(person_id, 0.0)
    return out


@router.post("", response_model=PersonOut, status_code=201)
def create_person(
    payload: PersonCreate, db: Session = Depends(get_db), _: User = Depends(require_staff)
):
    person = Person(**payload.model_dump())
    db.add(person)
    db.commit()
    db.refresh(person)
    return PersonOut.model_validate(person)


@router.patch("/{person_id}", response_model=PersonOut)
def update_person(
    person_id: int,
    payload: PersonUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
):
    person = db.get(Person, person_id)
    if not person:
        raise HTTPException(404, "Person not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(person, field, value)
    db.commit()
    db.refresh(person)
    return PersonOut.model_validate(person)


@router.delete("/{person_id}", status_code=204)
def delete_person(person_id: int, db: Session = Depends(get_db), _: User = Depends(require_staff)):
    person = db.get(Person, person_id)
    if not person:
        raise HTTPException(404, "Person not found")
    db.delete(person)
    db.commit()
