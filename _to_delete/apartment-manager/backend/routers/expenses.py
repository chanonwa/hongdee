from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, require_manager, require_staff
from ..models import Expense, ExpenseCategory, Property, User
from ..schemas import ExpenseCreate, ExpenseOut

router = APIRouter(prefix="/api/expenses", tags=["expenses"])


def _to_out(db: Session, e: Expense) -> ExpenseOut:
    out = ExpenseOut.model_validate(e)
    prop = db.get(Property, e.property_id)
    out.property_name = prop.name if prop else None
    return out


@router.get("", response_model=list[ExpenseOut])
def list_expenses(
    property_id: int | None = None,
    category: ExpenseCategory | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 500,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(Expense)
    if property_id:
        q = q.filter(Expense.property_id == property_id)
    if category:
        q = q.filter(Expense.category == category)
    if date_from:
        q = q.filter(Expense.spent_on >= date_from)
    if date_to:
        q = q.filter(Expense.spent_on <= date_to)
    return [_to_out(db, e) for e in q.order_by(Expense.spent_on.desc()).limit(limit).all()]


@router.post("", response_model=ExpenseOut, status_code=201)
def create_expense(
    payload: ExpenseCreate, db: Session = Depends(get_db), _: User = Depends(require_staff)
):
    if not db.get(Property, payload.property_id):
        raise HTTPException(404, "Property not found")
    e = Expense(**payload.model_dump())
    db.add(e)
    db.commit()
    db.refresh(e)
    return _to_out(db, e)


@router.delete("/{expense_id}", status_code=204)
def delete_expense(expense_id: int, db: Session = Depends(get_db), _: User = Depends(require_manager)):
    e = db.get(Expense, expense_id)
    if not e:
        raise HTTPException(404, "Expense not found")
    db.delete(e)
    db.commit()
