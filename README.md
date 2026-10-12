# HongDee — apartment & hostel management

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

Requires Python 3.10+.

```bash
./run.sh                      # installs deps, seeds demo data, serves on :8000
```

`run.sh` needs bash (Git Bash or WSL on Windows). The manual route works anywhere:

```bash
pip install -r requirements.txt
python -m backend.seed --reset      # rebuilds the demo database (drops existing tables first)
uvicorn backend.main:app --reload
```

The seed builds a demo portfolio of 3 properties, 46 units, 28 leases and about 4,500
bookings, with 14 months of billing history.

Open <http://127.0.0.1:8000> — API docs live at `/api/docs`.

| Demo account | Password | Access |
|---|---|---|
| `admin@hongdee.co.uk` | `admin1234` | everything, including user management |
| `manager@hongdee.co.uk` | `manager1234` | everything except user management |
| `frontdesk@hongdee.co.uk` | `frontdesk1234` | day-to-day operations: bookings, check-in/out, leases, payments, tickets. Can't void invoices, run the monthly rent run, delete records or add/remove properties, units and beds |
| `owner@hongdee.co.uk` | `viewer1234` | read only |

## Screens

![Dashboard](docs/dashboard.png)

![Front desk](docs/frontdesk.png)

![Analytics](docs/analytics.png)

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
commission tracking, and a front-desk board of today's arrivals, departures and in-house
guests. Check-out flags the unit for housekeeping.

**Billing** — one ledger for rent and accommodation. Idempotent monthly rent run,
part-payments, open/partial/paid/overdue statuses recomputed on every payment and on
demand, and an aged-debt report bucketed at 30/60/90 days.

**Maintenance** — ticketing with priority, assignee, cost and age. An urgent ticket takes
the unit off sale; resolving it puts it back and flags it for cleaning.

**Expenses** — categorised operating costs per property, which is what turns collected
revenue into a real NOI figure.

**Analytics** — occupancy split long-stay vs short-stay, MRR, collection rate, aged debt,
ADR and RevPAR, channel mix with commission leakage, per-property NOI, per-unit yield,
and a rule-based advisor that names the specific voids, under-market rents, overdue
accounts, OTA dependency, stale repairs and upcoming renewals costing money right now.

## Configuration

Settings come from environment variables, and every default works for local development.
`.env.example` lists them all. The app does not read `.env` by itself — export the
variables, or hand the file to uvicorn:

```bash
uvicorn backend.main:app --env-file .env
```

| Variable | Default | Purpose |
|---|---|---|
| `APP_NAME` | `HongDee` | name shown in the API docs and `/api/health` |
| `APP_ENV` | `development` | environment label returned by `/api/health` |
| `DATABASE_URL` | `sqlite:///./hongdee.db` | SQLAlchemy URL — see the Postgres note below |
| `SECRET_KEY` | dev placeholder | JWT signing key; **change before deploying** |
| `ACCESS_TOKEN_TTL_MINUTES` | `720` | login token lifetime |
| `DEFAULT_CURRENCY` | `GBP` | currency for analytics output |
| `CORS_ORIGINS` | `*` | comma-separated list of allowed origins |

**Postgres.** Install the driver (`pip install "psycopg[binary]"`) and set
`DATABASE_URL=postgresql+psycopg://user:password@host:5432/dbname`. The seed script reads the
same variable, so export it before seeding. The test suite runs on SQLite only; Postgres is
not covered by it.

## Architecture

```
backend/
  config.py        env-driven settings (SQLite by default, Postgres via DATABASE_URL)
  database.py      engine, session factory, declarative base
  models.py        SQLAlchemy 2.0 ORM — the domain model
  schemas.py       Pydantic request/response contracts
  security.py      PBKDF2-SHA256 password hashing, JWT issue/verify
  deps.py          current-user resolution and role gates
  services.py      business rules: availability, occupancy, invoicing, numbering
  routers/         one module per resource
  seed.py          realistic demo portfolio with 14 months of history
frontend/          single-page console: no build step, no framework
tests/             29 end-to-end API tests
docs/              screenshots used in this README
```

**Stack choice.** FastAPI + SQLAlchemy + SQLite/Postgres, with a dependency-free
frontend. The API is fully typed and self-documenting, and the whole thing runs from
one command — which matters more than framework fashion for a draft you want to
evaluate quickly. Swapping SQLite for Postgres is a `DATABASE_URL` change plus the
driver (see Configuration).

**Auth.** JWT bearer tokens, four roles (`admin`, `manager`, `staff`, `viewer`) enforced
by dependency injection per endpoint rather than checked ad hoc inside handlers.

**Frontend.** Vanilla JS with template strings and event delegation. Charts are
hand-rendered SVG — a validated colourblind-safe palette, one y-axis per chart, hover
tooltips, legends on multi-series charts and a monthly table view beneath the trend
charts on the Analytics page. Light and dark themes are separately specified rather than
auto-inverted.

## Tests

```bash
python -m pytest tests -q      # 29 passed
```

Coverage focuses on the rules that are expensive to get wrong: double-booking a bed,
back-to-back stays that must *not* clash, overlapping tenancies, idempotent rent runs,
part-payment status transitions, overpayment rejection, arrears bucketing, urgent-ticket
unit blocking, invoice numbers staying unique after deletions, role gates (read-only
users can't write, front desk can't delete contacts), and input checks that answer with a
4xx instead of a 500: duplicate unit names and bed labels, a bed from another unit, lease
edits with an out-of-range billing day or an end before the start, unknown references and
nulls sent for required fields. Each run uses a throwaway SQLite database.

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
6. **Dynamic pricing** — the analytics layer already computes ADR, RevPAR and channel
   mix, which is the input a rate engine needs.
7. **Accounting export** (Xero / QuickBooks) and tax-ready reports.
8. **Audit log** of who changed what.

## Production notes

- Set a real `SECRET_KEY` (≥ 32 random bytes) and a Postgres `DATABASE_URL`.
- Restrict `CORS_ORIGINS` to your actual frontend origin.
- Tables are created with `create_all` at startup. Add Alembic before the schema has data
  you care about.
- Rate-limit `/api/auth/login`.
- Don't seed a production database — the demo accounts above have published passwords.
