"""
schemas/room.py — Pydantic models for the Room Management API.

Schema hierarchy:

  Inbound (request bodies):
    RoomCreate — Admin creates a new room.
    RoomUpdate — Admin partially updates room details (PATCH).

  Outbound (response bodies):
    RoomRead   — Public representation of a room record.

Design decisions:

  Why are all three fields updatable via PATCH?
    Unlike sections (where year/label define structural identity),
    room fields have no such immutability constraint:
      - `name` is an admin-assigned label (e.g. "LH-101") that can be
        corrected if entered wrongly.
      - `room_type` could legitimately change if a room is converted from
        a lecture hall to a lab, or vice versa.
      - `capacity` changes whenever physical refurbishment occurs.
    All three are updatable, with name re-checking uniqueness on change.

  Why is RoomType imported from models.enums (not redefined here)?
    The same RoomType enum is used by the Room ORM model, the timetable
    entry model, and potentially the scheduler.  A single definition in
    models/enums.py is the source of truth.  Pydantic automatically
    validates str-based enums from JSON without any conversion step.

  Why no RoomListResponse wrapper?
    The total number of rooms in a university building is small enough
    (typically 20–50) that pagination is not needed.  A flat list with
    an optional room_type query filter is the cleanest API contract.
    If the institution scales to hundreds of rooms, a wrapper can be
    added without breaking clients (wrap the existing list in `items`).

Validation rules:
  - name stripped of whitespace, max 100 chars (mirrors VARCHAR(100))
  - room_type must be RoomType.LECTURE_HALL or RoomType.LAB (enum)
  - capacity must be > 0, ≤ 32767 (mirrors SMALLINT + CHECK constraint)
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.enums import RoomType


# ── Inbound ───────────────────────────────────────────────────────────────────

class RoomCreate(BaseModel):
    """
    Request body for POST /rooms.

    All three fields are required — there is no sensible default for any.

    room_type accepts the string values "LECTURE_HALL" or "LAB" directly
    (Pydantic deserialises them into the RoomType enum automatically
    because RoomType is a str-based enum).
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Room identifier, e.g. 'LH-101', 'Lab-A'. Must be unique.",
        examples=["LH-101"],
    )
    room_type: RoomType = Field(
        ...,
        description="Room classification: LECTURE_HALL (for lectures/tutorials) or LAB (for lab sessions).",
        examples=[RoomType.LECTURE_HALL],
    )
    capacity: int = Field(
        ...,
        gt=0,
        le=32767,   # SMALLINT upper bound
        description="Maximum number of students the room can accommodate. Must be > 0.",
        examples=[60],
    )

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: str) -> str:
        """Strip leading/trailing whitespace so '  LH-101  ' stores as 'LH-101'."""
        return v.strip()


class RoomUpdate(BaseModel):
    """
    Request body for PATCH /rooms/{room_id}.

    All fields are optional.  The service uses model_fields_set to update
    only explicitly-provided fields (PATCH semantics).
    Omitting a field means 'leave it unchanged', not 'set to null'.
    An empty body {} is a valid no-op.

    Updatable fields: name, room_type, capacity.
      - name: updatable with uniqueness re-check if changing.
      - room_type: updatable (e.g. room converted from lecture hall to lab).
      - capacity: updatable (e.g. after physical refurbishment).
    """

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="New room identifier. Must be unique if provided.",
        examples=["LH-102"],
    )
    room_type: RoomType | None = Field(
        default=None,
        description="New room type: LECTURE_HALL or LAB.",
        examples=[RoomType.LAB],
    )
    capacity: int | None = Field(
        default=None,
        gt=0,
        le=32767,
        description="New capacity. Must be > 0.",
        examples=[80],
    )

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.strip()


# ── Outbound ──────────────────────────────────────────────────────────────────

class RoomRead(BaseModel):
    """
    Public representation of a Room record.

    Returned by all room endpoints.

    Fields:
      id        — UUID primary key.
      name      — Room identifier, e.g. 'LH-101'.
      room_type — LECTURE_HALL or LAB.
      capacity  — Maximum student occupancy.
      created_at / updated_at — Timestamps.

    The scheduler uses room_type and capacity for best-fit allocation.
    The frontend uses the same fields for the room management table.
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    room_type: RoomType
    capacity: int
    created_at: datetime
    updated_at: datetime
