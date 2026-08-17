"""Application configuration.

Everything is overridable through environment variables so the same code runs
on SQLite locally and PostgreSQL in production.
"""
from __future__ import annotations

import os
from functools import lru_cache


class Settings:
    APP_NAME: str = os.getenv("APP_NAME", "Haven PMS")
    APP_ENV: str = os.getenv("APP_ENV", "development")

    # SQLite by default; set DATABASE_URL=postgresql+psycopg://... for Postgres.
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./haven.db")

    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-change-me-in-production")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_TTL_MINUTES: int = int(os.getenv("ACCESS_TOKEN_TTL_MINUTES", "720"))

    DEFAULT_CURRENCY: str = os.getenv("DEFAULT_CURRENCY", "GBP")

    # Comma separated list, or "*" for everything.
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "*")

    @property
    def cors_origins(self) -> list[str]:
        if self.CORS_ORIGINS.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
