"""Seed a realistic demo portfolio: one apartment block, one hostel, 14 months of history.

Run with:  python -m backend.seed  [--reset]
"""
from __future__ import annotations

import random
import sys
from datetime import date, timedelta

from sqlalchemy.orm import Session

from .database import Base, SessionLocal, engine, init_db
from .models import (
    Bed,
    Booking,
    BookingStatus,
    Channel,
    ChargeType,
    Expense,
    ExpenseCategory,
    HousekeepingStatus,
    Invoice,
    InvoiceStatus,
    Lease,
    LeaseStatus,
    MaintenanceTicket,
    Payment,
    PaymentMethod,
    Person,
    PersonType,
    Priority,
    Property,
    PropertyType,
    Role,
    TicketStatus,
    Unit,
    UnitStatus,
    UnitType,
    User,
)
from .security import hash_password
from .services import next_invoice_number, refresh_invoice_status

random.seed(20260815)

FIRST = ["Amara", "Ben", "Chloe", "Dmitri", "Elena", "Farid", "Grace", "Hugo", "Ines", "Jonas",
         "Keira", "Luca", "Maya", "Niall", "Olga", "Priya", "Quentin", "Rosa", "Sven", "Tara",
         "Ugo", "Vera", "Wren", "Xavi", "Yuki", "Zane", "Aisha", "Bruno", "Cara", "Dante"]
LAST = ["Okafor", "Whitfield", "Moreau", "Petrov", "Vasquez", "Haddad", "Lindqvist", "Baumann",
        "Rossi", "Nakamura", "Kowalski", "Silva", "Ahmed", "Novak", "Fernandez", "Dubois",
        "Muller", "Ivanova", "Tanaka", "Bergstrom"]
NATIONS = ["UK", "Germany", "Spain", "France", "Italy", "Poland", "Brazil", "Japan",
           "Australia", "Canada", "Nigeria", "India", "Sweden", "Netherlands", "USA"]


def _name(used: set[str]) -> str:
    while True:
        n = f"{random.choice(FIRST)} {random.choice(LAST)}"
        if n not in used:
            used.add(n)
            return n


def _email(name: str, i: int) -> str:
    a, b = name.lower().split(" ")
    return f"{a}.{b}{i}@example.com"


def reset() -> None:
    Base.metadata.drop_all(bind=engine)
    init_db()


