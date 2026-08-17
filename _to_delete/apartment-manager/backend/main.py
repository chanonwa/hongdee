"""Haven PMS - FastAPI application entrypoint."""
from __future__ import annotations

import os
from pathlib import Path

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import init_db
from .routers import (
    analytics,
    auth,
    billing,
    bookings,
    expenses,
    leases,
    maintenance,
    people,
    properties,
    units,
)

@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    lifespan=lifespan,
    title=settings.APP_NAME,
    version="0.1.0",
    description=(
        "Property management API for mixed apartment + hostel portfolios. "
        "Covers inventory, tenants and guests, leases, reservations, a unified "
        "billing ledger, maintenance, expenses and revenue analytics."
    ),
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (
    auth.router,
    properties.router,
    units.router,
    people.router,
    leases.router,
    bookings.router,
    billing.router,
    maintenance.router,
    expenses.router,
    analytics.router,
):
    app.include_router(r)


@app.get("/api/health", tags=["meta"])
def health():
    return {"status": "ok", "app": settings.APP_NAME, "env": settings.APP_ENV}


# ---- static frontend ------------------------------------------------------ #
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(FRONTEND_DIR / "index.html")
