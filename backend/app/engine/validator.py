"""
engine/validator.py — Per-constraint check functions for the scheduler.

Every function in this module is PURE:
  - Takes: (session, day, start_slot, room, current_assignments, ctx)
  - Returns: bool  (True = constraint satisfied, False = violated)
  - Has zero side effects.

The scheduler calls these functions when evaluating every candidate
(day, slot, room) for each session.  They are the innermost hot loop
of the scheduling algorithm, so they are kept as simple as possible.

Constraints enforced (per system_architecture.md §4 Step 6 and
PROJECT_CONTEXT.md §14):

  Resource clashes (checked via current_assignments lookup):
    - Faculty clash    — no two sessions with same faculty at (day, slot)
    - Section clash    — no two sessions with same section at (day, slot)
    - TA clash         — no two sessions with same ta_id at (day, slot)
    - Room clash       — no two sessions in same room at (day, slot)

  Capacity:
    - Room capacity    — room.capacity >= session.section_strength

  Daily load caps:
    - Student daily    — section total slots on day + duration <= 6
    - Faculty daily    — faculty total slots on day + duration <= 4
    - TA daily         — TA total slots on day + duration <= 3

  Structural:
    - Lecture same day — LECTURE sessions: course+section already has
                         a lecture on this day -> block (spread across days)
    - Midday break     — section must have at least 1 free hour in {12,13,14}
                         on any day it has classes.

  Lab-specific:
    - Lab consecutive  — lab must fit in [SLOT_START, SLOT_END] without
                         crossing the section's chosen midday break hour.
                         The midday break check is embedded here: we verify
                         that no slot in [start, start+duration) lands in
                         the section's only remaining free LUNCH_SLOT on that day.

  Availability blacklists:
    - Faculty unavailable — (faculty_id, day, slot) in faculty_unavailable set
    - TA unavailable      — (ta_id, day, slot) in ta_unavailable set

State representation:
  current_assignments: dict mapping (day, start_slot) to a list of
  SlotAssignment objects.  This flat dict is maintained by scheduler.py.

  Helper index structures (built once, updated incrementally by scheduler.py):
    faculty_day_slots:  dict[(faculty_id, day)] -> list[start_slot]
    section_day_slots:  dict[(section_id, day)] -> list[start_slot]
    ta_day_slots:       dict[(ta_id, day)]      -> list[start_slot]
    room_day_slots:     dict[(room_id, day)]    -> list[start_slot]

These indexes are passed in as a single _StateIndex namedtuple so the
validator signatures stay clean and the caller controls mutation.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from app.engine.types import (
    DAYS,
    FACULTY_DAILY_MAX,
    LUNCH_SLOTS,
    SESSION_ROOM_TYPE,
    SLOT_END,
    SLOT_START,
    STUDENT_DAILY_MAX,
    TA_DAILY_MAX,
    RoomInfo,
    ReasonCode,
    SchedulingContext,
    Session,
    SlotAssignment,
)


# ═════════════════════════════════════════════════════════════════════════════
# State index — maintained by scheduler.py, read by validator functions
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class StateIndex:
    """
    Incrementally maintained lookup structures over current_assignments.

    Kept separate from SchedulingContext because this state mutates as
    sessions are assigned and unassigned during backtracking.

    All dict values are lists of start_slots that are occupied on that day.
    For multi-slot sessions (labs), ALL occupied slots are recorded, not just
    the start slot — this makes slot-range checks O(duration) instead of
    requiring range arithmetic everywhere.

    Attributes:
        faculty_day_slots:
            (faculty_id, day) -> list of ALL slot hours occupied.
        section_day_slots:
            (section_id, day) -> list of ALL slot hours occupied.
        ta_day_slots:
            (ta_id, day)      -> list of ALL slot hours occupied.
        room_day_slots:
            (room_id, day)    -> list of ALL slot hours occupied.
        lecture_days:
            (section_id, course_id) -> set of days that already have a LECTURE.
            Used to enforce lecture-spread-across-days constraint.
        assignments:
            Flat list of all SlotAssignment objects placed so far.
            Used by backtracking to find and remove specific assignments.
    """
    faculty_day_slots: dict[tuple[uuid.UUID, str], list[int]] = field(
        default_factory=lambda: defaultdict(list)
    )
    section_day_slots: dict[tuple[uuid.UUID, str], list[int]] = field(
        default_factory=lambda: defaultdict(list)
    )
    ta_day_slots: dict[tuple[uuid.UUID, str], list[int]] = field(
        default_factory=lambda: defaultdict(list)
    )
    room_day_slots: dict[tuple[uuid.UUID, str], list[int]] = field(
        default_factory=lambda: defaultdict(list)
    )
    lecture_days: dict[tuple[uuid.UUID, uuid.UUID], set[str]] = field(
        default_factory=lambda: defaultdict(set)
    )
    assignments: list[SlotAssignment] = field(default_factory=list)


def make_state_index() -> StateIndex:
    """Create a fresh, empty StateIndex."""
    return StateIndex(
        faculty_day_slots=defaultdict(list),
        section_day_slots=defaultdict(list),
        ta_day_slots=defaultdict(list),
        room_day_slots=defaultdict(list),
        lecture_days=defaultdict(set),
        assignments=[],
    )


def record_assignment(
    state: StateIndex,
    session: Session,
    assignment: SlotAssignment,
) -> None:
    """
    Update all index structures when a session is assigned.
    Records every slot in [start_slot, end_slot) as occupied.
    """
    day = assignment.day
    for slot in range(assignment.start_slot, assignment.end_slot):
        state.faculty_day_slots[(assignment.faculty_id, day)].append(slot)
        state.section_day_slots[(assignment.section_id, day)].append(slot)
        if assignment.ta_id is not None:
            state.ta_day_slots[(assignment.ta_id, day)].append(slot)
        state.room_day_slots[(assignment.room_id, day)].append(slot)

    if session.session_type == "LECTURE":
        state.lecture_days[(session.section_id, session.course_id)].add(day)

    state.assignments.append(assignment)


def remove_assignment(
    state: StateIndex,
    session: Session,
    assignment: SlotAssignment,
) -> None:
    """
    Undo all index updates when a session is unassigned (backtracking).
    """
    day = assignment.day
    for slot in range(assignment.start_slot, assignment.end_slot):
        _remove_from_list(state.faculty_day_slots[(assignment.faculty_id, day)], slot)
        _remove_from_list(state.section_day_slots[(assignment.section_id, day)], slot)
        if assignment.ta_id is not None:
            _remove_from_list(state.ta_day_slots[(assignment.ta_id, day)], slot)
        _remove_from_list(state.room_day_slots[(assignment.room_id, day)], slot)

    if session.session_type == "LECTURE":
        lecture_set = state.lecture_days.get((session.section_id, session.course_id), set())
        lecture_set.discard(day)

    # Remove from flat assignments list
    try:
        # We match by identity via assignment_id + day + start_slot
        idx = next(
            i for i, a in enumerate(state.assignments)
            if (a.assignment_id == assignment.assignment_id
                and a.day == assignment.day
                and a.start_slot == assignment.start_slot
                and a.session_type == assignment.session_type)
        )
        state.assignments.pop(idx)
    except StopIteration:
        pass  # already removed (shouldn't happen)


def _remove_from_list(lst: list[int], value: int) -> None:
    """Remove the first occurrence of value from a list (in-place)."""
    try:
        lst.remove(value)
    except ValueError:
        pass


# ═════════════════════════════════════════════════════════════════════════════
# Constraint check functions
# ═════════════════════════════════════════════════════════════════════════════

def check_all_constraints(
    session: Session,
    day: str,
    start_slot: int,
    room: RoomInfo,
    state: StateIndex,
    ctx: SchedulingContext,
) -> tuple[bool, list[str]]:
    """
    Run every hard constraint for the given (session, day, slot, room) candidate.

    Returns:
        (passed: bool, violated_constraints: list[str])
        passed=True means ALL constraints were satisfied.
        violated_constraints contains ReasonCode strings for every failure.
    """
    end_slot = start_slot + session.duration
    violations: list[str] = []

    # ── 1. Slot range feasibility ─────────────────────────────────────────────
    if end_slot > SLOT_END + 1:  # SLOT_END=17, so max end_slot=18
        violations.append(ReasonCode.LAB_CONSECUTIVE)
        return False, violations

    # ── 2. Room type match ────────────────────────────────────────────────────
    required_type = SESSION_ROOM_TYPE.get(session.session_type, "LECTURE_HALL")
    if room.room_type != required_type:
        # This shouldn't be called with the wrong room type, but guard anyway
        violations.append(ReasonCode.ROOM_CAPACITY)
        return False, violations

    # ── 3. Room capacity ──────────────────────────────────────────────────────
    if not check_room_capacity(session, room):
        violations.append(ReasonCode.ROOM_CAPACITY)

    # ── 4. Faculty unavailability ─────────────────────────────────────────────
    if not check_faculty_available(session, day, start_slot, ctx):
        violations.append(ReasonCode.FACULTY_UNAVAILABLE)

    # ── 5. TA unavailability ──────────────────────────────────────────────────
    if not check_ta_available(session, day, start_slot, ctx):
        violations.append(ReasonCode.TA_UNAVAILABLE)

    # ── 6. Faculty clash ──────────────────────────────────────────────────────
    if not check_faculty_clash(session, day, start_slot, state):
        violations.append(ReasonCode.FACULTY_CLASH)

    # ── 7. Section clash ──────────────────────────────────────────────────────
    if not check_section_clash(session, day, start_slot, state):
        violations.append(ReasonCode.SECTION_CLASH)

    # ── 8. TA clash ───────────────────────────────────────────────────────────
    if not check_ta_clash(session, day, start_slot, state):
        violations.append(ReasonCode.TA_CLASH)

    # ── 9. Room clash ─────────────────────────────────────────────────────────
    if not check_room_clash(room, day, start_slot, session.duration, state):
        violations.append(ReasonCode.ROOM_CLASH)

    # ── 10. Student daily load ────────────────────────────────────────────────
    if not check_student_daily_load(session, day, state):
        violations.append(ReasonCode.STUDENT_DAILY_LOAD)

    # ── 11. Faculty daily load ────────────────────────────────────────────────
    if not check_faculty_daily_load(session, day, state):
        violations.append(ReasonCode.FACULTY_DAILY_LOAD)

    # ── 12. TA daily load ─────────────────────────────────────────────────────
    if not check_ta_daily_load(session, day, state):
        violations.append(ReasonCode.TA_DAILY_LOAD)

    # ── 13. Lecture spread (one lecture per course per day) ───────────────────
    if not check_lecture_day_spread(session, day, state):
        violations.append(ReasonCode.LECTURE_SAME_DAY)

    # ── 14. Midday break preservation ────────────────────────────────────────
    if not check_midday_break(session, day, start_slot, state):
        violations.append(ReasonCode.MIDDAY_BREAK)

    # ── 15. Lab consecutive / no-lunch-overlap ────────────────────────────────
    if session.session_type == "LAB":
        if not check_lab_consecutive(session, day, start_slot, state):
            violations.append(ReasonCode.LAB_CONSECUTIVE)

    passed = len(violations) == 0
    return passed, violations


# ── Individual constraint functions ──────────────────────────────────────────
# Each returns True = satisfied, False = violated.

def check_room_capacity(session: Session, room: RoomInfo) -> bool:
    """Room must be large enough for the section."""
    return room.capacity >= session.section_strength


def check_faculty_available(
    session: Session,
    day: str,
    start_slot: int,
    ctx: SchedulingContext,
) -> bool:
    """Faculty must not have marked any slot in [start, end) as unavailable."""
    blocked = ctx.faculty_unavailable.get(session.faculty_id, set())
    for slot in range(start_slot, start_slot + session.duration):
        if (day, slot) in blocked:
            return False
    return True


def check_ta_available(
    session: Session,
    day: str,
    start_slot: int,
    ctx: SchedulingContext,
) -> bool:
    """TA must not have marked any slot in [start, end) as unavailable."""
    if session.ta_id is None:
        return True
    blocked = ctx.ta_unavailable.get(session.ta_id, set())
    for slot in range(start_slot, start_slot + session.duration):
        if (day, slot) in blocked:
            return False
    return True


def check_faculty_clash(
    session: Session,
    day: str,
    start_slot: int,
    state: StateIndex,
) -> bool:
    """Faculty must have no other session in any of the slots [start, end)."""
    occupied = state.faculty_day_slots.get((session.faculty_id, day), [])
    occupied_set = set(occupied)
    for slot in range(start_slot, start_slot + session.duration):
        if slot in occupied_set:
            return False
    return True


def check_section_clash(
    session: Session,
    day: str,
    start_slot: int,
    state: StateIndex,
) -> bool:
    """Section must have no other session in any of the slots [start, end)."""
    occupied = state.section_day_slots.get((session.section_id, day), [])
    occupied_set = set(occupied)
    for slot in range(start_slot, start_slot + session.duration):
        if slot in occupied_set:
            return False
    return True


def check_ta_clash(
    session: Session,
    day: str,
    start_slot: int,
    state: StateIndex,
) -> bool:
    """TA must have no other tutorial in any of the slots [start, end)."""
    if session.ta_id is None:
        return True
    occupied = state.ta_day_slots.get((session.ta_id, day), [])
    occupied_set = set(occupied)
    for slot in range(start_slot, start_slot + session.duration):
        if slot in occupied_set:
            return False
    return True


def check_room_clash(
    room: RoomInfo,
    day: str,
    start_slot: int,
    duration: int,
    state: StateIndex,
) -> bool:
    """Room must be unoccupied in all slots [start, start+duration)."""
    occupied = state.room_day_slots.get((room.id, day), [])
    occupied_set = set(occupied)
    for slot in range(start_slot, start_slot + duration):
        if slot in occupied_set:
            return False
    return True


def check_student_daily_load(
    session: Session,
    day: str,
    state: StateIndex,
) -> bool:
    """
    Section must not exceed STUDENT_DAILY_MAX (6) hours on this day
    after adding this session's duration.
    """
    current = len(state.section_day_slots.get((session.section_id, day), []))
    return (current + session.duration) <= STUDENT_DAILY_MAX


def check_faculty_daily_load(
    session: Session,
    day: str,
    state: StateIndex,
) -> bool:
    """
    Faculty must not exceed FACULTY_DAILY_MAX (4) hours on this day
    after adding this session's duration.
    """
    current = len(state.faculty_day_slots.get((session.faculty_id, day), []))
    return (current + session.duration) <= FACULTY_DAILY_MAX


def check_ta_daily_load(
    session: Session,
    day: str,
    state: StateIndex,
) -> bool:
    """
    TA must not exceed TA_DAILY_MAX (3) hours on this day
    after adding this session's duration.
    """
    if session.ta_id is None:
        return True
    current = len(state.ta_day_slots.get((session.ta_id, day), []))
    return (current + session.duration) <= TA_DAILY_MAX


def check_lecture_day_spread(
    session: Session,
    day: str,
    state: StateIndex,
) -> bool:
    """
    LECTURE sessions: the same course+section must not have another lecture
    on this day already.  Spreads lectures across different days.
    """
    if session.session_type != "LECTURE":
        return True
    days_used = state.lecture_days.get((session.section_id, session.course_id), set())
    return day not in days_used


def check_midday_break(
    session: Session,
    day: str,
    start_slot: int,
    state: StateIndex,
) -> bool:
    """
    After adding this session, the section must still have at least one free
    1-hour slot in LUNCH_SLOTS (hours 12, 13, 14) on this day.

    This implements the midday break hard constraint (§8, PROJECT_CONTEXT.md).

    If the section has no sessions on this day yet (before this one), and
    the proposed session doesn't occupy all of LUNCH_SLOTS, the constraint
    is satisfied.

    The section is considered to "have classes today" once any session is
    assigned (including the candidate being evaluated).
    """
    # Determine which LUNCH_SLOTS this candidate session would occupy
    new_slots = set(range(start_slot, start_slot + session.duration))

    # Existing section slots for today
    existing = set(state.section_day_slots.get((session.section_id, day), []))

    # All section slots after this assignment
    all_slots = existing | new_slots

    # Check if at least one lunch slot remains free
    for lunch_slot in LUNCH_SLOTS:
        if lunch_slot not in all_slots:
            return True  # at least one break available

    # All lunch slots would be occupied
    return False


def check_lab_consecutive(
    session: Session,
    day: str,
    start_slot: int,
    state: StateIndex,
) -> bool:
    """
    Lab sessions must:
      1. Fit within [SLOT_START, SLOT_END+1) — handled before calling this.
      2. Not overlap the section's midday break hour on this day.
         The midday break is whichever of {12, 13, 14} is still free for
         this section on this day.

    We determine the "chosen" break hour as the first free LUNCH_SLOT for
    the section on this day (after existing assignments).  Then we check
    that the lab does not occupy that slot.

    If no LUNCH_SLOT is already committed as free, we use the midday_break
    check above to verify at least one is preserved.  This function only
    checks the specific no-overlap rule.
    """
    if session.session_type != "LAB":
        return True

    lab_slots = set(range(start_slot, start_slot + session.duration))
    existing = set(state.section_day_slots.get((session.section_id, day), []))

    # Find the free LUNCH_SLOT(s) after including existing (but before this lab)
    free_lunch = LUNCH_SLOTS - existing

    if not free_lunch:
        # No lunch slot is currently free — midday_break check will fail; skip here
        return True  # let midday_break check handle it

    # Check if the lab occupies any of the (still-free) lunch slots
    # It's allowed to occupy a lunch slot only if another lunch slot remains free
    after_lab = existing | lab_slots
    remaining_lunch = LUNCH_SLOTS - after_lab

    if not remaining_lunch:
        # Lab would consume the last free lunch slot
        return False

    return True


def get_section_free_lunch_slot(
    section_id: uuid.UUID,
    day: str,
    state: StateIndex,
) -> Optional[int]:
    """
    Return the first free LUNCH_SLOT for a section on a given day,
    or None if all lunch slots are occupied.

    Utility used by conflict.py to explain why a session failed.
    """
    occupied = set(state.section_day_slots.get((section_id, day), []))
    for slot in sorted(LUNCH_SLOTS):
        if slot not in occupied:
            return slot
    return None
