"""
engine/conflict.py — Conflict report builder.

Takes the list of sessions that failed to be scheduled and the violation
codes collected during the scheduling attempt, and produces a list of
UnscheduledSession objects ready to be stored as JSONB in ConflictReport.

Design (per system_architecture.md §4 Step 7):
  For each UNSCHEDULED session:
    1. Look at all violation codes collected during its search.
    2. Pick the PRIMARY reason: the most frequently occurring code.
    3. Generate a human-readable reason_detail string.
    4. Return an UnscheduledSession dataclass.

The summary is deliberately simple:
  - We don't replay every (day, slot, room) combination here — that was
    already done during scheduling.
  - Instead we use the accumulated violation list from the scheduler.
  - The most frequent violation code = the "dominant" blocking reason.

Primary reason selection:
  Frequency wins.  If FACULTY_CLASH appears 15 times and NO_VALID_ROOM
  appears 3 times, the primary reason is FACULTY_CLASH.
  On tie, the code that appears first in CONSTRAINT_PRIORITY order wins.

Entry point:
    unscheduled = build_conflict_report(failed_sessions, conflict_details)
"""

from __future__ import annotations

from collections import Counter

from app.engine.types import (
    ReasonCode,
    Session,
    UnscheduledSession,
)

# Priority order when resolving ties in frequency (most informative first)
CONSTRAINT_PRIORITY: list[str] = [
    ReasonCode.NO_VALID_ROOM,
    ReasonCode.ROOM_CAPACITY,
    ReasonCode.FACULTY_UNAVAILABLE,
    ReasonCode.TA_UNAVAILABLE,
    ReasonCode.FACULTY_CLASH,
    ReasonCode.SECTION_CLASH,
    ReasonCode.TA_CLASH,
    ReasonCode.ROOM_CLASH,
    ReasonCode.STUDENT_DAILY_LOAD,
    ReasonCode.FACULTY_DAILY_LOAD,
    ReasonCode.TA_DAILY_LOAD,
    ReasonCode.LECTURE_SAME_DAY,
    ReasonCode.MIDDAY_BREAK,
    ReasonCode.LAB_CONSECUTIVE,
    ReasonCode.NO_VALID_SLOT,
    ReasonCode.BACKTRACK_EXHAUSTED,
]

# Human-readable templates for each reason code
_REASON_TEMPLATES: dict[str, str] = {
    ReasonCode.NO_VALID_ROOM: (
        "No {room_type} room with capacity >= {strength} is available "
        "in any valid time slot."
    ),
    ReasonCode.ROOM_CAPACITY: (
        "No {room_type} room can accommodate {strength} students in any free slot."
    ),
    ReasonCode.FACULTY_CLASH: (
        "Faculty member has no free slot that does not conflict with another assigned session."
    ),
    ReasonCode.SECTION_CLASH: (
        "Section {section} has no available slot (all valid slots clash with existing sessions)."
    ),
    ReasonCode.TA_CLASH: (
        "The assigned TA has no free slot compatible with remaining options."
    ),
    ReasonCode.ROOM_CLASH: (
        "All suitable rooms are occupied in every remaining valid time slot."
    ),
    ReasonCode.STUDENT_DAILY_LOAD: (
        "Section {section} would exceed the 6-hour daily student load limit in all candidate slots."
    ),
    ReasonCode.FACULTY_DAILY_LOAD: (
        "Faculty would exceed the 4-hour daily teaching load limit in all candidate slots."
    ),
    ReasonCode.TA_DAILY_LOAD: (
        "TA would exceed the 3-hour daily teaching load limit in all candidate slots."
    ),
    ReasonCode.LECTURE_SAME_DAY: (
        "Cannot spread all lectures for {course_code} / {section} across different days "
        "(lecture distribution constraint)."
    ),
    ReasonCode.MIDDAY_BREAK: (
        "Placing this session would eliminate the required midday break for section {section}."
    ),
    ReasonCode.LAB_CONSECUTIVE: (
        "No consecutive {duration}-hour block is available without overlapping "
        "the midday break for section {section}."
    ),
    ReasonCode.FACULTY_UNAVAILABLE: (
        "Faculty has marked all candidate slots as unavailable."
    ),
    ReasonCode.TA_UNAVAILABLE: (
        "The assigned TA has marked all candidate slots as unavailable."
    ),
    ReasonCode.NO_VALID_SLOT: (
        "No valid slot was found after checking all constraints."
    ),
    ReasonCode.BACKTRACK_EXHAUSTED: (
        "Backtracking limit reached. Could not resolve conflicts with neighbouring sessions."
    ),
}


def build_conflict_report(
    failed_sessions: list[Session],
    conflict_details: dict[str, list[str]],
) -> list[UnscheduledSession]:
    """
    Build UnscheduledSession objects for every failed session.

    Args:
        failed_sessions:  Sessions that could not be placed.
        conflict_details: Maps session.id -> list of ReasonCode strings
                          accumulated during the scheduling attempt.

    Returns:
        List of UnscheduledSession dataclasses, ready for JSONB storage.
    """
    result: list[UnscheduledSession] = []

    for session in failed_sessions:
        violations = conflict_details.get(session.id, [])
        primary_reason = _pick_primary_reason(violations)
        reason_detail = _build_detail(primary_reason, session)

        # Deduplicated list of all constraint codes hit (preserves insertion order)
        blocking = list(dict.fromkeys(violations))

        result.append(
            UnscheduledSession(
                assignment_id=session.assignment_id,
                course_code=session.course_code,
                course_name=session.course_name,
                section=session.section_name,
                session_type=session.session_type,
                reason_code=primary_reason,
                reason_detail=reason_detail,
                blocking_constraints=blocking,
            )
        )

    return result


# ── Internal helpers ──────────────────────────────────────────────────────────

def _pick_primary_reason(violations: list[str]) -> str:
    """
    Select the primary blocking reason from a list of violation codes.

    Strategy:
      1. Count frequencies.
      2. Find the maximum frequency.
      3. Among all codes with that frequency, pick the one earliest in
         CONSTRAINT_PRIORITY (most informative / actionable).
      4. Fall back to NO_VALID_SLOT if the list is empty.
    """
    if not violations:
        return ReasonCode.NO_VALID_SLOT

    counts = Counter(violations)
    max_freq = max(counts.values())

    # All codes tied for highest frequency
    top_codes = {code for code, freq in counts.items() if freq == max_freq}

    # Pick by priority order
    for code in CONSTRAINT_PRIORITY:
        if code in top_codes:
            return code

    # Fallback: any code not in priority list
    return next(iter(top_codes))


def _build_detail(reason_code: str, session: Session) -> str:
    """
    Build a human-readable detail string for the given reason code and session.
    """
    from app.engine.types import SESSION_ROOM_TYPE

    required_room_type = SESSION_ROOM_TYPE.get(session.session_type, "LECTURE_HALL")

    template = _REASON_TEMPLATES.get(
        reason_code,
        "Session could not be scheduled: {reason_code}."
    )

    try:
        detail = template.format(
            room_type=required_room_type,
            strength=session.section_strength,
            section=session.section_name,
            course_code=session.course_code,
            course_name=session.course_name,
            duration=session.duration,
            reason_code=reason_code,
        )
    except KeyError:
        detail = template

    return detail
