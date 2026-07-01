"""
schemas/availability.py — Pydantic models for the Availability Management API.

Schema hierarchy:

  Shared:
    SlotInput          — One (day, slot_hour) pair for use in request bodies.

  Faculty availability:
    FacultyAvailabilityCreate — Request body for PUT /availability/faculty/{user_id}
                                (bulk-replace all slots for a faculty member).

  TA availability:
    TAAvailabilityCreate      — Request body for PUT /availability/ta/{user_id}.

  Outbound:
    AvailabilitySlotRead      — One row from the DB (id + user_id + day + slot_hour).
    AvailabilityResponse      — Full availability set for one user.

Design decisions:

  Why PUT (replace) instead of POST/PATCH for the primary write operation?
    The availability tables use "replace semantics" as documented in the
    model and the database_schema.md:
      "Rows are never updated in-place.  Replace semantics: the frontend
       sends the full new availability set, and the service deletes-then-inserts."
    There is no meaningful way to UPDATE a slot: a slot IS its (user_id, day,
    slot_hour) triple.  "Changing" a slot means deleting the old triple and
    inserting a new one.  PUT with a full set is the semantically correct
    HTTP method for this pattern (PUT replaces the entire resource state).

    However, to support granular operations (add one slot, remove one slot)
    without requiring the frontend to re-send the entire set every time,
    we also expose:
      POST /{user_id}/slots         — add exactly one slot
      DELETE /{user_id}/slots/{id}  — remove exactly one slot by its UUID

  Why no `updated_at` in AvailabilitySlotRead?
    The `UUIDPKCreatedAtMixin` on FacultyAvailability and TAAvailability
    provides only `id` and `created_at` — no `updated_at`.  These rows
    are immutable after insertion.

  Validation rules:
    - slot_hour: 8–17 (mirrors DB CHECK constraint and engine Slot.start_hour)
    - day: must be a valid DayOfWeek enum value (MON–FRI)
    - Duplicate (day, slot_hour) pairs in a single bulk-replace request are
      silently de-duplicated by the service (set semantics before insert).
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import DayOfWeek


# ── Shared building block ─────────────────────────────────────────────────────

class SlotInput(BaseModel):
    """
    One unavailable (day, slot_hour) pair.

    Used as elements in the bulk-replace list and as the body for the
    single-slot add endpoint.

    slot_hour represents the START of a 1-hour window:
      8  = 8:00–9:00 AM
      9  = 9:00–10:00 AM
      ...
      17 = 17:00–18:00 PM (5 PM–6 PM)

    These values map directly to the scheduler engine's Slot.start_hour
    field — no conversion is needed between the API, DB, and engine.
    """

    day: DayOfWeek = Field(
        ...,
        description="Day of the week: MON | TUE | WED | THU | FRI.",
        examples=[DayOfWeek.MON],
    )
    slot_hour: int = Field(
        ...,
        ge=8,
        le=17,
        description=(
            "Start hour of the unavailable slot (8–17). "
            "8 = 8:00–9:00, 9 = 9:00–10:00, ..., 17 = 17:00–18:00."
        ),
        examples=[10],
    )


# ── Inbound: Faculty ──────────────────────────────────────────────────────────

class FacultyAvailabilityCreate(BaseModel):
    """
    Request body for PUT /availability/faculty/{user_id}.

    Provides the COMPLETE set of unavailable slots for a faculty member.
    The service atomically replaces the existing set with this new set
    (DELETE all existing rows, INSERT the new rows — one transaction).

    An empty slots list [] clears all unavailability for the user
    (makes them available for all slots).

    Duplicate (day, slot_hour) pairs are silently de-duplicated before
    insertion — the service treats the list as a set.
    """

    slots: list[SlotInput] = Field(
        ...,
        description=(
            "Complete set of unavailable slots. "
            "Replaces all existing availability for this faculty member. "
            "Empty list clears all unavailability."
        ),
    )


class TAAvailabilityCreate(BaseModel):
    """
    Request body for PUT /availability/ta/{user_id}.

    Identical contract to FacultyAvailabilityCreate but for TA users.
    """

    slots: list[SlotInput] = Field(
        ...,
        description=(
            "Complete set of unavailable slots. "
            "Replaces all existing availability for this TA. "
            "Empty list clears all unavailability."
        ),
    )


# ── Outbound ──────────────────────────────────────────────────────────────────

class AvailabilitySlotRead(BaseModel):
    """
    Public representation of one availability row.

    Returned by granular add/delete and in the slots list of AvailabilityResponse.

    No updated_at — availability rows are immutable after insertion
    (confirmed by UUIDPKCreatedAtMixin on both model classes).
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    user_id: uuid.UUID
    day: DayOfWeek
    slot_hour: int
    created_at: datetime


class AvailabilityResponse(BaseModel):
    """
    Full availability set for one user.

    Returned by:
      GET  /availability/faculty/{user_id}
      GET  /availability/ta/{user_id}
      PUT  /availability/faculty/{user_id}  (after replace)
      PUT  /availability/ta/{user_id}       (after replace)

    `total` lets the frontend know how many slots are blocked
    without counting the list.

    `slots` is ordered by day then slot_hour (Mon first, 8 AM first)
    matching the logical order of the weekly schedule.
    """

    user_id: uuid.UUID = Field(..., description="The user whose availability this describes.")
    total: int = Field(..., description="Total number of unavailable slots.")
    slots: list[AvailabilitySlotRead] = Field(
        ...,
        description="All unavailable slots, ordered by day then slot_hour.",
    )
