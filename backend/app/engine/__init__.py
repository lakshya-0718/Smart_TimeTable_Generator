"""
engine/__init__.py — Public API of the scheduler engine.

Exposes run_scheduler() as the single entry point for timetable_service.py.

Usage in timetable_service.py:
    from app.engine import run_scheduler
    from app.engine.context import build_context

    context = await build_context(db, semester_id)
    result = await loop.run_in_executor(None, run_scheduler, context)
    # result.assignments -> list[SlotAssignment]
    # result.unscheduled -> list[UnscheduledSession]
    # result.warnings    -> list[str]

Note:
    build_context is imported lazily (via app.engine.context) rather than
    re-exported here to avoid importing SQLAlchemy ORM models at module
    load time.  The pure-logic modules (types, graph, validator, scheduler,
    conflict, pre_validator) have NO database dependencies and are always
    importable without a live DB connection or asyncpg installed.
"""

# Pure engine — no database dependency
from app.engine.scheduler import run_scheduler
from app.engine.types import (
    SchedulingContext,
    SchedulingResult,
    SlotAssignment,
    UnscheduledSession,
    Session,
    RoomInfo,
    SectionInfo,
    ReasonCode,
)

# build_context is DB-dependent (imports ORM models).
# Import it explicitly when needed:
#   from app.engine.context import build_context
# timetable_service.py already does this directly.

__all__ = [
    "run_scheduler",
    "SchedulingContext",
    "SchedulingResult",
    "SlotAssignment",
    "UnscheduledSession",
    "Session",
    "RoomInfo",
    "SectionInfo",
    "ReasonCode",
]
