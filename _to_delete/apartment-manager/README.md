# Haven PMS — apartment & hostel management

A working draft of a property management system that covers **both** businesses in one
data model: long-stay residential lettings (apartments → leases → recurring monthly rent)
and short-stay hostel trading (dorms → beds → nightly bookings). Both revenue streams
settle into a single invoice/payment ledger, which is what makes portfolio-wide analytics
possible.

Feature scope was drafted from the common core of established products in both categories —
residential tools (Buildium, AppFolio, Landlord Studio, Hemlane, RentRedi, DoorLoop, TenantCloud)
and hostel PMS platforms (Cloudbeds, Mews, SabeeApp, RoomRaccoon, WebRezPro, Little Hotelier) —
then reduced to what actually earns its place in a v1.

## Quick start

```bash
./run.sh                      # installs deps, seeds demo data, serves on :8000
```

Or manually:

```bash
pip install -r requirements.txt
python -m backend.seed --reset      # 3 properties, 46 units, 28 leases, ~4,600 bookings, 14 months of history
uvicorn backend.main:app --reload
```

Open <http://127.0.0.1:8000> — API docs live at `/api/docs`.

| Demo account | Password | Sees |
|---|---|---|
| `admin@havenpms.co.uk` | `admin1234` | everything, including user management |
| `manager@havenpms.co.uk` | `manager1234` | everything except user management |
| `frontdesk@havenpms.co.uk` | `frontdesk1234` | day-to-day operations, no deletes |
| `owner@havenpms.co.uk` | `viewer1234` | read only |

## Screens

![Dashboard](docs/dashboard.png)

Front desk and analytics screens are in `docs/frontdesk.png` and `docs/analytics.png`.

## What's in the draft

**Inventory** — properties → units → beds. A unit is an apartment, a studio, a private
room or a dorm; dorms carry individual beds, which is the sellable unit for hostels.
Status and housekeeping state per unit.

**People** — one contact record shared by tenants and guests, with screening status,
ID document, nationality and a live outstanding balance.

**Leases** — term, rent, billing day, deposit and deposit-scheme reference. Overlapping
tenancies on one unit are rejected; an active lease flips the unit to occupied.

**Bookings** — bed-level or whole-room reservations with half-open date intervals
(checkout day is the next guest's arrival day), an availability search, channel and
commission tracking, and front-desk check-in/check-out that flags housekeeping.

**Billing** — one ledger for rent and accommodation. Idempotent monthly rent run,
part-payments, automatic open/partial/paid/overdue transitions, and an aged-debt report
bucketed at 30/60/90 days.

**Maintenance** — ticketing with priority, assignee, cost and age. An urgent ticket takes
the unit off sale; resolving it puts it back and flags it for cleaning.

**Expenses** — categorised operating costs per property, which is what turns collected
revenue into a real NOI figure.

**Analytics** — occupancy split long-stay vs short-stay, MRR, collection rate, aged debt,
ADR and RevPAR, channel mix with commission leakage, per-property NOI, per-unit yield,
and a rule-based advisor that names the specific voids, under-market rents, overdue
accounts, OTA dependency, stale repairs and upcoming renewals costing money right now.

## Architecture

```
backend/
  config.py        env-driven settings (SQLite dev → Postgres prod, one variable)
  database.py      engine, session factory, declarative base
  models.py        SQLAlchemy 2.0 ORM — the domain model
  schemas.py       Pydantic request/response contracts
  security.py      PBKDF2-SHA256 password hashing, JWT issue/verify
  deps.py          current-user resolution and role gates
  services.py      business rules: availability, occupancy, invoicing, numbering
  routers/         one module per resource
  seed.py          realistic demo portfolio with 14 months of history
frontend/          single-page console: no build step, no framework
tests/             22 end-to-end API tests
```

**Stack choice.** FastAPI + SQLAlchemy + SQLite/Postgres, with a dependency-free
frontend. The API is fully typed and self-documenting, and the whole thing runs from
one command — which matters more than framework fashion for a draft you want to
evaluate quickly. Swapping SQLite for Postgres is a single environment variable.

**Auth.** JWT bearer tokens, four roles (`admin`, `manager`, `staff`, `viewer`) enforced
by dependency injection per endpoint rather than checked ad hoc inside handlers.

**Frontend.** Vanilla JS with template strings and event delegation. Charts are
hand-rendered SVG — a validated colourblind-safe palette, one y-axis per chart, hover
tooltips, legends and a table view of every chart. Light and dark themes are separately
specified rather than auto-inverted.

## Tests

```bash
python -m pytest tests -q      # 22 passed
```

Coverage focuses on the rules that are expensive to get wrong: double-booking a bed,
back-to-back stays that must *not* clash, overlapping tenancies, idempotent rent runs,
part-payment status transitions, overpayment rejection, arrears bucketing, urgent-ticket
unit blocking, and role enforcement.

## Not in the draft yet

Deliberately out of scope for v1, in rough priority order:

1. **Channel manager sync** (Booking.com / Hostelworld two-way inventory) — the single
   highest-value integration for the hostel side.
2. **Payment gateway** (Stripe / GoCardless) so rent collection and card pre-auth are
   real rather than recorded after the fact.
3. **Tenant and guest portals** — self-service payment, documents, maintenance requests.
4. **Automated messaging** — booking confirmation, pre-arrival, post-stay review request,
   arrears reminders at 3/7/14 days.
5. **Document storage and e-signature** for tenancy agreements.
6. **Dynamic pricing** — the analytics layer already computes ADR, RevPAR, pace and
   channel mix, which is the input a rate engine needs.
7. **Accounting export** (Xero / QuickBooks) and tax-ready reports.
8. **Audit log** of who changed what.

## Production notes

- Set a real `SECRET_KEY` (≥ 32 random bytes) and a Postgres `DATABASE_URL`.
- Restrict `CORS_ORIGINS` to your actual frontend origin.
- Add Alembic before the schema has data you care about.
- Rate-limit `/api/auth/login`.
