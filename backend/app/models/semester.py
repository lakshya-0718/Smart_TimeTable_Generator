"""
Semester model.

A Semester is the top-level grouping for courses and timetables.
The scheduler always operates on a single selected semester.

Design decisions:
- Courses are semester-scoped (offerings change each term).
- Sections and Rooms are NOT semester-scoped (they persist across terms).
- `is_active` is a UI convenience flag: which semester is the admin
  currently working on.  Only one should be active at a time; this
  invariant is enforced at the service layer (not as a partial unique
  index), since toggling is always an explicit admin action.
- No start_date / end_date: the scheduler works on weekly patterns, not
  calendar dates.  Adding date columns would be unused dead weight.

Cascade: deleting a semester cascades to courses → course_assignments
         → timetable_entries, AND to timetables → timetable_entries +
         conflict_reports.  The full semester data set is a coherent unit.
"""

from sqlalchemy import Boolean, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import UUIDPrimaryKeyMixin


class Semester(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "semesters"

    # ── Core fields ──────────────────────────────────────────────────
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
    )

    # ── Constraints & indexes ─────────────────────────────────────────
    __table_args__ = (
        # No two semesters may share the same name
        UniqueConstraint("name", name="uq_semesters_name"),
        # Fast lookup for "get the active semester" — used constantly
        Index("idx_semesters_is_active", "is_active"),
    )

    # ── Relationships ─────────────────────────────────────────────────
    courses: Mapped[list["Course"]] = relationship(
        "Course",
        back_populates="semester",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    timetables: Mapped[list["Timetable"]] = relationship(
        "Timetable",
        back_populates="semester",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        active = " [ACTIVE]" if self.is_active else ""
        return f"<Semester {self.name!r}{active}>"
