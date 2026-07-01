"""
schemas/user.py — Pydantic models for the User Management API.

This module is the single source of truth for all user-facing schemas.
schemas/auth.py imports UserRead from here so that both auth endpoints
(POST /auth/login, GET /auth/me) and user-management endpoints return
the same object shape.

Schema hierarchy:

  Inbound (request bodies):
    UserCreate   — Admin creates a new Faculty or TA account.
    UserUpdate   — Admin partially updates email / full_name.

  Outbound (response bodies):
    UserRead     — Safe public representation of a user.
                   NEVER includes hashed_password.
    UserListResponse — Paginated list wrapper for GET /users.

Validation rules enforced here (not in the service):
  - email normalised to lowercase + stripped (same as LoginRequest)
  - password min length 8 (creation only)
  - role restricted to FACULTY | TA on creation (Admin cannot create
    another Admin through the API — Admins are seeded at DB level)
  - full_name stripped of leading/trailing whitespace
  - All fields that are optional on UserUpdate use None as the sentinel
    for "not provided" (Pydantic v2 model_fields_set is used in the
    service to skip unchanged fields)

Why no AdminCreate or separate FacultyCreate/TACreate?
  All three user types share the same `users` table and the same fields.
  The only difference between creating a Faculty and a TA is the `role`
  value.  A single UserCreate schema with a role field is cleaner and
  requires no code duplication.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.enums import UserRole


# ── Inbound ───────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    """
    Request body for POST /users.

    Admin-only.  Creates a FACULTY or TA account.
    Admin accounts are NOT creatable via this endpoint; they are seeded
    directly in the database.  Attempting to set role=ADMIN returns 422.

    All fields are required — there is no sensible default for any of them.
    """

    email: EmailStr = Field(
        ...,
        description="Email address for the new account. Must be unique.",
        examples=["dr.sharma@college.edu"],
    )
    full_name: str = Field(
        ...,
        min_length=2,
        max_length=255,
        description="Full display name of the user.",
        examples=["Dr. Ananya Sharma"],
    )
    password: str = Field(
        ...,
        min_length=8,
        description="Initial password (min 8 characters). User should change it on first login.",
        examples=["SecurePass123"],
    )
    role: UserRole = Field(
        ...,
        description="Role to assign: FACULTY or TA.",
        examples=[UserRole.FACULTY],
    )

    @field_validator("email", mode="before")
    @classmethod
    def normalise_email(cls, v: str) -> str:
        """Lowercase + strip so storage is always canonical."""
        return v.strip().lower()

    @field_validator("full_name", mode="before")
    @classmethod
    def strip_name(cls, v: str) -> str:
        return v.strip()

    @field_validator("role")
    @classmethod
    def role_must_not_be_admin(cls, v: UserRole) -> UserRole:
        """
        Admin accounts cannot be created via the API.
        They are provisioned directly in the database by the system operator.
        This prevents privilege escalation through the user-creation endpoint.
        """
        if v == UserRole.ADMIN:
            raise ValueError(
                "Admin accounts cannot be created through the API. "
                "Provision them directly in the database."
            )
        return v


class UserUpdate(BaseModel):
    """
    Request body for PATCH /users/{user_id}.

    All fields are optional.  The service inspects `model_fields_set`
    to update only the fields that were explicitly provided in the request.
    Omitting a field means "leave it unchanged", NOT "set it to null".

    Updatable fields: email, full_name.
    NOT updatable via this endpoint: role, password, is_active.
      - role changes are a significant access-control event; not supported in v1.
      - password changes require a separate /change-password flow (future).
      - is_active is toggled via the dedicated /deactivate and /reactivate
        endpoints so the intent is explicit and auditable.
    """

    email: EmailStr | None = Field(
        default=None,
        description="New email address. Must be unique across all users.",
        examples=["new.email@college.edu"],
    )
    full_name: str | None = Field(
        default=None,
        min_length=2,
        max_length=255,
        description="Updated display name.",
        examples=["Dr. Ananya Sharma"],
    )

    @field_validator("email", mode="before")
    @classmethod
    def normalise_email(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.strip().lower()

    @field_validator("full_name", mode="before")
    @classmethod
    def strip_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.strip()


# ── Outbound ──────────────────────────────────────────────────────────────────

class UserRead(BaseModel):
    """
    Safe, read-only representation of a User record.

    This is the canonical user output schema used by:
      - POST /users          (response: the created user)
      - GET  /users          (response: list of UserRead)
      - GET  /users/{id}     (response: single UserRead)
      - PATCH /users/{id}    (response: updated UserRead)
      - POST /users/{id}/deactivate   (response: updated UserRead)
      - POST /users/{id}/reactivate   (response: updated UserRead)
      - POST /auth/login     (embedded in TokenResponse)
      - GET  /auth/me        (direct response)

    Intentionally EXCLUDES:
      - hashed_password — NEVER sent over the wire under any circumstances.
      - Internal ORM relationships (availability lists, assignment lists).
        Those are loaded lazily and would trigger unnecessary DB queries.

    `updated_at` is included so the frontend can detect stale cached data.
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    email: EmailStr
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserListResponse(BaseModel):
    """
    Paginated response wrapper for GET /users.

    `total` is the count of all matching users (before pagination).
    `items` is the current page.

    Using an explicit wrapper (instead of returning a plain list) allows
    the frontend to know the total count without a separate COUNT request,
    and makes it easy to add cursor-based pagination in the future without
    breaking the response contract.
    """

    total: int = Field(..., description="Total number of users matching the filter.")
    items: list[UserRead] = Field(..., description="Users on the current page.")
