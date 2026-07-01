"""
models/__init__.py — single import point for all ORM models.

Importing this package is the only thing Alembic and the FastAPI
lifespan need to do to ensure that SQLAlchemy's metadata is fully
populated before `Base.metadata.create_all()` or Alembic's
`autogenerate` runs.

Import order matters: base types first, then enums, then models that
have no FK dependencies, then models with FK dependencies, then the
most-dependent models last.

DO NOT add business logic here.  This file is a pure registry.
"""

# ── Shared infrastructure ─────────────────────────────────────────────
from app.models.base import (  # noqa: F401
    CreatedAtMixin,
    TimestampMixin,
    UUIDPKCreatedAtMixin,
    UUIDPrimaryKeyMixin,
)

# ── Enums ─────────────────────────────────────────────────────────────
from app.models.enums import (  # noqa: F401
    CourseTier,
    DayOfWeek,
    RoomType,
    SessionType,
    TimetableStatus,
    UserRole,
)

# ── Leaf models (no FK dependencies on other domain models) ──────────
from app.models.user import User  # noqa: F401
from app.models.semester import Semester  # noqa: F401
from app.models.section import Section  # noqa: F401
from app.models.room import Room  # noqa: F401

# ── Mid-level models ─────────────────────────────────────────────────
from app.models.course import Course  # noqa: F401
from app.models.availability import FacultyAvailability, TAAvailability  # noqa: F401

# ── Scheduling atom ───────────────────────────────────────────────────
from app.models.course_assignment import CourseAssignment  # noqa: F401

# ── Timetable cluster (most FK-dependent) ────────────────────────────
from app.models.timetable import (  # noqa: F401
    ConflictReport,
    Timetable,
    TimetableEntry,
)

__all__ = [
    # Mixins
    "CreatedAtMixin",
    "TimestampMixin",
    "UUIDPKCreatedAtMixin",
    "UUIDPrimaryKeyMixin",
    # Enums
    "CourseTier",
    "DayOfWeek",
    "RoomType",
    "SessionType",
    "TimetableStatus",
    "UserRole",
    # Models
    "User",
    "Semester",
    "Section",
    "Room",
    "Course",
    "FacultyAvailability",
    "TAAvailability",
    "CourseAssignment",
    "Timetable",
    "TimetableEntry",
    "ConflictReport",
]
