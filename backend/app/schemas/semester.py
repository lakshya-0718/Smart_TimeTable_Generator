"""
schemas/semester.py — Pydantic models for the Semester Management API.

Schema hierarchy:

  Inbound (request bodies):
    SemesterCreate — Admin creates a new semester.
    SemesterUpdate — Admin renames an existing semester (PATCH).

  Outbound (response bodies):
    SemesterRead   — Public representation of a semester record.

Why no SemesterListResponse wrapper?
  Semesters are a small, bounded set — a single department will never have
  more than ~20 active semesters.  A flat list[SemesterRead] is simpler
  and cleaner here than a pagination wrapper.  If the dataset ever grew
  large enough to warrant pagination, a wrapper could be added without
  breaking any existing consumers (just add `total` and `items` around the
  existing list).

Validation rules:
  - name is stripped of whitespace on inbound.
  - name max length is 100 chars, matching the DB column VARCHAR(100).
  - is_active is NOT settable through SemesterCreate or SemesterUpdate.
    It has a dedicated POST /{id}/set-active endpoint so the intent is
    explicit and auditable.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


# ── Inbound ───────────────────────────────────────────────────────────────────

class SemesterCreate(BaseModel):
    """
    Request body for POST /semesters.

    Only `name` is required.  The admin assigns a human-readable label like
    "2024-25 Odd Sem" or "Monsoon 2025".

    `is_active` defaults to False at creation.  Use POST /semesters/{id}/set-active
    to activate a semester after it has been created and populated with courses.
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Human-readable semester name, e.g. '2024-25 Odd Sem'. Must be unique.",
        examples=["2024-25 Odd Sem"],
    )

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: str) -> str:
        """Strip leading/trailing whitespace so '  Odd Sem  ' is stored as 'Odd Sem'."""
        return v.strip()


class SemesterUpdate(BaseModel):
    """
    Request body for PATCH /semesters/{semester_id}.

    Only `name` is updatable here.
    `is_active` is controlled exclusively via POST /{id}/set-active and
    POST /{id}/unset-active — never via a general update.

    An empty body `{}` is a valid no-op (returns the unchanged semester).
    """

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="New name for the semester. Must be unique if provided.",
        examples=["2024-25 Even Sem"],
    )

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.strip()


# ── Outbound ──────────────────────────────────────────────────────────────────

class SemesterRead(BaseModel):
    """
    Public representation of a Semester record.

    Returned by all semester endpoints.

    `is_active` tells the frontend which semester is the currently selected
    working context.  Only one semester should have is_active=True at any
    time (enforced by semester_service.set_active).

    `updated_at` is included so the frontend can detect stale cached data.
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
