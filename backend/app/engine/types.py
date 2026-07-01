"""
engine/types.py — Core dataclasses and constants for the scheduler engine.

All types in this file are pure Python dataclasses.  No SQLAlchemy, no
FastAPI, no database access.  The engine is deliberately kept database-free
so it can be tested independently and run in a thread pool executor.

Type hierarchy:
  SchedulingContext  — everything the engine needs, built by context.py
    ├── list[Session]            — the schedulable units
    ├── list[RoomInfo]           — rooms available for assignment
    ├── dict[UUID, SectionInfo]  — section strength + name lookup
    ├── dict[UUID, set[...]]     — faculty unavailable slots (blacklist)
    └── dict[UUID, set[...]]     — TA unavailable slots (blacklist)

  SchedulingResult   — what the engine returns, consumed by timetable_service.py
    ├── list[SlotAssignment]     — successfully scheduled sessions
    ├── list[UnscheduledSession] — sessions that could not be placed
    └── list[str]                — pre-generation warnings

Constants:
  DAYS            — ordered working days (MON ... FRI)
  SLOT_START      — first schedulable hour (8)
  SLOT_END        — last start hour (17), so slots are 8-9 ... 17-18
  LUNCH_SLOTS     — hours that count as potential midday breaks (12, 13, 14)
  MAX_BT_DEPTH    — maximum backtracking depth before giving up
  SESSION_ROOM_TYPE — maps SessionType string -> required RoomType string
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

# ── Day ordering ─────────────────────────────────────────────────────────────
DAYS: list[str] = ["MON", "TUE", "WED", "THU", "FRI"]

# ── Time window ───────────────────────────────────────────────────────────────
SLOT_START: int = 8   # 8:00 AM
SLOT_END: int = 17    # last valid start hour (slot covers 17:00-18:00)

# ── Midday break window: at least one of these hours must remain free per
# section per day that has classes (hard constraint §8, PROJECT_CONTEXT.md)
LUNCH_SLOTS: frozenset[int] = frozenset({12, 13, 14})

# ── Backtracking limit: max sessions to unassign before giving up ─────────────
MAX_BT_DEPTH: int = 3

# ── Maps session type string -> room type string ──────────────────────────────
SESSION_ROOM_TYPE: dict[str, str] = {
    "LECTURE":  "LECTURE_HALL",
    "TUTORIAL": "LECTURE_HALL",
    "LAB":      "LAB",
}

# ── Daily load caps (hours/slots) ─────────────────────────────────────────────
STUDENT_DAILY_MAX: int = 6
FACULTY_DAILY_MAX: int = 4
TA_DAILY_MAX: int = 6

# ── Reason codes for conflict report ─────────────────────────────────────────
class ReasonCode:
    NO_VALID_SLOT       = "NO_VALID_SLOT"        # no (day, slot) passed all checks
    NO_VALID_ROOM       = "NO_VALID_ROOM"        # no room of right type + capacity
    FACULTY_CLASH       = "FACULTY_CLASH"        # faculty already booked
    SECTION_CLASH       = "SECTION_CLASH"        # section already has a session
    TA_CLASH            = "TA_CLASH"             # TA already booked
    ROOM_CLASH          = "ROOM_CLASH"           # room already taken
    ROOM_CAPACITY       = "ROOM_CAPACITY"        # no room with sufficient capacity
    STUDENT_DAILY_LOAD  = "STUDENT_DAILY_LOAD"   # section would exceed 6h/day
    FACULTY_DAILY_LOAD  = "FACULTY_DAILY_LOAD"   # faculty would exceed 4h/day
    TA_DAILY_LOAD       = "TA_DAILY_LOAD"        # TA would exceed 3h/day
    LECTURE_SAME_DAY    = "LECTURE_SAME_DAY"     # two lectures of same course on same day
    MIDDAY_BREAK        = "MIDDAY_BREAK"         # section would have no midday break
    LAB_CONSECUTIVE     = "LAB_CONSECUTIVE"      # lab cannot fit without crossing lunch
    FACULTY_UNAVAILABLE = "FACULTY_UNAVAILABLE"  # faculty marked slot unavailable
    TA_UNAVAILABLE      = "TA_UNAVAILABLE"       # TA marked slot unavailable
    BACKTRACK_EXHAUSTED = "BACKTRACK_EXHAUSTED"  # backtracking limit reached


# ═════════════════════════════════════════════════════════════════════════════
# Domain dataclasses — used inside SchedulingContext
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class RoomInfo:
    """
    A physical room available for scheduling.

    Attributes:
        id:         UUID from the rooms table.
        name:       Human-readable room name (e.g. "LH-101").
        room_type:  "LECTURE_HALL" or "LAB".
        capacity:   Maximum students the room can hold.
    """
    id: uuid.UUID
    name: str
    room_type: str   # "LECTURE_HALL" | "LAB"
    capacity: int


@dataclass
class SectionInfo:
    """
    A student group (e.g. Y2A) with its strength.

    Attributes:
        id:       UUID from the sections table.
        name:     "Y1A" ... "Y4B".
        strength: Number of enrolled students (used for room capacity check).
    """
    id: uuid.UUID
    name: str
    strength: int


@dataclass
class Session:
    """
    The atomic schedulable unit produced by context.py from a CourseAssignment.

    One CourseAssignment expands into 1-5 Sessions depending on tier:
      TIER_1 -> Lecture x3, Tutorial x1, Lab x1  (lab_duration=3)
      TIER_2 -> Lecture x3, Tutorial x1
      TIER_3 -> Lab x1                            (lab_duration=4)
      TIER_4 -> Lab x1                            (lab_duration=2)

    Attributes:
        id:               Unique string within the engine run
                          (e.g. "<assignment_uuid>-LECTURE-0").
        assignment_id:    UUID of the parent CourseAssignment row.
        course_id:        UUID of the Course.
        course_name:      Display name (e.g. "Data Structures").
        course_code:      Short code (e.g. "CS301").
        section_id:       UUID of the Section.
        section_name:     Display name (e.g. "Y2A").
        session_type:     "LECTURE" | "TUTORIAL" | "LAB".
        duration:         Number of consecutive 1-hour slots (1, 2, 3, or 4).
        faculty_id:       UUID of the faculty member (teaches lectures + labs).
        ta_id:            UUID of the TA (teaches tutorials); None otherwise.
        tier:             "TIER_1" | "TIER_2" | "TIER_3" | "TIER_4".
        section_strength: Cached from SectionInfo for fast capacity checks.
    """
    id: str
    assignment_id: uuid.UUID
    course_id: uuid.UUID
    course_name: str
    course_code: str
    section_id: uuid.UUID
    section_name: str
    session_type: str      # "LECTURE" | "TUTORIAL" | "LAB"
    duration: int          # consecutive slots this session occupies
    faculty_id: uuid.UUID
    ta_id: Optional[uuid.UUID]
    tier: str
    section_strength: int


@dataclass
class SlotAssignment:
    """
    A successfully scheduled session.  This is what timetable_service.py
    reads to build TimetableEntry rows.

    Attributes:
        assignment_id:  Parent CourseAssignment UUID.
        session_type:   "LECTURE" | "TUTORIAL" | "LAB".
        day:            "MON" | "TUE" | "WED" | "THU" | "FRI".
        start_slot:     Integer hour (8-17).
        end_slot:       start_slot + duration  (9-18).
        room_id:        UUID of the assigned room.
        section_id:     UUID of the section (denormalized for timetable_entries).
        faculty_id:     UUID of the faculty member (denormalized).
        ta_id:          UUID of the TA, or None.
    """
    assignment_id: uuid.UUID
    session_type: str
    day: str
    start_slot: int
    end_slot: int
    room_id: uuid.UUID
    section_id: uuid.UUID
    faculty_id: uuid.UUID
    ta_id: Optional[uuid.UUID]


@dataclass
class UnscheduledSession:
    """
    A session the scheduler could not place in any valid (day, slot, room).

    Attributes:
        assignment_id:        Parent CourseAssignment UUID.
        course_code:          e.g. "CS301".
        course_name:          e.g. "Data Structures".
        section:              Section name e.g. "Y2A".
        session_type:         "LECTURE" | "TUTORIAL" | "LAB".
        reason_code:          Primary reason from ReasonCode constants.
        reason_detail:        Human-readable explanation.
        blocking_constraints: All constraint names that were hit during search.
    """
    assignment_id: uuid.UUID
    course_code: str
    course_name: str
    section: str
    session_type: str
    reason_code: str
    reason_detail: str
    blocking_constraints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to a plain dict for JSONB storage in ConflictReport."""
        return {
            "assignment_id":        str(self.assignment_id),
            "course_code":          self.course_code,
            "course_name":          self.course_name,
            "section":              self.section,
            "session_type":         self.session_type,
            "reason_code":          self.reason_code,
            "reason_detail":        self.reason_detail,
            "blocking_constraints": list(self.blocking_constraints),
        }


