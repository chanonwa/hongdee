"""End-to-end API tests against a throwaway SQLite database."""
from __future__ import annotations

import os
import tempfile
from datetime import date, timedelta

import pytest

TMP = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{TMP}/test.db"
os.environ["SECRET_KEY"] = "test-secret"

from fastapi.testclient import TestClient  # noqa: E402

from backend.database import SessionLocal, init_db  # noqa: E402
from backend.main import app  # noqa: E402
from backend.models import Role, User  # noqa: E402
from backend.security import hash_password  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _db():
    init_db()
    db = SessionLocal()
    db.add(User(email="t@havenpms.co.uk", full_name="Tester", role=Role.admin,
                hashed_password=hash_password("test1234")))
    db.commit()
    db.close()


@pytest.fixture(scope="session")
def client(_db):
    c = TestClient(app)
    r = c.post("/api/auth/login", data={"username": "t@havenpms.co.uk", "password": "test1234"})
    assert r.status_code == 200, r.text
    c.headers.update({"Authorization": f"Bearer {r.json()['access_token']}"})
    return c


@pytest.fixture(scope="session")
def fixtures(client):
    """A hostel with one 2-bed dorm, an apartment, a tenant and a guest."""
    prop = client.post("/api/properties", json={"name": "Test House", "code": "TST", "type": "mixed"}).json()
    dorm = client.post("/api/units", json={
        "property_id": prop["id"], "name": "Dorm 1", "type": "dorm",
        "capacity": 2, "nightly_rate": 20, "bed_count": 2}).json()
    flat = client.post("/api/units", json={
        "property_id": prop["id"], "name": "Flat 1", "type": "apartment", "market_rent": 900}).json()
    tenant = client.post("/api/people", json={"full_name": "Tina Tenant", "type": "tenant"}).json()
    guest = client.post("/api/people", json={"full_name": "Gary Guest", "type": "guest"}).json()
    return {"prop": prop, "dorm": dorm, "flat": flat, "tenant": tenant, "guest": guest}


# ------------------------------------------------------------------ auth ---
def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_login_rejects_bad_password(client):
    r = client.post("/api/auth/login", data={"username": "t@havenpms.co.uk", "password": "nope"})
    assert r.status_code == 401


def test_endpoints_require_a_token():
    with TestClient(app) as anon:
        assert anon.get("/api/properties").status_code == 401


# ------------------------------------------------------------- inventory ---
def test_dorm_creates_its_beds(fixtures):
    assert len(fixtures["dorm"]["beds"]) == 2


def test_duplicate_property_code_rejected(client, fixtures):
    r = client.post("/api/properties", json={"name": "Clash", "code": "TST"})
    assert r.status_code == 409


# -------------------------------------------------------------- bookings ---
def test_booking_blocks_the_same_bed_twice(client, fixtures):
    bed = fixtures["dorm"]["beds"][0]["id"]
    body = {
        "unit_id": fixtures["dorm"]["id"], "bed_id": bed, "person_id": fixtures["guest"]["id"],
        "check_in": "2030-01-10", "check_out": "2030-01-13", "nightly_rate": 20,
    }
    first = client.post("/api/bookings", json=body)
    assert first.status_code == 201, first.text
    assert first.json()["nights"] == 3
    assert first.json()["total_amount"] == 60

    clash = client.post("/api/bookings", json={**body, "check_in": "2030-01-12", "check_out": "2030-01-15"})
    assert clash.status_code == 409

    # The other bed in the same dorm is still sellable for those dates.
    other = client.post("/api/bookings", json={**body, "bed_id": fixtures["dorm"]["beds"][1]["id"]})
    assert other.status_code == 201


def test_back_to_back_stays_do_not_clash(client, fixtures):
    """Checkout day is the next guest's arrival day - half-open intervals."""
    bed = fixtures["dorm"]["beds"][0]["id"]
    body = {"unit_id": fixtures["dorm"]["id"], "bed_id": bed, "person_id": fixtures["guest"]["id"],
            "nightly_rate": 20}
    a = client.post("/api/bookings", json={**body, "check_in": "2030-03-01", "check_out": "2030-03-03"})
    b = client.post("/api/bookings", json={**body, "check_in": "2030-03-03", "check_out": "2030-03-05"})
    assert a.status_code == 201 and b.status_code == 201


def test_availability_excludes_booked_beds(client, fixtures):
    rows = client.get("/api/bookings/availability?check_in=2030-01-11&check_out=2030-01-12").json()
    dorm = next((r for r in rows if r["unit_id"] == fixtures["dorm"]["id"]), None)
    assert dorm is None or len(dorm["free_beds"]) == 0


def test_checkout_flags_housekeeping(client, fixtures):
    bed = fixtures["dorm"]["beds"][1]["id"]
    bk = client.post("/api/bookings", json={
        "unit_id": fixtures["dorm"]["id"], "bed_id": bed, "person_id": fixtures["guest"]["id"],
        "check_in": "2031-05-01", "check_out": "2031-05-02", "nightly_rate": 25}).json()
    client.post(f"/api/bookings/{bk['id']}/check-out")
    unit = client.get(f"/api/units/{fixtures['dorm']['id']}").json()
    assert unit["housekeeping"] == "dirty"


def test_checkout_before_checkin_rejected(client, fixtures):
    r = client.post("/api/bookings", json={
        "unit_id": fixtures["dorm"]["id"], "person_id": fixtures["guest"]["id"],
        "check_in": "2030-06-10", "check_out": "2030-06-10", "nightly_rate": 20})
    assert r.status_code == 422


