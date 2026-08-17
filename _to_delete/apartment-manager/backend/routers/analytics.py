"""Analytics: the layer that turns operational data into revenue decisions."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..config import settings
from ..database import get_db
from ..deps import get_current_user
from ..models import (
    Booking,
    BookingStatus,
    Expense,
    Invoice,
    InvoiceStatus,
    Lease,
    LeaseStatus,
    MaintenanceTicket,
    Payment,
    Priority,
    Property,
    TicketStatus,
    Unit,
    UnitStatus,
    UnitType,
    User,
)
from ..schemas import (
    KpiSummary,
    NamedValue,
    PropertyPerformance,
    Recommendation,
    TrendPoint,
)
from ..services import bookings_on, leases_active_on, month_bounds, occupancy_on

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _months_back(n: int, end: date | None = None) -> list[tuple[int, int]]:
    end = end or date.today()
    out = []
    y, m = end.year, end.month
    for _ in range(n):
        out.append((y, m))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return list(reversed(out))


# --------------------------------------------------------------------------- #
@router.get("/summary", response_model=KpiSummary)
def summary(
    as_of: date | None = None, db: Session = Depends(get_db), _: User = Depends(get_current_user)
):
    today = as_of or date.today()
    m_start, m_end = month_bounds(today.year, today.month)

    props = db.query(Property).all()
    units = db.query(Unit).options(joinedload(Unit.beds)).all()
    total_beds = sum(len(u.beds) for u in units)

    occ = occupancy_on(db, today)
    total_capacity = occ["long_total"] + occ["short_capacity"]
    total_sold = occ["long_occupied"] + occ["short_sold"]

    active_leases = leases_active_on(db, today)
    mrr = sum(float(l.rent_amount) for l in active_leases)

    invoices = db.query(Invoice).options(joinedload(Invoice.payments)).all()
    billed_month = sum(
        i.total for i in invoices
        if i.status != InvoiceStatus.void and m_start <= i.issue_date <= m_end
    )
    collected_month = (
        db.query(func.coalesce(func.sum(Payment.amount), 0))
        .filter(Payment.paid_on >= m_start, Payment.paid_on <= m_end)
        .scalar()
        or 0
    )
    outstanding = sum(i.balance for i in invoices if i.status != InvoiceStatus.void and i.balance > 0)
    overdue_count = sum(
        1 for i in invoices
        if i.status != InvoiceStatus.void and i.balance > 0.005 and i.due_date < today
    )

    # ADR / RevPAR over the trailing 30 nights of short-stay trading.
    window_start = today - timedelta(days=30)
    stays = (
        db.query(Booking)
        .filter(
            Booking.status.in_(
                [BookingStatus.confirmed, BookingStatus.checked_in, BookingStatus.checked_out]
            ),
            Booking.check_out > window_start,
            Booking.check_in <= today,
        )
        .all()
    )
    room_nights, room_revenue = 0, 0.0
    for b in stays:
        start = max(b.check_in, window_start)
        end = min(b.check_out, today)
        n = max((end - start).days, 0)
        room_nights += n
        room_revenue += n * float(b.nightly_rate)
    adr = round(room_revenue / room_nights, 2) if room_nights else 0.0
    available_bed_nights = occ["short_capacity"] * 30
    revpar = round(room_revenue / available_bed_nights, 2) if available_bed_nights else 0.0

    open_tickets = (
        db.query(func.count(MaintenanceTicket.id))
        .filter(
            MaintenanceTicket.status.in_(
                [TicketStatus.open, TicketStatus.in_progress, TicketStatus.on_hold]
            )
        )
        .scalar()
        or 0
    )
    urgent_tickets = (
        db.query(func.count(MaintenanceTicket.id))
        .filter(
            MaintenanceTicket.priority == Priority.urgent,
            MaintenanceTicket.status.in_([TicketStatus.open, TicketStatus.in_progress]),
        )
        .scalar()
        or 0
    )

    expenses_month = (
        db.query(func.coalesce(func.sum(Expense.amount), 0))
        .filter(Expense.spent_on >= m_start, Expense.spent_on <= m_end)
        .scalar()
        or 0
    )

    horizon = today + timedelta(days=60)
    expiring = sum(
        1 for l in active_leases if l.end_date and today <= l.end_date <= horizon
    )

    arrivals = (
        db.query(func.count(Booking.id))
        .filter(Booking.check_in == today, Booking.status != BookingStatus.cancelled)
        .scalar()
        or 0
    )
    departures = (
        db.query(func.count(Booking.id))
        .filter(Booking.check_out == today, Booking.status != BookingStatus.cancelled)
        .scalar()
        or 0
    )

    return KpiSummary(
        as_of=today,
        currency=settings.DEFAULT_CURRENCY,
        total_properties=len(props),
        total_units=len(units),
        total_beds=total_beds,
        occupied_units=total_sold,
        occupancy_rate=round(total_sold / total_capacity * 100, 1) if total_capacity else 0.0,
        long_stay_occupancy=occ["long_rate"],
        short_stay_occupancy=occ["short_rate"],
        monthly_recurring_revenue=round(mrr, 2),
        billed_this_month=round(float(billed_month), 2),
        collected_this_month=round(float(collected_month), 2),
        collection_rate=round(float(collected_month) / float(billed_month) * 100, 1)
        if billed_month
        else 0.0,
        outstanding_balance=round(outstanding, 2),
        overdue_invoices=overdue_count,
        adr=adr,
        revpar=revpar,
        open_tickets=open_tickets,
        urgent_tickets=urgent_tickets,
        expenses_this_month=round(float(expenses_month), 2),
        net_operating_income=round(float(collected_month) - float(expenses_month), 2),
        active_leases=len(active_leases),
        leases_expiring_60d=expiring,
        arrivals_today=arrivals,
        departures_today=departures,
    )


@router.get("/trend", response_model=list[TrendPoint])
def trend(
    months: int = Query(12, ge=1, le=36),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    periods = _months_back(months)
    invoices = db.query(Invoice).filter(Invoice.status != InvoiceStatus.void).all()
    payments = db.query(Payment).all()
    expenses = db.query(Expense).all()

    billed: dict[str, float] = defaultdict(float)
    for i in invoices:
        billed[f"{i.issue_date:%Y-%m}"] += i.total
    paid: dict[str, float] = defaultdict(float)
    for p in payments:
        paid[f"{p.paid_on:%Y-%m}"] += float(p.amount)
    spent: dict[str, float] = defaultdict(float)
    for e in expenses:
        spent[f"{e.spent_on:%Y-%m}"] += float(e.amount)

    out: list[TrendPoint] = []
    for y, m in periods:
        key = f"{y:04d}-{m:02d}"
        start, end = month_bounds(y, m)
        sample = min(end, date.today())
        occ = occupancy_on(db, sample) if sample >= start else {"long_rate": 0, "short_rate": 0,
                                                                "long_total": 0, "short_capacity": 0,
                                                                "long_occupied": 0, "short_sold": 0}
        cap = occ["long_total"] + occ["short_capacity"]
        sold = occ["long_occupied"] + occ["short_sold"]
        out.append(
            TrendPoint(
                period=key,
                revenue=round(billed.get(key, 0.0), 2),
                collected=round(paid.get(key, 0.0), 2),
                expenses=round(spent.get(key, 0.0), 2),
                occupancy=round(sold / cap * 100, 1) if cap else 0.0,
            )
        )
    return out


@router.get("/channel-mix", response_model=list[NamedValue])
def channel_mix(
    months: int = 6, db: Session = Depends(get_db), _: User = Depends(get_current_user)
):
    """Revenue and commission cost by booking channel - drives direct-booking strategy."""
    since = date.today() - timedelta(days=30 * months)
    rows = (
        db.query(Booking)
        .filter(
            Booking.check_in >= since,
            Booking.status != BookingStatus.cancelled,
        )
        .all()
    )
    revenue: dict[str, float] = defaultdict(float)
    commission: dict[str, float] = defaultdict(float)
    for b in rows:
        revenue[b.channel.value] += float(b.total_amount)
        commission[b.channel.value] += float(b.total_amount) * float(b.commission_rate or 0)
    return [
        NamedValue(label=k, value=round(v, 2), secondary=round(commission[k], 2))
        for k, v in sorted(revenue.items(), key=lambda kv: kv[1], reverse=True)
    ]


@router.get("/property-performance", response_model=list[PropertyPerformance])
def property_performance(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    today = date.today()
    ytd_start = date(today.year, 1, 1)
    result: list[PropertyPerformance] = []

    for prop in db.query(Property).order_by(Property.name).all():
        units = db.query(Unit).options(joinedload(Unit.beds)).filter(Unit.property_id == prop.id).all()
        unit_ids = [u.id for u in units]

        capacity, sold = 0, 0
        for u in units:
            if u.type in (UnitType.apartment, UnitType.studio):
                capacity += 1
            else:
                capacity += len(u.beds) if u.beds else max(u.capacity, 1)
        sold += len({l.unit_id for l in leases_active_on(db, today) if l.unit_id in unit_ids})
        for b in bookings_on(db, today):
            if b.unit_id in unit_ids:
                sold += 1 if b.bed_id else (len(b.unit.beds) if b.unit and b.unit.beds else 1)

        invoices = (
            db.query(Invoice)
            .options(joinedload(Invoice.payments))
            .filter(
                Invoice.property_id == prop.id,
                Invoice.status != InvoiceStatus.void,
                Invoice.issue_date >= ytd_start,
            )
            .all()
        )
        revenue = sum(i.total for i in invoices)
        collected = sum(i.paid for i in invoices)
        arrears = sum(i.balance for i in invoices if i.balance > 0)

        expenses = (
            db.query(func.coalesce(func.sum(Expense.amount), 0))
            .filter(Expense.property_id == prop.id, Expense.spent_on >= ytd_start)
            .scalar()
            or 0
        )

        rents = [float(l.rent_amount) for l in leases_active_on(db, today) if l.unit_id in unit_ids]

        result.append(
            PropertyPerformance(
                property_id=prop.id,
                property_name=prop.name,
                type=prop.type,
                units=len(units),
                occupancy_rate=round(min(sold, capacity) / capacity * 100, 1) if capacity else 0.0,
                revenue_ytd=round(revenue, 2),
                collected_ytd=round(collected, 2),
                expenses_ytd=round(float(expenses), 2),
                noi_ytd=round(collected - float(expenses), 2),
                arrears=round(arrears, 2),
                avg_rent=round(sum(rents) / len(rents), 2) if rents else 0.0,
            )
        )
    return result


@router.get("/unit-yield", response_model=list[NamedValue])
def unit_yield(
    limit: int = 15, db: Session = Depends(get_db), _: User = Depends(get_current_user)
):
    """Revenue per unit over the last 12 months - finds the under-performers."""
    since = date.today() - timedelta(days=365)
    per_unit: dict[int, float] = defaultdict(float)

    for lease in db.query(Lease).all():
        invs = (
            db.query(Invoice)
            .options(joinedload(Invoice.payments))
            .filter(Invoice.lease_id == lease.id, Invoice.issue_date >= since,
                    Invoice.status != InvoiceStatus.void)
            .all()
        )
        per_unit[lease.unit_id] += sum(i.total for i in invs)

    for b in db.query(Booking).filter(
        Booking.check_in >= since, Booking.status != BookingStatus.cancelled
    ).all():
        per_unit[b.unit_id] += float(b.total_amount)

    units = {u.id: u for u in db.query(Unit).options(joinedload(Unit.property)).all()}
    rows = [
        NamedValue(
            label=f"{units[uid].property.name} · {units[uid].name}" if uid in units else f"#{uid}",
            value=round(v, 2),
            secondary=float(units[uid].market_rent or 0) * 12 if uid in units else 0,
        )
        for uid, v in per_unit.items()
        if uid in units
    ]
    return sorted(rows, key=lambda r: r.value, reverse=True)[:limit]


@router.get("/recommendations", response_model=list[Recommendation])
def recommendations(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Rule-based advisor: where the money is leaking and what to do about it."""
    today = date.today()
    recs: list[Recommendation] = []
    sym = {"GBP": "\u00a3", "USD": "$", "EUR": "\u20ac", "THB": "\u0e3f"}.get(settings.DEFAULT_CURRENCY, "")

    # 1. Vacant long-stay units
    long_units = db.query(Unit).filter(Unit.type.in_([UnitType.apartment, UnitType.studio])).all()
    let_unit_ids = {l.unit_id for l in leases_active_on(db, today)}
    vacant = [
        u for u in long_units
        if u.id not in let_unit_ids and u.status not in (UnitStatus.offline, UnitStatus.maintenance)
    ]
    if vacant:
        lost = sum(float(u.market_rent or 0) for u in vacant)
        recs.append(
            Recommendation(
                severity="critical" if len(vacant) > len(long_units) * 0.15 else "warning",
                area="occupancy",
                title=f"{len(vacant)} residential unit(s) sitting empty",
                detail="Void units: " + ", ".join(f"{u.property.name} {u.name}" for u in vacant[:8])
                + ". Re-list them and consider a short-let fallback to bridge the void period.",
                impact_estimate=round(lost, 2),
            )
        )

    # 2. Rents below market
    below = []
    for lease in leases_active_on(db, today):
        market = float(lease.unit.market_rent or 0)
        if market and float(lease.rent_amount) < market * 0.93:
            below.append((lease, market - float(lease.rent_amount)))
    if below:
        uplift = sum(gap for _, gap in below)
        recs.append(
            Recommendation(
                severity="warning",
                area="pricing",
                title=f"{len(below)} tenancy(ies) priced under market",
                detail="Schedule a rent review at renewal for: "
                + ", ".join(f"{l.unit.name} (+{sym}{gap:.0f}/mo)" for l, gap in sorted(below, key=lambda x: -x[1])[:6]),
                impact_estimate=round(uplift * 12, 2),
            )
        )

    # 3. Arrears
    overdue = [
        i for i in db.query(Invoice).options(joinedload(Invoice.payments)).all()
        if i.status != InvoiceStatus.void and i.balance > 0.005 and i.due_date < today
    ]
    if overdue:
        total = sum(i.balance for i in overdue)
        worst = sorted(overdue, key=lambda i: i.due_date)[0]
        recs.append(
            Recommendation(
                severity="critical" if total > 5000 else "warning",
                area="collections",
                title=f"{len(overdue)} overdue invoice(s) worth {sym}{total:,.0f}",
                detail=f"Oldest is {worst.number} due {worst.due_date}. Chase in date order and "
                "turn on automatic reminders at 3, 7 and 14 days past due.",
                impact_estimate=round(total, 2),
            )
        )

    # 4. OTA commission leakage
    since = today - timedelta(days=180)
    ota_rev, ota_comm, direct_rev = 0.0, 0.0, 0.0
    for b in db.query(Booking).filter(
        Booking.check_in >= since, Booking.status != BookingStatus.cancelled
    ).all():
        if float(b.commission_rate or 0) > 0:
            ota_rev += float(b.total_amount)
            ota_comm += float(b.total_amount) * float(b.commission_rate)
        else:
            direct_rev += float(b.total_amount)
    if ota_comm > 0 and ota_rev + direct_rev > 0:
        share = ota_rev / (ota_rev + direct_rev) * 100
        if share > 40:
            recs.append(
                Recommendation(
                    severity="warning",
                    area="channel",
                    title=f"{share:.0f}% of short-stay revenue comes through OTAs",
                    detail=f"You paid roughly {sym}{ota_comm:,.0f} in commission over 6 months. "
                    "Shifting 20% of that volume to direct booking pays for a booking engine many times over.",
                    impact_estimate=round(ota_comm * 0.2, 2),
                )
            )

    # 5. Ageing maintenance
    stale = (
        db.query(MaintenanceTicket)
        .filter(
            MaintenanceTicket.status.in_([TicketStatus.open, TicketStatus.in_progress]),
            MaintenanceTicket.reported_at <= today - timedelta(days=14),
        )
        .all()
    )
    if stale:
        recs.append(
            Recommendation(
                severity="warning",
                area="maintenance",
                title=f"{len(stale)} ticket(s) open longer than 14 days",
                detail="Slow repairs drive churn and bad reviews. Oldest: "
                + ", ".join(f"{t.title} ({(today - t.reported_at).days}d)" for t in stale[:5]),
                impact_estimate=0,
            )
        )

    # 6. Renewals coming up
    horizon = today + timedelta(days=60)
    expiring = [l for l in leases_active_on(db, today) if l.end_date and today <= l.end_date <= horizon]
    if expiring:
        recs.append(
            Recommendation(
                severity="info",
                area="occupancy",
                title=f"{len(expiring)} tenancy(ies) expire within 60 days",
                detail="Open renewal conversations now - re-letting costs far more than a small rent concession. "
                + ", ".join(f"{l.unit.name} ({l.end_date})" for l in expiring[:6]),
                impact_estimate=round(sum(float(l.rent_amount) for l in expiring), 2),
            )
        )

    order = {"critical": 0, "warning": 1, "info": 2}
    return sorted(recs, key=lambda r: (order[r.severity], -r.impact_estimate))
