"""
Enums for the Smart Academic Timetable Generator.

All enums are str-based so that SQLAlchemy serialises them as the
string value directly into PostgreSQL ENUM columns, and Pydantic
schemas can validate them from JSON without an extra conversion step.

Each enum maps 1-to-1 with a PostgreSQL ENUM type that Alembic will
create.  The `name` argument on SQLAlchemy's Enum() must match the
name used in __table_args__ across all models.
"""

import enum


class UserRole(str, enum.Enum):
    """
    Discriminates the three actor types that share the `users` table.

    ADMIN   — full CRUD over all resources, generates timetable.
    FACULTY — marks own unavailability, views timetable.
    TA      — marks own unavailability, views assigned tutorials.
    """

    ADMIN = "ADMIN"
    FACULTY = "FACULTY"
    TA = "TA"


class CourseTier(str, enum.Enum):
    """
    Encodes the L-T-P pattern for a course.

    TIER_1 → 4-credit: 3 lectures + 1 tutorial + 1 lab (3 slots)
    TIER_2 → 3-credit: 3 lectures + 1 tutorial
    TIER_3 → 2-credit lab-only: 1 lab (4 consecutive slots)
    TIER_4 → 1-credit lab-only: 1 lab (2 consecutive slots)

    The scheduler's context.py uses this enum to expand each
    CourseAssignment into the correct set of Session objects.
    """

    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"
    TIER_4 = "TIER_4"


class RoomType(str, enum.Enum):
    """
    Physical room classification.

    LECTURE_HALL — used for lectures and tutorials.
    LAB          — used exclusively for lab sessions.

    This is the only criterion (besides capacity) the scheduler uses
    when matching a room to a session.
    """

    LECTURE_HALL = "LECTURE_HALL"
    LAB = "LAB"


class SessionType(str, enum.Enum):
    """
    The type of a single schedulable session within a course.

    LECTURE  — 1 slot, taught by faculty, held in LECTURE_HALL.
    TUTORIAL — 1 slot, taught by TA, held in LECTURE_HALL.
    LAB      — 2/3/4 consecutive slots, taught by faculty, held in LAB.
    """

    LECTURE = "LECTURE"
    TUTORIAL = "TUTORIAL"
    LAB = "LAB"


class DayOfWeek(str, enum.Enum):
    """
    Working days only — Monday to Friday.

    Stored as short uppercase strings to match the scheduler engine's
    internal Slot.day field directly, eliminating any conversion layer.
    """

    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"


class TimetableStatus(str, enum.Enum):
    """
    Lifecycle status of a generated timetable.

    ACTIVE   — the current timetable for the semester (displayed to all users).
    SNAPSHOT — the immediately previous timetable, retained as a single
               rollback point. Deleted when a new generation occurs.

    At most 2 timetables exist per semester at any time.
    """

    ACTIVE = "ACTIVE"
    SNAPSHOT = "SNAPSHOT"
