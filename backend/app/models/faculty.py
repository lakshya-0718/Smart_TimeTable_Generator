"""
Faculty model + FacultyPreference model.

Faculty constraints are the trickiest part of academic scheduling:
- A faculty member can teach multiple courses across sections.
- They have time-slot preferences (preferred / available / unavailable).
- max_hours_per_day caps daily load to prevent burnout.
- The preference table is a separate entity because preferences are
  per (faculty, day, slot_number) — a many-to-many-style relation.
"""

import uuid

from sqlalchemy import (
    CheckConstraint,
    Enum,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import UUIDPrimaryKeyMixin
from app.models.enums import DayOfWeek, PreferenceLevel


class Faculty(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "faculty"

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    employee_id: Mapped[str] = mapped_column(
        String(20), unique=True, nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False
    )
    department_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("departments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    max_hours_per_day: Mapped[int] = mapped_column(
        SmallInteger,
        default=6,
        nullable=False,
    )
    max_hours_per_week: Mapped[int] = mapped_column(
        SmallInteger,
        default=25,
        nullable=False,
    )

    # ── Constraints ──────────────────────────────────────────────────
    __table_args__ = (
        CheckConstraint(
            "max_hours_per_day > 0 AND max_hours_per_day <= 8",
            name="ck_faculty_daily_hours",
        ),
        CheckConstraint(
            "max_hours_per_week > 0 AND max_hours_per_week <= 40",
            name="ck_faculty_weekly_hours",
        ),
    )

    # ── Relationships ────────────────────────────────────────────────
    department = relationship("Department", back_populates="faculty_members")
    preferences = relationship(
        "FacultyPreference",
        back_populates="faculty",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    course_assignments = relationship(
        "CourseAssignment",
        back_populates="faculty",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Faculty {self.employee_id} — {self.name}>"


class FacultyPreference(UUIDPrimaryKeyMixin, Base):
    """
    Encodes per-slot preferences for a faculty member.

    Example: Dr. Sharma prefers NOT to teach on Monday slots 1-2
    → two rows with level=UNAVAILABLE.

    The engine treats UNAVAILABLE as a hard constraint and
    PREFERRED as a soft bonus during the optimization pass.
    """

    __tablename__ = "faculty_preferences"

    faculty_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("faculty.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    day: Mapped[DayOfWeek] = mapped_column(
        Enum(DayOfWeek, name="day_of_week", create_constraint=True),
        nullable=False,
    )
    slot_number: Mapped[int] = mapped_column(
        SmallInteger, nullable=False
    )
    level: Mapped[PreferenceLevel] = mapped_column(
        Enum(PreferenceLevel, name="preference_level", create_constraint=True),
        default=PreferenceLevel.AVAILABLE,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "faculty_id", "day", "slot_number",
            name="uq_faculty_day_slot",
        ),
        CheckConstraint(
            "slot_number > 0 AND slot_number <= 8",
            name="ck_preference_slot_range",
        ),
    )

    faculty = relationship("Faculty", back_populates="preferences")

    def __repr__(self) -> str:
        return f"<Preference faculty={self.faculty_id} {self.day.value} S{self.slot_number} → {self.level.value}>"
