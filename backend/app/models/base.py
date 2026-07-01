"""
Shared mixins for all ORM models.

Provides:
- TimestampMixin  — created_at / updated_at (TIMESTAMPTZ)
- UUIDPrimaryKeyMixin — UUID PK + timestamps (standard base for all tables)
- CreatedAtMixin  — created_at only (for immutable tables: availability,
                    conflict_reports, timetable_entries)

Design notes:
- server_default=func.now() means the DB sets the timestamp at INSERT,
  not Python.  This guarantees correctness even when records are inserted
  via raw SQL or Alembic data migrations.
- onupdate=func.now() on updated_at triggers on SQLAlchemy-level UPDATEs.
  For DB-level updates outside SQLAlchemy, a PostgreSQL trigger is the
  complement (added in the Alembic migration).
- UUID primary keys use server_default=text("gen_random_uuid()") so that
  PostgreSQL generates the UUID, keeping generation consistent whether the
  INSERT originates from SQLAlchemy or a raw SQL script.
"""

import uuid

from sqlalchemy import DateTime, Index, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    """
    Adds created_at and updated_at to mutable domain tables.
    Used by: users, semesters, sections, rooms, courses, course_assignments,
             timetables.
    """

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class CreatedAtMixin:
    """
    Adds only created_at to immutable/append-only tables.
    Used by: faculty_availability, ta_availability, timetable_entries,
             conflict_reports.
    These rows are never updated in-place — only inserted or deleted.
    """

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class UUIDPrimaryKeyMixin(TimestampMixin):
    """
    UUID primary key + full timestamps.
    Standard base for all domain tables that are mutable.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


class UUIDPKCreatedAtMixin(CreatedAtMixin):
    """
    UUID primary key + created_at only.
    Used for immutable tables (availability slots, timetable entries,
    conflict reports) that are never updated — only created or deleted.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
