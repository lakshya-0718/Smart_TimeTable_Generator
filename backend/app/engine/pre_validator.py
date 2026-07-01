"""
engine/pre_validator.py — Pre-generation feasibility checks.

These checks run BEFORE the scheduler starts and are purely advisory.
They never block scheduling — they return a list of warning strings so
that timetable_service.py can surface them to the admin in the response.

Why only warnings, not errors?
  The scheduler supports partial scheduling (§16 of PROJECT_CONTEXT.md).
  Even if these checks fire, the engine should still attempt to schedule
  as much as possible.  Blocking on warnings would prevent partial results.

Checks performed:
  1. Room capacity feasibility:
     For each (session_type, section) pair, does at least one room of the
     correct type exist with capacity >= section.strength?
     If not, labs/lectures for that section cannot possibly be placed.

  2. Weekly slot feasibility:
     Does the total number of slots required across all sessions for a
     section fit within the available weekly time budget?
     Budget = 5 days x (SLOT_END - SLOT_START + 1) = 5 x 10 = 50 slots.
     Practical limit is lower once lunch breaks are accounted for, but
     50 is the hard ceiling used here as the pre-check.

  3. Missing TA warning:
     Tier 1 and Tier 2 assignments that have no ta_id — tutorials will
     be scheduled but there will be no TA clash checking.  Warn admin.

Entry point:
    warnings = run_pre_validation(ctx)
"""

from __future__ import annotations

from collections import defaultdict

from app.engine.types import (
    DAYS,
    SLOT_END,
    SLOT_START,
    SESSION_ROOM_TYPE,
    SchedulingContext,
    Session,
)


def run_pre_validation(ctx: SchedulingContext) -> list[str]:
    """
    Run all pre-generation feasibility checks and return a list of warnings.

    Args:
        ctx: The fully built SchedulingContext from context.py.

    Returns:
        A list of human-readable warning strings.  Empty list = no issues.
    """
    warnings: list[str] = []

    warnings.extend(_check_room_capacity(ctx))
    warnings.extend(_check_weekly_slot_budget(ctx))
    warnings.extend(_check_missing_ta(ctx))
    warnings.extend(_check_no_rooms(ctx))

    return warnings


# ── Internal check functions ──────────────────────────────────────────────────

def _check_room_capacity(ctx: SchedulingContext) -> list[str]:
    """
    Warn if any (session_type -> required_room_type) has no room with
    sufficient capacity to hold any section that needs it.

    We check per (section, session_type) pair to be specific.
    """
    warnings: list[str] = []

    # Build a set of available capacities per room type for fast lookup
    capacity_by_type: dict[str, list[int]] = defaultdict(list)
    for room in ctx.rooms:
        capacity_by_type[room.room_type].append(room.capacity)

    # Track which (section, required_room_type) combos we've already warned about
    warned: set[tuple[str, str]] = set()

    for session in ctx.sessions:
        required_room_type = SESSION_ROOM_TYPE.get(session.session_type, "LECTURE_HALL")
        strength = session.section_strength
        section_name = session.section_name

        key = (section_name, required_room_type)
        if key in warned:
            continue

        available = capacity_by_type.get(required_room_type, [])
        if not any(cap >= strength for cap in available):
            warned.add(key)
            warnings.append(
                f"WARNING: No {required_room_type} room has capacity >= {strength} "
                f"for section {section_name}. "
                f"Sessions requiring a {required_room_type} for this section may be unscheduled."
            )

    return warnings


def _check_weekly_slot_budget(ctx: SchedulingContext) -> list[str]:
    """
    Warn if the total slots required for any section exceeds the weekly cap.

    Max slots available per week = 5 days x 10 hours = 50.
    We subtract 1 per day for the mandatory midday break = 5 slots reserved.
    Practical budget = 45 schedulable slots per section per week.
    """
    warnings: list[str] = []

    WEEKLY_BUDGET = len(DAYS) * (SLOT_END - SLOT_START + 1)  # 50
    PRACTICAL_BUDGET = WEEKLY_BUDGET - len(DAYS)              # 45 (1 break/day)

    # Accumulate total slot-hours needed per section
    section_slots: dict[str, int] = defaultdict(int)
    for session in ctx.sessions:
        section_slots[session.section_name] += session.duration

    for section_name, total_slots in section_slots.items():
        if total_slots > PRACTICAL_BUDGET:
            warnings.append(
                f"WARNING: Section {section_name} requires {total_slots} slot-hours "
                f"per week, which exceeds the practical budget of {PRACTICAL_BUDGET}. "
                f"Some sessions will be unscheduled."
            )
        elif total_slots > WEEKLY_BUDGET * 0.80:
            warnings.append(
                f"INFO: Section {section_name} requires {total_slots} slot-hours "
                f"per week ({round(total_slots/WEEKLY_BUDGET*100)}% of weekly capacity). "
                f"Scheduling may be tight."
            )

    return warnings


def _check_missing_ta(ctx: SchedulingContext) -> list[str]:
    """
    Warn if a Tier 1 or Tier 2 assignment has no TA assigned.
    Tutorials for those sessions will still be scheduled but with ta_id=None.
    """
    warnings: list[str] = []
    warned_assignments: set[str] = set()

    for session in ctx.sessions:
        if session.session_type == "TUTORIAL" and session.ta_id is None:
            key = str(session.assignment_id)
            if key not in warned_assignments:
                warned_assignments.add(key)
                warnings.append(
                    f"WARNING: Tutorial for {session.course_code} / {session.section_name} "
                    f"has no TA assigned. TA clash checking will be skipped for this tutorial."
                )

    return warnings


def _check_no_rooms(ctx: SchedulingContext) -> list[str]:
    """
    Warn if there are no rooms of a required type at all.
    This catches misconfigured datasets early.
    """
    warnings: list[str] = []
    types_present = {r.room_type for r in ctx.rooms}
    types_needed = {SESSION_ROOM_TYPE[s.session_type] for s in ctx.sessions}

    for needed_type in types_needed:
        if needed_type not in types_present:
            warnings.append(
                f"WARNING: No {needed_type} rooms exist in the system. "
                f"All sessions requiring a {needed_type} will be unscheduled."
            )

    return warnings