def seed(db: Session) -> None:  # noqa: PLR0915 - a seed script is meant to be linear
    today = date.today()
    used_names: set[str] = set()

    # ---------------------------------------------------------------- users --
    users = [
        ("admin@havenpms.co.uk", "Alex Rivera", Role.admin, "admin1234"),
        ("manager@havenpms.co.uk", "Morgan Lee", Role.manager, "manager1234"),
        ("frontdesk@havenpms.co.uk", "Sam Patel", Role.staff, "frontdesk1234"),
        ("owner@havenpms.co.uk", "Jordan Blake", Role.viewer, "viewer1234"),
    ]
    for email, full_name, role, pw in users:
        db.add(User(email=email, full_name=full_name, role=role, hashed_password=hash_password(pw)))

    # ----------------------------------------------------------- properties --
    riverside = Property(
        name="Riverside Court", code="RSC", type=PropertyType.apartment,
        address_line1="14 Riverside Walk", city="Manchester", postcode="M1 4TR",
        country="United Kingdom", currency="GBP", purchase_price=2_450_000,
        notes="24 unit block, 2018 build, communal roof terrace.",
    )
    nomad = Property(
        name="Nomad House Hostel", code="NMH", type=PropertyType.hostel,
        address_line1="8 Canal Street", city="Manchester", postcode="M1 6JB",
        country="United Kingdom", currency="GBP", purchase_price=1_150_000,
        notes="72 beds across dorms and private rooms, bar and cafe on site.",
    )
    oakfield = Property(
        name="Oakfield Mews", code="OKM", type=PropertyType.mixed,
        address_line1="3 Oakfield Mews", city="Leeds", postcode="LS2 9DF",
        country="United Kingdom", currency="GBP", purchase_price=890_000,
        notes="Converted townhouse: 6 flats upstairs, 3 short-let rooms on the ground floor.",
    )
    db.add_all([riverside, nomad, oakfield])
    db.flush()

    # ---------------------------------------------------------------- units --
    long_units: list[Unit] = []
    for floor in range(1, 5):
        for n in range(1, 7):
            beds_n = random.choice([1, 1, 2, 2, 3])
            rent = {1: 875, 2: 1150, 3: 1450}[beds_n] + random.choice([-50, 0, 0, 25, 50])
            u = Unit(
                property_id=riverside.id, name=f"{floor}{n:02d}",
                type=UnitType.studio if beds_n == 1 else UnitType.apartment,
                floor=floor, bedrooms=beds_n, bathrooms=1.0 if beds_n < 3 else 2.0,
                size_sqm=32 + beds_n * 16, capacity=beds_n + 1, market_rent=rent,
                amenities="wifi,dishwasher,lift,bike store",
            )
            db.add(u)
            long_units.append(u)

    for n in range(1, 7):
        u = Unit(
            property_id=oakfield.id, name=f"Flat {n}", type=UnitType.apartment,
            floor=(n + 1) // 2, bedrooms=2, bathrooms=1.0, size_sqm=58, capacity=3,
            market_rent=795 + random.choice([0, 25, 50]), amenities="wifi,garden access",
        )
        db.add(u)
        long_units.append(u)

    short_units: list[Unit] = []
    dorm_specs = [("Dorm A", 8, 24), ("Dorm B", 8, 24), ("Dorm C", 10, 21),
                  ("Dorm D", 6, 27), ("Dorm E (female)", 6, 29)]
    for name, size, rate in dorm_specs:
        u = Unit(
            property_id=nomad.id, name=name, type=UnitType.dorm, floor=random.choice([1, 2]),
            bedrooms=1, bathrooms=1.0, capacity=size, nightly_rate=rate,
            amenities="wifi,lockers,reading light,usb",
        )
        db.add(u)
        db.flush()
        for i in range(1, size + 1):
            db.add(Bed(unit_id=u.id, label=f"{name.split()[1]}{i:02d}", nightly_rate=rate))
        short_units.append(u)

    for n in range(1, 9):
        u = Unit(
            property_id=nomad.id, name=f"Private {n}", type=UnitType.private_room, floor=3,
            bedrooms=1, bathrooms=1.0, capacity=2, nightly_rate=62 + (n % 3) * 8,
            amenities="wifi,ensuite,desk",
        )
        db.add(u)
        short_units.append(u)

    for n in range(1, 4):
        u = Unit(
            property_id=oakfield.id, name=f"Room G{n}", type=UnitType.private_room, floor=0,
            bedrooms=1, bathrooms=1.0, capacity=2, nightly_rate=58, amenities="wifi,ensuite",
        )
        db.add(u)
        short_units.append(u)

    db.flush()

    # -------------------------------------------------------- tenants/leases --
    tenants: list[Person] = []
    for i in range(len(long_units)):
        n = _name(used_names)
        p = Person(
            type=PersonType.tenant, full_name=n, email=_email(n, i), phone=f"+4477{random.randint(10**7, 10**8-1)}",
            nationality=random.choice(NATIONS), screening_status=random.choice(["passed", "passed", "passed", "conditional"]),
        )
        db.add(p)
        tenants.append(p)
    db.flush()

    leases: list[Lease] = []
    for unit, tenant in zip(long_units, tenants):
        if random.random() < 0.11:          # leave ~11% void
            continue
        term = random.choice([12, 12, 12, 18, 24])
        # Start far enough back to build history, but keep most tenancies live today.
        months_ago = random.randint(1, term - 1)
        start = (today.replace(day=1) - timedelta(days=months_ago * 30)).replace(day=1)
        end = date(start.year + (start.month - 1 + term) // 12, (start.month - 1 + term) % 12 + 1, 1) - timedelta(days=1)
        market = float(unit.market_rent)
        # Some tenancies drift below market - the analytics engine flags these.
        rent = round(market * random.choice([1.0, 1.0, 0.97, 0.90, 0.88, 1.02]), 0)
        status = LeaseStatus.active
        if end < today:
            status = LeaseStatus.ended
        lease = Lease(
            unit_id=unit.id, person_id=tenant.id, start_date=start, end_date=end,
            rent_amount=rent, billing_day=random.choice([1, 1, 5, 15]),
            deposit_amount=round(rent * 1.15, 2), status=status,
            deposit_scheme_ref=f"TDS-{random.randint(100000, 999999)}",
        )
        db.add(lease)
        leases.append(lease)
        unit.status = UnitStatus.occupied if status == LeaseStatus.active else UnitStatus.available
    db.flush()

    # ------------------------------------------------------- rent invoices ---
    def month_iter(start: date, end: date):
        y, m = start.year, start.month
        while (y, m) <= (end.year, end.month):
            yield y, m
            m += 1
            if m == 13:
                m, y = 1, y + 1

    inv_seq = 0
    for lease in leases:
        first = max(lease.start_date, today - timedelta(days=430)).replace(day=1)
        last = min(lease.end_date or today, today)
        for y, m in month_iter(first, last):
            import calendar

            due_day = min(lease.billing_day, calendar.monthrange(y, m)[1])
            issue = date(y, m, 1)
            inv_seq += 1
            inv = Invoice(
                number=f"INV-{y}{m:02d}-{inv_seq:04d}",
                person_id=lease.person_id, property_id=lease.unit.property_id, lease_id=lease.id,
                charge_type=ChargeType.rent,
                description=f"Rent {issue:%b %Y} - {lease.unit.name}",
                issue_date=issue, due_date=date(y, m, due_day),
                period_start=issue, period_end=date(y, m, calendar.monthrange(y, m)[1]),
                amount=float(lease.rent_amount),
            )
            db.add(inv)
            db.flush()

            # Payment behaviour: mostly on time, some late, a few in arrears.
            roll = random.random()
            if roll < 0.80:
                paid_on = inv.due_date + timedelta(days=random.randint(-3, 2))
                amt = inv.total
            elif roll < 0.92:
                paid_on = inv.due_date + timedelta(days=random.randint(5, 25))
                amt = inv.total
            elif roll < 0.96:
                paid_on = inv.due_date + timedelta(days=random.randint(2, 10))
                amt = round(inv.total * 0.5, 2)
            else:
                amt = 0
                paid_on = None
            if amt > 0 and paid_on and paid_on <= today:
                db.add(Payment(invoice_id=inv.id, amount=amt, paid_on=paid_on,
                               method=random.choice(list(PaymentMethod)),
                               reference=f"SO-{random.randint(1000,9999)}"))
            db.flush()
            db.refresh(inv)
            refresh_invoice_status(inv, today)

    # ------------------------------------------------------------ bookings ---
    guests: list[Person] = []
    for i in range(220):
        n = _name(used_names) if random.random() < 0.7 else f"{random.choice(FIRST)} {random.choice(LAST)}"
        p = Person(type=PersonType.guest, full_name=n, email=_email(n, 1000 + i),
                   phone=f"+4477{random.randint(10**7, 10**8-1)}", nationality=random.choice(NATIONS),
                   id_document=f"P{random.randint(10**7, 10**8-1)}")
        db.add(p)
        guests.append(p)
    db.flush()

    all_beds = {u.id: db.query(Bed).filter(Bed.unit_id == u.id).all() for u in short_units}
    channel_weights = [
        (Channel.direct, 0.20, 0.0), (Channel.website, 0.14, 0.0), (Channel.walk_in, 0.08, 0.0),
        (Channel.hostelworld, 0.24, 0.15), (Channel.booking_com, 0.26, 0.17), (Channel.airbnb, 0.08, 0.14),
    ]
    ch_list = [c for c, _, _ in channel_weights]
    ch_probs = [w for _, w, _ in channel_weights]
    ch_comm = {c: k for c, _, k in channel_weights}

    occupied: dict[tuple[int, int], set[date]] = {}  # (unit_id, bed_id) -> nights taken
    ref_seq = {"n": 0}

    # Seasonality: share of nights sold, by calendar month.
    SEASON = {1: 0.52, 2: 0.58, 3: 0.66, 4: 0.72, 5: 0.78, 6: 0.86,
              7: 0.92, 8: 0.93, 9: 0.80, 10: 0.70, 11: 0.60, 12: 0.75}

    def make_booking(unit: Unit, bed: Bed | None, guest: Person, ci: date, nights: int) -> Booking:
        co = ci + timedelta(days=nights)
        channel = random.choices(ch_list, weights=ch_probs, k=1)[0]
        base = float((bed.nightly_rate if bed and bed.nightly_rate else unit.nightly_rate) or 30)
        rate = base * SEASON[ci.month] / 0.75          # price follows demand
        if ci.weekday() >= 4:
            rate *= 1.18
        rate = round(rate * random.uniform(0.94, 1.08), 2)

        if co < today:                       # stay finished before today
            status = random.choices(
                [BookingStatus.checked_out, BookingStatus.cancelled, BookingStatus.no_show],
                weights=[0.92, 0.06, 0.02], k=1)[0]
        elif ci < today <= co:               # in house — including guests leaving today
            status = BookingStatus.checked_in
        elif ci == today:                    # arriving today: some already at the desk, some not
            status = random.choices([BookingStatus.confirmed, BookingStatus.checked_in, BookingStatus.pending],
                                    weights=[0.55, 0.35, 0.10], k=1)[0]
        else:                                # future
            status = random.choices([BookingStatus.confirmed, BookingStatus.pending],
                                    weights=[0.88, 0.12], k=1)[0]

        ref_seq["n"] += 1
        bk = Booking(
            reference=f"BK-{ref_seq['n']:06d}",
            unit_id=unit.id, bed_id=bed.id if bed else None, person_id=guest.id,
            check_in=ci, check_out=co, guests=1 if bed else random.choice([1, 2]),
            nightly_rate=rate, total_amount=round(rate * nights, 2),
            channel=channel, commission_rate=ch_comm[channel], status=status,
        )
        db.add(bk)
        return bk

    # Walk each sellable slot's calendar forward so occupancy is realistic
    # rather than randomly scattered: stay, short gap, stay, longer gap...
    slots: list[tuple[Unit, Bed | None]] = []
    for u in short_units:
        beds = all_beds.get(u.id) or []
        slots.extend((u, b) for b in beds) if beds else slots.append((u, None))

    start_window = today - timedelta(days=400)
    horizon = today + timedelta(days=75)
    made = 0
    for unit, bed in slots:
        cursor = start_window + timedelta(days=random.randint(0, 6))
        while cursor < horizon:
            target = SEASON[cursor.month]
            if random.random() > target:                     # slot sits empty
                cursor += timedelta(days=random.randint(1, 4))
                continue
            nights = random.choices([1, 2, 3, 4, 5, 7, 10, 14],
                                    weights=[16, 26, 21, 12, 8, 10, 4, 3], k=1)[0]
            nights = min(nights, (horizon - cursor).days)
            if nights < 1:
                break
            make_booking(unit, bed, random.choice(guests), cursor, nights)
            made += 1
            cursor += timedelta(days=nights + random.choices([0, 0, 1, 2, 3], weights=[42, 22, 18, 11, 7], k=1)[0])
    db.flush()

    # Accommodation invoices are raised close to arrival, not months ahead.
    for bk in db.query(Booking).filter(
        Booking.status != BookingStatus.cancelled,
        Booking.check_in <= today + timedelta(days=7),
    ).all():
        inv_seq += 1
        inv = Invoice(
            number=f"INV-{bk.check_in:%Y%m}-{inv_seq:04d}",
            person_id=bk.person_id, property_id=bk.unit.property_id, booking_id=bk.id,
            charge_type=ChargeType.accommodation,
            description=f"{bk.nights} night(s) - {bk.unit.name} ({bk.reference})",
            issue_date=bk.check_in, due_date=bk.check_in,
            period_start=bk.check_in, period_end=bk.check_out,
            amount=float(bk.total_amount),
        )
        db.add(inv)
        db.flush()
        # Short stays are settled at arrival; a small tail goes unpaid.
        if bk.check_in <= today and random.random() < 0.985:
            db.add(Payment(invoice_id=inv.id, amount=inv.total,
                           paid_on=min(bk.check_in, today),
                           method=random.choice([PaymentMethod.card, PaymentMethod.online, PaymentMethod.cash])))
        db.flush()
        db.refresh(inv)
        refresh_invoice_status(inv, today)

    # --------------------------------------------------------- maintenance ---
    issues = [
        ("Boiler not firing", "heating", Priority.urgent), ("Dripping kitchen tap", "plumbing", Priority.low),
        ("Broken window latch", "windows", Priority.medium), ("Shower pressure low", "plumbing", Priority.medium),
        ("Smoke alarm chirping", "safety", Priority.high), ("Bed frame squeaking", "furniture", Priority.low),
        ("Wifi dropping in Dorm B", "internet", Priority.high), ("Lift out of service", "lift", Priority.urgent),
        ("Damp patch on ceiling", "damp", Priority.high), ("Front door fob not working", "access", Priority.medium),
        ("Fridge not cooling", "appliance", Priority.high), ("Blocked shower drain", "plumbing", Priority.medium),
    ]
    all_units = long_units + short_units
    for i in range(48):
        title, cat, prio = random.choice(issues)
        reported = today - timedelta(days=random.randint(0, 200))
        unit = random.choice(all_units)
        resolved = None
        status = random.choices(
            [TicketStatus.closed, TicketStatus.resolved, TicketStatus.in_progress, TicketStatus.open, TicketStatus.on_hold],
            weights=[0.45, 0.2, 0.14, 0.16, 0.05], k=1)[0]
        if status in (TicketStatus.closed, TicketStatus.resolved):
            resolved = min(reported + timedelta(days=random.randint(1, 21)), today)
        db.add(MaintenanceTicket(
            property_id=unit.property_id, unit_id=unit.id, title=title, category=cat,
            description=f"Reported by occupant of {unit.name}.", priority=prio, status=status,
            assignee=random.choice(["Dave (handyman)", "AquaFlow Plumbing", "In-house", "Northern Electrics"]),
            cost=round(random.uniform(0, 480), 2) if resolved else 0,
            reported_at=reported, resolved_at=resolved,
        ))

    # ------------------------------------------------------------ expenses ---
    for prop in (riverside, nomad, oakfield):
        for months_ago in range(14):
            d = (today.replace(day=1) - timedelta(days=months_ago * 30)).replace(day=random.randint(1, 27))
            base = {"RSC": 3200, "NMH": 5400, "OKM": 1400}[prop.code]
            for cat, share in [
                (ExpenseCategory.utilities, 0.22), (ExpenseCategory.cleaning, 0.18),
                (ExpenseCategory.repairs, 0.14), (ExpenseCategory.insurance, 0.08),
                (ExpenseCategory.salaries, 0.24), (ExpenseCategory.marketing, 0.06),
                (ExpenseCategory.supplies, 0.08),
            ]:
                db.add(Expense(
                    property_id=prop.id, category=cat,
                    vendor=cat.value.title() + " Co", description=f"{cat.value} {d:%b %Y}",
                    amount=round(base * share * random.uniform(0.85, 1.15), 2), spent_on=d,
                ))

    # a few units deliberately off-market so the advisor has something to say
    for u in random.sample([u for u in long_units if u.status == UnitStatus.available], 2):
        u.housekeeping = HousekeepingStatus.dirty

    db.commit()
    print(f"Seeded: 3 properties, {len(all_units)} units, {len(leases)} leases, {made} bookings.")


def main() -> None:
    if "--reset" in sys.argv:
        reset()
    else:
        init_db()
    db = SessionLocal()
    try:
        if db.query(User).count() and "--reset" not in sys.argv:
            print("Database already seeded. Re-run with --reset to rebuild.")
            return
        seed(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
