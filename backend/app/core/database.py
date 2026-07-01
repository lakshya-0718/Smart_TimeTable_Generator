"""
Async database engine and session management.

Uses SQLAlchemy 2.0 async API with asyncpg driver.
Each request gets an independent session via the `get_db` dependency.
"""

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

settings = get_settings()

# ── Engine ────────────────────────────────────────────────────────────
# pool_size + max_overflow = max concurrent DB connections
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,  # detect stale connections
)

# ── Session factory ───────────────────────────────────────────────────
async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ── Base class for all models ─────────────────────────────────────────
class Base(DeclarativeBase):
    """All ORM models inherit from this. Alembic auto-detects subclasses."""
    pass


# ── Dependency for FastAPI routes ─────────────────────────────────────
async def get_db() -> AsyncSession:
    """
    Yield an async session per request.
    Commits happen explicitly in service layer; rollback on exception.
    """
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