# ---------------------------------------------------------------- leases ---
def test_overlapping_lease_on_one_unit_rejected(client, fixtures):
    body = {"unit_id": fixtures["flat"]["id"], "person_id": fixtures["tenant"]["id"],
            "start_date": "2029-01-01", "end_date": "2029-12-31", "rent_amount": 900, "billing_day": 1}
    assert client.post("/api/leases", json=body).status_code == 201
    clash = client.post("/api/leases", json={**body, "start_date": "2029-06-01", "end_date": "2030-05-31"})
    assert clash.status_code == 409


def test_lease_marks_unit_occupied(client, fixtures):
    unit = client.get(f"/api/units/{fixtures['flat']['id']}").json()
    assert unit["status"] == "occupied"


def test_invalid_billing_day_rejected(client, fixtures):
    r = client.post("/api/leases", json={
        "unit_id": fixtures["flat"]["id"], "person_id": fixtures["tenant"]["id"],
        "start_date": "2040-01-01", "rent_amount": 500, "billing_day": 31})
    assert r.status_code == 422


# --------------------------------------------------------------- billing ---
def test_rent_run_is_idempotent(client, fixtures):
    payload = {"year": 2029, "month": 3}
    first = client.post("/api/billing/rent-run", json=payload).json()
    second = client.post("/api/billing/rent-run", json=payload).json()
    assert first["created"] >= 1
    assert second["created"] == 0 and second["skipped"] >= 1


def test_payment_updates_invoice_status(client, fixtures):
    inv = client.post("/api/billing/invoices", json={
        "person_id": fixtures["tenant"]["id"], "charge_type": "utilities",
        "issue_date": str(date.today()), "due_date": str(date.today() + timedelta(days=7)),
        "amount": 100}).json()

    half = client.post("/api/billing/payments", json={
        "invoice_id": inv["id"], "amount": 40, "paid_on": str(date.today())})
    assert half.status_code == 201
    assert client.get(f"/api/billing/invoices/{inv['id']}").json()["status"] == "partial"

    client.post("/api/billing/payments", json={
        "invoice_id": inv["id"], "amount": 60, "paid_on": str(date.today())})
    after = client.get(f"/api/billing/invoices/{inv['id']}").json()
    assert after["status"] == "paid" and after["balance"] == 0


def test_overpayment_rejected(client, fixtures):
    inv = client.post("/api/billing/invoices", json={
        "person_id": fixtures["tenant"]["id"], "charge_type": "other",
        "issue_date": str(date.today()), "due_date": str(date.today()), "amount": 50}).json()
    r = client.post("/api/billing/payments", json={
        "invoice_id": inv["id"], "amount": 51, "paid_on": str(date.today())})
    assert r.status_code == 422


def test_overdue_invoice_lands_in_arrears(client, fixtures):
    client.post("/api/billing/invoices", json={
        "person_id": fixtures["tenant"]["id"], "charge_type": "rent",
        "issue_date": str(date.today() - timedelta(days=120)),
        "due_date": str(date.today() - timedelta(days=100)), "amount": 250})
    client.post("/api/billing/sync-statuses")
    rows = client.get("/api/billing/arrears").json()
    tina = next(r for r in rows if r["person_id"] == fixtures["tenant"]["id"])
    assert tina["d90_plus"] >= 250


# -------------------------------------------------------------- analytics ---
def test_summary_shape(client, fixtures):
    k = client.get("/api/analytics/summary").json()
    for key in ("occupancy_rate", "monthly_recurring_revenue", "adr", "revpar", "net_operating_income"):
        assert key in k
    assert 0 <= k["occupancy_rate"] <= 100


def test_trend_returns_requested_months(client, fixtures):
    assert len(client.get("/api/analytics/trend?months=6").json()) == 6


def test_recommendations_are_ranked(client, fixtures):
    recs = client.get("/api/analytics/recommendations").json()
    order = {"critical": 0, "warning": 1, "info": 2}
    assert [order[r["severity"]] for r in recs] == sorted(order[r["severity"]] for r in recs)


# ------------------------------------------------------------ maintenance ---
def test_urgent_ticket_takes_unit_offline_then_returns_it(client, fixtures):
    t = client.post("/api/maintenance", json={
        "property_id": fixtures["prop"]["id"], "unit_id": fixtures["dorm"]["id"],
        "title": "Flood", "priority": "urgent", "reported_at": str(date.today())}).json()
    assert client.get(f"/api/units/{fixtures['dorm']['id']}").json()["status"] == "maintenance"

    client.patch(f"/api/maintenance/{t['id']}", json={"status": "resolved"})
    assert client.get(f"/api/units/{fixtures['dorm']['id']}").json()["status"] == "available"


# ------------------------------------------------------------------ roles ---
def test_viewer_cannot_write(client, fixtures):
    client.post("/api/auth/users", json={
        "email": "v@havenpms.co.uk", "full_name": "Vera Viewer", "role": "viewer", "password": "viewer1234"})
    with TestClient(app) as v:
        tok = v.post("/api/auth/login", data={"username": "v@havenpms.co.uk", "password": "viewer1234"}).json()
        v.headers.update({"Authorization": f"Bearer {tok['access_token']}"})
        assert v.get("/api/properties").status_code == 200
        assert v.post("/api/people", json={"full_name": "Nope"}).status_code == 403
