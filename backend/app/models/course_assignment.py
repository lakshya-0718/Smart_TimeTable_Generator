"""
CourseAssignment model — the central scheduling atom.

A CourseAssignment binds: Course × Section × Faculty (× TA).
This is the object the scheduler engine works with directly.  It never
needs to look up course/section/faculty/TA separately — all the
information it needs is encoded in this single row.

The engine's context.py reads every CourseAssignment for a semester and
expands each into individual Session objects:
  TIER_1 → Lecture×3 + Tutorial×1 + Lab×1 (3 slots)
  TIER_2 → Lecture×3 + Tutorial×1
  TIER_3 → Lab×1 (4 slots)
  TIER_4 → Lab×1 (2 slots)

Design decisions:
- `ta_id` is nullable: Tier 3 and Tier 4 are lab-only with no tutorial
  and therefore no TA.  The service layer enforces that Tier 1/2
  assignments must supply a ta_id.
- FK on `section_id` and `faculty_id` uses ON DELETE RESTRICT: the admin
  must remove assignments before removing the section or faculty member.
  This prevents orphaned assignments.
- FK on `ta_id` uses ON DELETE SET NULL: a TA can be deactivated without
  deleting the whole assignment — the admin can then reassign a new TA.
- FK on `course_id` uses ON DELETE CASCADE: deleting a course (via
  semester cascade or directly) removes all its assignments cleanly.
- Unique constraint (course_id, section_id): a course can be assigned to
  a section only once per semester.  Y2A and Y2B both have DSA — two rows
  with different section_ids.

Two separate FKs to `users` (faculty_id, ta_id) require explicit
`foreign_keys` on all User → CourseAssignment relationships to avoid
SQLAlchemy's ambiguous FK warning.
"""

import uuid

from sqlalchemy import ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import UUIDPrimaryKeyMixin


class CourseAssignment(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "course_assignments"

    # ── Foreign keys ──────────────────────────────────────────────────
    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
    )
    section_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sections.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # The professor who teaches lectures (and labs for Tier 1)
    faculty_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # The TA who teaches tutorials — nullable for Tier 3/4 (lab-only)
    ta_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── Constraints & indexes ─────────────────────────────────────────
    __table_args__ = (
        # One course may be assigned to one section at most once per semester
        UniqueConstraint(
            "course_id", "section_id",
            name="uq_course_assignments_course_section",
        ),
        # "Show all courses for this section"
        Index("idx_ca_course_id", "course_id"),
        Index("idx_ca_section_id", "section_id"),
        # "Show all assignments for this faculty member"
        Index("idx_ca_faculty_id", "faculty_id"),
        # "Show all tutorial assignments for this TA"
        Index("idx_ca_ta_id", "ta_id"),
    )

    # ── Relationships ─────────────────────────────────────────────────
    course: Mapped["Course"] = relationship(
        "Course",
        back_populates="assignments",
    )
    section: Mapped["Section"] = relationship(
        "Section",
        back_populates="course_assignments",
    )
    faculty: Mapped["User"] = relationship(
        "User",
        foreign_keys=[faculty_id],
        back_populates="faculty_assignments",
    )
    ta: Mapped["User | None"] = relationship(
        "User",
        foreign_keys=[ta_id],
        back_populates="ta_assignments",
    )
    timetable_entries: Mapped[list["TimetableEntry"]] = relationship(
        "TimetableEntry",
        back_populates="assignment",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<CourseAssignment course={self.course_id} "
            f"section={self.section_id} "
            f"faculty={self.faculty_id} "
            f"ta={self.ta_id}>"
        )
