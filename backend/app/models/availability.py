"""
Availability models — faculty and TA blocked time slots.

FacultyAvailability and TAAvailability are structurally identical but
kept as separate tables for three reasons:
1. Independent index cardinality — faculty and TA sets are always
   queried separately (never JOINed together).
2. Role clarity — the service layer that loads faculty availability
   never accidentally reads TA availability.
3. Future flexibility — TA daily load cap (3h) differs from faculty (4h);
   the separate table makes this boundary visible and explicit.

Schema design:
- Each row is ONE blocked slot: (user_id, day, slot_hour).
- `slot_hour` is an integer from 8 to 17 representing the start of a
  1-hour slot (8 = 8:00–9:00, 17 = 17:00–18:00).  This matches the
  engine's Slot.start_hour field directly — no conversion needed.
- Rows are never updated in-place.  Replace semantics: the service
  deletes all rows for a user and re-inserts the new set.  Therefore
  only `created_at` is needed (no `updated_at`).
- ON DELETE CASCADE from users: deleting a user purges their
  availability automatically.
- The composite unique constraint (user_id, day, slot_hour) prevents
  double-marking and is also the hot-path index for the scheduler's
  O(1) availability check.
"""

import uuid

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, SmallInteger, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import UUIDPKCreatedAtMixin
from app.models.enums import DayOfWeek


class FacultyAvailability(UUIDPKCreatedAtMixin, Base):
    """
    Blacklist of (faculty, day, hour) triples where the faculty
    member has marked themselves unavailable.

    The scheduler's validator.py checks this set for every candidate
    slot before making an assignment.  Unavailable = hard constraint.
    """

    __tablename__ = "faculty_availability"

    # FK to users (role=FACULTY — enforced at service layer, not DB)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    day: Mapped[DayOfWeek] = mapped_column(
        Enum(DayOfWeek, name="day_of_week", create_constraint=True),
        nullable=False,
    )
    # Integer hour: 8 = 8:00–9:00, ..., 17 = 17:00–18:00
    slot_hour: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
    )

    # ── Constraints & indexes ─────────────────────────────────────────
    __table_args__ = (
        CheckConstraint(
            "slot_hour BETWEEN 8 AND 17",
            name="ck_faculty_avail_slot_hour_range",
        ),
        # Prevents double-marking; also serves as the hot-path index
        UniqueConstraint(
            "user_id", "day", "slot_hour",
            name="uq_faculty_avail_user_day_slot",
        ),
        # Single-column index for "load all unavailable slots for user X"
        Index("idx_faculty_avail_user_id", "user_id"),
        # Composite index for O(1) validator lookup: (user_id, day, slot_hour)
        Index("idx_faculty_avail_lookup", "user_id", "day", "slot_hour"),
    )

    # ── Relationships ─────────────────────────────────────────────────
    user: Mapped["User"] = relationship(
        "User",
        back_populates="faculty_availability",
    )

    def __repr__(self) -> str:
        return (
            f"<FacultyAvailability user={self.user_id} "
            f"{self.day.value} slot={self.slot_hour}>"
        )


class TAAvailability(UUIDPKCreatedAtMixin, Base):
    """
    Blacklist of (TA, day, hour) triples where the TA has marked
    themselves unavailable.  Structurally identical to FacultyAvailability
    but kept separate for index cardinality and role clarity.
    """

    __tablename__ = "ta_availability"

    # FK to users (role=TA — enforced at service layer, not DB)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    day: Mapped[DayOfWeek] = mapped_column(
        # Reuse the same PostgreSQL ENUM type created for FacultyAvailability
        Enum(DayOfWeek, name="day_of_week", create_constraint=False),
        nullable=False,
    )
    slot_hour: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
    )

    # ── Constraints & indexes ─────────────────────────────────────────
    __table_args__ = (
        CheckConstraint(
            "slot_hour BETWEEN 8 AND 17",
            name="ck_ta_avail_slot_hour_range",
        ),
        UniqueConstraint(
            "user_id", "day", "slot_hour",
            name="uq_ta_avail_user_day_slot",
        ),
        Index("idx_ta_avail_user_id", "user_id"),
        Index("idx_ta_avail_lookup", "user_id", "day", "slot_hour"),
    )

    # ── Relationships ─────────────────────────────────────────────────
    user: Mapped["User"] = relationship(
        "User",
        back_populates="ta_availability",
    )

    def __repr__(self) -> str:
        return (
            f"<TAAvailability user={self.user_id} "
            f"{self.day.value} slot={self.slot_hour}>"
        )
