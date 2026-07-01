"""
Section model — permanent student groups (Y1A through Y4B).

Design decisions:
- Sections are NOT semester-scoped.  Y2A is always Y2A; only its
  strength changes each semester.  Tying sections to semesters would
  force the admin to recreate 8 identical rows every term.
- `year` and `label` are stored as separate columns alongside `name`
  so queries like "show all Year 2 sections" filter on `year` without
  string parsing.
- `strength` lives on Section, not on CourseAssignment, because strength
  is a property of the student cohort, not the course pairing.
- The composite unique constraint (year, label) enforces that at most
  two sections exist per year (A and B), matching the 8-section scope.
- ON DELETE RESTRICT on course_assignments.section_id and
  timetable_entries.section_id prevents accidentally removing a section
  that has live data.

No `semester_id` FK — intentional by design.
"""

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import UUIDPrimaryKeyMixin


class Section(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "sections"

    # ── Core fields ──────────────────────────────────────────────────
    # e.g. "Y1A", "Y2B", "Y4A"
    name: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
    )
    # 1 through 4 — the academic year the section belongs to
    year: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
    )
    # 'A' or 'B' — the division letter within the year
    label: Mapped[str] = mapped_column(
        CHAR(1),
        nullable=False,
    )
    # Number of enrolled students — used for room capacity validation
    # and lab batch sizing
    strength: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
    )

    # ── Constraints & indexes ─────────────────────────────────────────
    __table_args__ = (
        # Primary uniqueness: "Y2A" cannot appear twice
        UniqueConstraint("name", name="uq_sections_name"),
        # Structural uniqueness: Year 2 / Section A can only exist once
        UniqueConstraint("year", "label", name="uq_sections_year_label"),
        # Domain checks
        CheckConstraint("year BETWEEN 1 AND 4", name="ck_sections_year_range"),
        CheckConstraint("label IN ('A', 'B')", name="ck_sections_label_values"),
        CheckConstraint("strength > 0", name="ck_sections_strength_positive"),
        # idx_sections_name — used in virtually every JOIN path
        Index("idx_sections_name", "name"),
        # idx_sections_year — used for year-level timetable views
        Index("idx_sections_year", "year"),
    )

    # ── Relationships ─────────────────────────────────────────────────
    course_assignments: Mapped[list["CourseAssignment"]] = relationship(
        "CourseAssignment",
        back_populates="section",
        lazy="selectin",
        # RESTRICT is enforced via FK ondelete; SQLAlchemy cascade is
        # not set here to match that DB-level behaviour
    )
    timetable_entries: Mapped[list["TimetableEntry"]] = relationship(
        "TimetableEntry",
        back_populates="section",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Section {self.name} strength={self.strength}>"
