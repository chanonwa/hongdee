from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..deps import get_current_user, require_manager, require_staff
from ..models import Invoice, InvoiceStatus, Payment, Person, User
from ..schemas import (
    ArrearsRow,
    InvoiceCreate,
    InvoiceOut,
    PaymentCreate,
    PaymentOut,
    RentRunRequest,
    RentRunResult,
)
from ..services import (
    generate_rent_invoices,
    next_invoice_number,
    refresh_invoice_status,
    sync_all_invoice_statuses,
)

router = APIRouter(prefix="/api/billing", tags=["billing"])


def _to_out(inv: Invoice) -> InvoiceOut:
    out = InvoiceOut.model_validate(inv)
    out.total = inv.total
    out.paid = inv.paid
    out.balance = inv.balance
    out.person_name = inv.person.full_name if inv.person else None
    return out


# ------------------------------ invoices ---------------------------------- #
@router.get("/invoices", response_model=list[InvoiceOut])
def list_invoices(
    status: InvoiceStatus | None = None,
    person_id: int | None = None,
    property_id: int | None = None,
    unpaid_only: bool = False,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 500,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(Invoice).options(joinedload(Invoice.person), joinedload(Invoice.payments))
    if status:
        q = q.filter(Invoice.status == status)
    if person_id:
        q = q.filter(Invoice.person_id == person_id)
    if property_id:
        q = q.filter(Invoice.property_id == property_id)
    if date_from:
        q = q.filter(Invoice.issue_date >= date_from)
    if date_to:
        q = q.filter(Invoice.issue_date <= date_to)
    rows = q.order_by(Invoice.issue_date.desc(), Invoice.id.desc()).limit(limit).all()
    out = [_to_out(i) for i in rows]
    if unpaid_only:
        out = [i for i in out if i.balance > 0.005 and i.status != InvoiceStatus.void]
    return out


@router.get("/invoices/{invoice_id}", response_model=InvoiceOut)
def get_invoice(invoice_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    inv = db.get(Invoice, invoice_id)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    return _to_out(inv)


@router.post("/invoices", response_model=InvoiceOut, status_code=201)
def create_invoice(
    payload: InvoiceCreate, db: Session = Depends(get_db), _: User = Depends(require_staff)
):
    if not db.get(Person, payload.person_id):
        raise HTTPException(404, "Person not found")
    inv = Invoice(**payload.model_dump(), number=next_invoice_number(db, payload.issue_date))
    db.add(inv)
    db.commit()
    db.refresh(inv)
    refresh_invoice_status(inv)
    db.commit()
    return _to_out(inv)


@router.post("/invoices/{invoice_id}/void", response_model=InvoiceOut)
def void_invoice(invoice_id: int, db: Session = Depends(get_db), _: User = Depends(require_manager)):
    inv = db.get(Invoice, invoice_id)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    inv.status = InvoiceStatus.void
    db.commit()
    db.refresh(inv)
    return _to_out(inv)


@router.post("/rent-run", response_model=RentRunResult)
def rent_run(
    payload: RentRunRequest, db: Session = Depends(get_db), _: User = Depends(require_manager)
):
    """Raise the monthly rent invoices for every active lease. Safe to re-run."""
    created, skipped = generate_rent_invoices(db, payload.year, payload.month, payload.property_id)
    return RentRunResult(
        created=len(created),
        skipped=skipped,
        total_billed=round(sum(float(i.amount) for i in created), 2),
        invoice_ids=[i.id for i in created],
    )


@router.post("/sync-statuses")
def sync_statuses(db: Session = Depends(get_db), _: User = Depends(require_staff)):
    """Recompute open/partial/paid/overdue across the ledger."""
    return {"updated": sync_all_invoice_statuses(db)}


# ------------------------------ payments ---------------------------------- #
@router.get("/payments", response_model=list[PaymentOut])
def list_payments(
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 500,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(Payment)
    if date_from:
        q = q.filter(Payment.paid_on >= date_from)
    if date_to:
        q = q.filter(Payment.paid_on <= date_to)
    return q.order_by(Payment.paid_on.desc()).limit(limit).all()


@router.post("/payments", response_model=PaymentOut, status_code=201)
def record_payment(
    payload: PaymentCreate, db: Session = Depends(get_db), _: User = Depends(require_staff)
):
    inv = db.get(Invoice, payload.invoice_id)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    if inv.status == InvoiceStatus.void:
        raise HTTPException(409, "Cannot pay a voided invoice")
    if payload.amount - inv.balance > 0.005:
        raise HTTPException(422, f"Payment exceeds outstanding balance of {inv.balance:.2f}")

    payment = Payment(**payload.model_dump())
    db.add(payment)
    db.flush()
    db.refresh(inv)
    refresh_invoice_status(inv)
    db.commit()
    db.refresh(payment)
    return payment


@router.delete("/payments/{payment_id}", status_code=204)
def delete_payment(payment_id: int, db: Session = Depends(get_db), _: User = Depends(require_manager)):
    payment = db.get(Payment, payment_id)
    if not payment:
        raise HTTPException(404, "Payment not found")
    invoice = payment.invoice
    db.delete(payment)
    db.flush()
    db.refresh(invoice)
    refresh_invoice_status(invoice)
    db.commit()


# ------------------------------- arrears ---------------------------------- #
@router.get("/arrears", response_model=list[ArrearsRow])
def arrears(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Aged debt report - the single most useful collections screen."""
    today = date.today()
    rows: dict[int, ArrearsRow] = {}
    invoices = (
        db.query(Invoice)
        .options(joinedload(Invoice.person), joinedload(Invoice.payments))
        .filter(Invoice.status != InvoiceStatus.void)
        .all()
    )
    for inv in invoices:
        bal = inv.balance
        if bal <= 0.005:
            continue
        person = inv.person
        row = rows.setdefault(
            inv.person_id,
            ArrearsRow(
                person_id=inv.person_id,
                person_name=person.full_name if person else f"#{inv.person_id}",
                email=person.email if person else None,
                phone=person.phone if person else None,
            ),
        )
        age = (today - inv.due_date).days
        if age <= 0:
            row.current += bal
        elif age <= 30:
            row.d1_30 += bal
        elif age <= 60:
            row.d31_60 += bal
        elif age <= 90:
            row.d61_90 += bal
        else:
            row.d90_plus += bal
        row.total += bal

    result = sorted(rows.values(), key=lambda r: r.total, reverse=True)
    for r in result:
        for f in ("current", "d1_30", "d31_60", "d61_90", "d90_plus", "total"):
            setattr(r, f, round(getattr(r, f), 2))
    return result
