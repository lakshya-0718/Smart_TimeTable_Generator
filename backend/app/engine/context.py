"""
engine/context.py — Build a SchedulingContext from DB-loaded data.

This is the ONLY module in the engine package that touches the database.
It loads every piece of data the engine needs and converts it into
pure-Python dataclasses so the rest of the engine remains DB-free.

Entry point:
    context = await build_context(db, semester_id)

What it loads:
    1. All CourseAssignment rows for the semester (with eager-joined
       Course, Section data already available via SQLAlchemy relationships).
    2. All Room rows.
    3. All FacultyAvailability rows for all faculty in those assignments.
    4. All TAAvailability rows for all TAs in those assignments.

Session expansion (§4 of system_architecture.md):
    TIER_1 -> Lecture x3, Tutorial x1, Lab x1  (3-slot lab)
    TIER_2 -> Lecture x3, Tutorial x1
    TIER_3 -> Lab x1                            (4-slot lab)
    TIER_4 -> Lab x1                            (2-slot lab)

Each Session gets a unique string ID: "<assignment_uuid>-<TYPE>-<index>"
so it can be tracked unambiguously through the scheduling pipeline.

The function is async because DB access is async in this project.
The engine itself (scheduler.py) is synchronous and runs in a thread.
"""

from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.availability import FacultyAvailability, TAAvailability
from app.models.course_assignment import CourseAssignment
from app.models.room import Room

from app.engine.types import (
    RoomInfo,
    SchedulingContext,
    SectionInfo,
    Session,
)

# ── Tier -> session structure mapping ─────────────────────────────────────────
# Each entry is a list of (session_type, duration) tuples.
# duration = number of consecutive 1-hour slots the session occupies.
_TIER_SESSIONS: dict[str, list[tuple[str, int]]] = {
    "TIER_1": [
        ("LECTURE",  1),
        ("LECTURE",  1),
        ("LECTURE",  1),
        ("TUTORIAL", 1),
        ("LAB",      3),
    ],
    "TIER_2": [
        ("LECTURE",  1),
        ("LECTURE",  1),
        ("LECTURE",  1),
        ("TUTORIAL", 1),
    ],
    "TIER_3": [
        ("LAB", 4),
    ],
    "TIER_4": [
        ("LAB", 2),
    ],
}


async def build_context(
    db: AsyncSession,
    semester_id: uuid.UUID,
) -> SchedulingContext:
    """
    Load all scheduling data from the database and return a SchedulingContext.

    Args:
        db:          An active async SQLAlchemy session.
        semester_id: The semester for which to build the context.

    Returns:
        A fully populated SchedulingContext ready to pass to run_scheduler().

    Raises:
        ValueError: If no CourseAssignment rows exist for the semester.
    """

    # ── 1. Load CourseAssignments for this semester ───────────────────────────
    # The Course relationship is eagerly loaded (lazy="selectin" on Course.assignments).
    # We access course.tier, course.name, course.code, section.name, section.strength
    # through the ORM relationships without extra queries.
    result = await db.execute(
        select(CourseAssignment)
        .join(CourseAssignment.course)
        .where(CourseAssignment.course.has(semester_id=semester_id))
        .options(
            selectinload(CourseAssignment.course),
            selectinload(CourseAssignment.section)
        )
    )
    assignments: list[CourseAssignment] = list(result.scalars().unique().all())

    if not assignments:
        raise ValueError(
            f"No course assignments found for semester {semester_id}."
        )

    # ── 2. Collect unique faculty IDs and TA IDs for availability loading ─────
    faculty_ids: set[uuid.UUID] = set()
    ta_ids: set[uuid.UUID] = set()
    section_map: dict[uuid.UUID, SectionInfo] = {}

    for ca in assignments:
        faculty_ids.add(ca.faculty_id)
        if ca.ta_id is not None:
            ta_ids.add(ca.ta_id)
        # Build section lookup from the relationship (already eager-loaded)
        sec = ca.section
        if sec.id not in section_map:
            section_map[sec.id] = SectionInfo(
                id=sec.id,
                name=sec.name,
                strength=sec.strength,
            )

    # ── 3. Load faculty unavailability ────────────────────────────────────────
    faculty_unavailable: dict[uuid.UUID, set[tuple[str, int]]] = defaultdict(set)
    if faculty_ids:
        fa_result = await db.execute(
            select(FacultyAvailability).where(
                FacultyAvailability.user_id.in_(faculty_ids)
            )
        )
        for fa in fa_result.scalars().all():
            day_str = fa.day.value if hasattr(fa.day, "value") else str(fa.day)
            faculty_unavailable[fa.user_id].add((day_str, fa.slot_hour))

    # ── 4. Load TA unavailability ─────────────────────────────────────────────
    ta_unavailable: dict[uuid.UUID, set[tuple[str, int]]] = defaultdict(set)
    if ta_ids:
        ta_result = await db.execute(
            select(TAAvailability).where(
                TAAvailability.user_id.in_(ta_ids)
            )
        )
        for ta in ta_result.scalars().all():
            day_str = ta.day.value if hasattr(ta.day, "value") else str(ta.day)
            ta_unavailable[ta.user_id].add((day_str, ta.slot_hour))

    # ── 5. Load all rooms, sorted by (room_type, capacity ASC) ───────────────
    rooms_result = await db.execute(
        select(Room).order_by(Room.room_type, Room.capacity)
    )
    rooms: list[RoomInfo] = [
        RoomInfo(
            id=r.id,
            name=r.name,
            room_type=r.room_type.value if hasattr(r.room_type, "value") else str(r.room_type),
            capacity=r.capacity,
        )
        for r in rooms_result.scalars().all()
    ]

    # ── 6. Expand CourseAssignments into Session objects ──────────────────────
    sessions: list[Session] = []

    for ca in assignments:
        course = ca.course
        sec = ca.section
        tier_str = course.tier.value if hasattr(course.tier, "value") else str(course.tier)

        session_templates = _TIER_SESSIONS.get(tier_str, [])

        for index, (session_type, duration) in enumerate(session_templates):
            # Unique ID within this engine run
            session_id = f"{ca.id}-{session_type}-{index}"

            # TA is relevant for TUTORIAL and LAB sessions
            ta_id: uuid.UUID | None = None
            if session_type in ("TUTORIAL", "LAB"):
                ta_id = ca.ta_id

            sessions.append(
                Session(
                    id=session_id,
                    assignment_id=ca.id,
                    course_id=course.id,
                    course_name=course.name,
                    course_code=course.code,
                    section_id=sec.id,
                    section_name=sec.name,
                    session_type=session_type,
                    duration=duration,
                    faculty_id=ca.faculty_id,
                    ta_id=ta_id,
                    tier=tier_str,
                    section_strength=sec.strength,
                )
            )

    return SchedulingContext(
        semester_id=semester_id,
        sessions=sessions,
        rooms=rooms,
        sections=section_map,
        faculty_unavailable=dict(faculty_unavailable),
        ta_unavailable=dict(ta_unavailable),
    )
