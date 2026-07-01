"""
Room model — physical spaces available for scheduling.

Design decisions:
- Only two room types exist: LECTURE_HALL and LAB.
  LECTURE_HALL serves lectures and tutorials.
  LAB serves lab sessions exclusively.
  This maps exactly to SessionType in timetable_entries.
- `capacity` is compared against `section.strength` during best-fit
  room allocation in the scheduler.
- No availability columns: the system explicitly does NOT support room
  blocked slots (all rooms are available 8 AM–6 PM, Mon–Fri).
- No semester scoping: rooms exist permanently.
- The compound index (room_type, capacity) serves the scheduler's
  best-fit search: filter by type, order by capacity ASC, pick the
  smallest room that fits.
"""

from sqlalchemy import CheckConstraint, Enum, Index, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import UUIDPrimaryKeyMixin
from app.models.enums import RoomType


class Room(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "rooms"

    # ── Core fields ──────────────────────────────────────────────────
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    room_type: Mapped[RoomType] = mapped_column(
        Enum(RoomType, name="room_type", create_constraint=True),
        nullable=False,
    )
    # Maximum number of students the room can accommodate
    capacity: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
    )

    # ── Constraints & indexes ─────────────────────────────────────────
    __table_args__ = (
        UniqueConstraint("name", name="uq_rooms_name"),
        CheckConstraint("capacity > 0", name="ck_rooms_capacity_positive"),
        # Composite index for the scheduler's best-fit query:
        # WHERE room_type = :type ORDER BY capacity ASC
        Index("idx_rooms_type_capacity", "room_type", "capacity"),
    )

    # ── Relationships ─────────────────────────────────────────────────
    timetable_entries: Mapped[list["TimetableEntry"]] = relationship(
        "TimetableEntry",
        back_populates="room",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Room {self.name!r} {self.room_type.value} cap={self.capacity}>"