# ═════════════════════════════════════════════════════════════════════════════
# Primary I/O types for the engine
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class SchedulingContext:
    """
    Everything the engine needs to schedule a timetable.

    Built by context.py from DB-loaded data.  Passed directly to
    run_scheduler() and pre_validator.run_pre_validation().

    Attributes:
        semester_id:
            The semester being scheduled.
        sessions:
            Flat list of all Session objects to schedule.  Ordered by
            scheduler.py before processing begins.
        rooms:
            All rooms, sorted by (room_type, capacity ASC) so that the
            best-fit search can be done linearly.
        sections:
            UUID -> SectionInfo mapping for O(1) strength lookups.
        faculty_unavailable:
            faculty_id -> set of (day_str, slot_hour) tuples that are
            blocked.  Loaded from faculty_availability table.
        ta_unavailable:
            ta_id -> set of (day_str, slot_hour) tuples that are blocked.
            Loaded from ta_availability table.
    """
    semester_id: uuid.UUID
    sessions: list[Session]
    rooms: list[RoomInfo]
    sections: dict[uuid.UUID, SectionInfo]
    faculty_unavailable: dict[uuid.UUID, set[tuple[str, int]]]
    ta_unavailable: dict[uuid.UUID, set[tuple[str, int]]]


@dataclass
class SchedulingResult:
    """
    Output of run_scheduler().  Consumed by timetable_service.py to build
    TimetableEntry rows and the ConflictReport.

    Attributes:
        assignments:  Sessions that were successfully placed.
        unscheduled:  Sessions that failed placement (partial timetable).
        warnings:     Pre-generation feasibility warnings (non-blocking).
    """
    assignments: list[SlotAssignment] = field(default_factory=list)
    unscheduled: list[UnscheduledSession] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
