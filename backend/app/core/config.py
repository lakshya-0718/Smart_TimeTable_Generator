"""
Application configuration using pydantic-settings.

All settings are loaded from environment variables (or .env file).
Secrets like DB password and JWT secret should NEVER be hardcoded.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration — single source of truth for all env vars."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Application ──────────────────────────────────────────────────
    APP_NAME: str = "Smart Timetable Generator"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"  # development | staging | production

    # ── Database ─────────────────────────────────────────────────────
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_USER: str = "timetable_user"
    DB_PASSWORD: str = "changeme"
    DB_NAME: str = "timetable_db"

    @property
    def DATABASE_URL(self) -> str:
        """Async connection string for SQLAlchemy + asyncpg."""
        return (
            f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    @property
    def DATABASE_URL_SYNC(self) -> str:
        """Sync connection string for Alembic migrations."""
        return (
            f"postgresql+psycopg2://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    # ── JWT Auth ─────────────────────────────────────────────────────
    JWT_SECRET_KEY: str = "CHANGE-THIS-TO-A-REAL-SECRET"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_REFRESH_TOKEN_EXPIRE_MINUTES: int = 10080  # 7 days

    # ── Timetable Engine ─────────────────────────────────────────────
    MAX_SLOTS_PER_DAY: int = 8
    WORKING_DAYS: list[str] = [
        "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"
    ]
    LAB_CONTIGUOUS_SLOTS: int = 2  # labs need 2 consecutive slots
    MAX_BACKTRACK_ITERATIONS: int = 50_000
    OPTIMIZATION_PASSES: int = 3

    # ── CORS ─────────────────────────────────────────────────────────
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton — avoids re-reading .env on every call."""
    return Settings()
