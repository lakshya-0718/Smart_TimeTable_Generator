"""
Course model — semester-scoped course catalogue.

A Course represents a subject offered in a specific semester.
Courses vary per semester (different offerings, different faculty
assignments), so they carry a semester_id FK.

Design decisions:
- `tier` encodes the full L-T-P structure as a single enum:
    TIER_1 → 4-credit  (3L + 1T + 1Lab-3slot)
    TIER_2 → 3-credit  (3L + 1T)
    TIER_3 → 2-credit  (1Lab-4slot, lab-only)
    TIER_4 → 1-credit  (1Lab-2slot, lab-only)
  The scheduler's context.py reads this to expand each CourseAssignment
  into the correct session objects without additional per-course config.
- `code` (e.g. "MA201") is separate from `name` (e.g. "Discrete Math")
  because both are displayed in the export CSV and the timetable grid.
- Unique constraint (semester_id, code): the same code cannot appear
  twice in the same semester.  Different semesters may reuse codes.
- ON DELETE CASCADE from semester: deleting a semester removes all its
  courses, which cascades to course_assignments and timetable_entries.
"""

import uuid

from sqlalchemy import Enum, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import UUIDPrimaryKeyMixin
from app.models.enums import CourseTier


class Course(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "courses"

    # ── Core fields ──────────────────────────────────────────────────
    semester_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("semesters.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Full course name, e.g. "Data Structures and Algorithms"
    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    # Short course code, e.g. "CS301"
    code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    # L-T-P tier — drives session expansion in context.py
    tier: Mapped[CourseTier] = mapped_column(
        Enum(CourseTier, name="course_tier", create_constraint=True),
        nullable=False,
    )

    # ── Constraints & indexes ─────────────────────────────────────────
    __table_args__ = (
        # Same course code cannot appear twice in the same semester
        UniqueConstraint("semester_id", "code", name="uq_courses_semester_code"),
        # Hot path: load all courses for a semester (used on every scheduler run)
        Index("idx_courses_semester_id", "semester_id"),
        # Used when sorting courses by scheduling priority (Tier 1 first)
        Index("idx_courses_tier", "tier"),
    )

    # ── Relationships ─────────────────────────────────────────────────
    semester: Mapped["Semester"] = relationship(
        "Semester",
        back_populates="courses",
    )
    assignments: Mapped[list["CourseAssignment"]] = relationship(
        "CourseAssignment",
        back_populates="course",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Course {self.code} tier={self.tier.value}>"
