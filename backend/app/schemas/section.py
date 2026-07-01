"""
schemas/section.py — Pydantic models for the Section Management API.

Schema hierarchy:

  Inbound (request bodies):
    SectionCreate — Admin creates a new section (Y1A–Y4B).
    SectionUpdate — Admin updates a section's strength.

  Outbound (response bodies):
    SectionRead   — Public representation of a section record.

Design decisions:

  Why is `name` derived automatically from year + label?
    The DB has a unique constraint on both `name` and `(year, label)`.
    Allowing the admin to specify `name` independently from `year`+`label`
    would create a consistency problem: "Y2A" with year=3 is nonsense.
    The service derives `name = f"Y{year}{label}"` automatically, making
    the API surface simpler and preventing mismatch bugs.

  Why can't year/label be updated via PATCH?
    Year and label define a section's structural identity — "Y2A" IS
    "Year 2, Section A", not just a string label.  Changing year or label
    is semantically equivalent to deleting the section and creating a new
    one.  More importantly, these changes could silently corrupt course
    assignments and timetable entries that reference the section.
    If admin genuinely needs to rename a section's identity, they must
    delete and recreate it (which the RESTRICT FK will only permit if no
    live assignments exist).

  Why is `strength` the only PATCH-able field?
    Strength changes each semester as cohort enrolment numbers change.
    It is the only section field that legitimately varies over time while
    all other structural fields remain constant.  The admin updates it
    once per semester before running the scheduler.

  Why no SectionListResponse wrapper?
    The system scope is exactly 8 sections (Y1A, Y1B, Y2A, Y2B, Y3A, Y3B,
    Y4A, Y4B).  A flat list[SectionRead] is the correct, simplest contract
    for this small, fixed-size dataset.

Validation rules:
  - year must be 1–4 (mirrors DB CHECK constraint)
  - label must be 'A' or 'B', uppercase-normalized (mirrors DB CHECK)
  - strength must be > 0 (mirrors DB CHECK)
  - name is auto-derived from year + label — NOT a client-supplied field
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


# ── Inbound ───────────────────────────────────────────────────────────────────

class SectionCreate(BaseModel):
    """
    Request body for POST /sections.

    Admin provides year, label, and strength.
    The canonical section name (e.g. "Y2A") is derived by the service
    as f"Y{year}{label}" to guarantee consistency between the name column
    and the (year, label) composite unique constraint.

    All fields are required — there is no sensible default for any of them.
    """

    year: int = Field(
        ...,
        ge=1,
        le=4,
        description="Academic year the section belongs to (1–4).",
        examples=[2],
    )
    label: Literal["A", "B"] = Field(
        ...,
        description="Division letter within the year. Must be 'A' or 'B'.",
        examples=["A"],
    )
    strength: int = Field(
        ...,
        gt=0,
        le=32767,   # SMALLINT upper bound
        description="Number of enrolled students. Must be greater than 0.",
        examples=[60],
    )

    @field_validator("label", mode="before")
    @classmethod
    def uppercase_label(cls, v: str) -> str:
        """Normalise 'a' → 'A' and 'b' → 'B' before the Literal check."""
        if isinstance(v, str):
            return v.strip().upper()
        return v


class SectionUpdate(BaseModel):
    """
    Request body for PATCH /sections/{section_id}.

    Only `strength` is updatable.  year and label define structural identity
    and cannot change after creation.  An empty body {} is a valid no-op.

    strength must be > 0 when provided (mirrors DB CHECK constraint).
    """

    strength: int | None = Field(
        default=None,
        gt=0,
        le=32767,
        description="Updated student count. Must be greater than 0.",
        examples=[65],
    )


# ── Outbound ──────────────────────────────────────────────────────────────────

class SectionRead(BaseModel):
    """
    Public representation of a Section record.

    Returned by all section endpoints.

    Fields:
      id       — UUID primary key.
      name     — Derived canonical name, e.g. "Y2A".
      year     — Academic year (1–4).
      label    — Division letter ('A' or 'B').
      strength — Current enrolled student count.
      created_at / updated_at — Timestamps.

    All fields are read-only from the consumer's perspective.
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    year: int
    label: str
    strength: int
    created_at: datetime
    updated_at: datetime
