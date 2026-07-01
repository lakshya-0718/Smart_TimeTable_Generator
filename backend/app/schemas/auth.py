"""
schemas/auth.py — Pydantic models for the authentication layer.

These schemas are the contract between the API layer and the outside world.
They are NOT ORM models — they contain no SQLAlchemy machinery.

Schemas in this file:
  LoginRequest   — inbound:  email + password from the login form
  TokenResponse  — outbound: JWT + basic user info returned on successful login
  UserPublic     — re-export alias for UserRead (schemas/user.py is the
                   single source of truth for user serialization)
  TokenPayload   — internal: typed container for decoded JWT claims

Why is UserPublic kept as an alias (not deleted)?
  api/auth.py already imports UserPublic from this module.  The alias
  means we can point to UserRead without breaking that import or the
  OpenAPI schema names that the frontend will rely on.

Validation rules:
  - email is lowercased and stripped on input (prevents case-mismatch bugs)
  - password min length 8 enforces a basic security floor at the API edge
  - All UUIDs and datetimes are serialized to JSON-safe types by Pydantic v2
"""

from pydantic import BaseModel, Field, field_validator
from pydantic import EmailStr
import uuid

from app.models.enums import UserRole

# UserRead is the canonical user output schema (defined in schemas/user.py).
# UserPublic is kept as an alias so api/auth.py needs no changes.
from app.schemas.user import UserRead

UserPublic = UserRead  # backward-compat alias


# ── Inbound ───────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    """
    Credentials submitted by the user on the login page.

    `email` is normalized to lowercase so that "Admin@example.com" and
    "admin@example.com" always resolve to the same account.
    """

    email: EmailStr = Field(
        ...,
        description="Registered email address of the user.",
        examples=["admin@example.com"],
    )
    password: str = Field(
        ...,
        min_length=8,
        description="Account password (min 8 characters).",
    )

    @field_validator("email", mode="before")
    @classmethod
    def normalise_email(cls, v: str) -> str:
        """Lower-case and strip whitespace from the email before validation."""
        return v.strip().lower()


# ── Outbound — user representation ────────────────────────────────────────────
# UserPublic alias is imported above (= UserRead from schemas/user.py).


# ── Outbound — token response ─────────────────────────────────────────────────

class TokenResponse(BaseModel):
    """
    Response body for POST /auth/login.

    The frontend stores `access_token` in Zustand (memory only — no
    localStorage/sessionStorage) and attaches it as `Authorization: Bearer
    <token>` on every subsequent request via an Axios request interceptor.

    `token_type` is always "bearer" per OAuth2 / RFC 6750 convention.
    Including it lets the frontend code be generic about token attachment.

    `user` is embedded so the frontend can populate its auth Zustand slice
    (role, full_name, id) without an extra GET /auth/me call after login.
    """

    access_token: str = Field(..., description="Signed JWT access token.")
    token_type: str = Field(default="bearer", description="Always 'bearer'.")
    user: UserRead = Field(..., description="Public profile of the logged-in user.")


# ── Internal — decoded JWT payload ────────────────────────────────────────────

class TokenPayload(BaseModel):
    """
    Typed representation of the decoded JWT payload.

    Used internally by deps.py after calling security.decode_access_token().
    Pydantic validation here provides a second line of defence: even if a
    hand-crafted token passes jose's signature check, it must still conform
    to this schema or deps.py will reject it with a 401.

    Fields:
      sub  — user UUID as string (standard JWT "subject" claim)
      role — role string ("ADMIN", "FACULTY", "TA")
      exp  — expiry unix timestamp (jose already validated this; stored for
             potential downstream use, e.g. showing "session expires in X min")
    """

    sub: str = Field(..., description="User UUID (string form).")
    role: str = Field(..., description="User role string.")
    exp: int | float = Field(..., description="Expiry as a Unix timestamp.")

    @field_validator("sub")
    @classmethod
    def sub_must_be_valid_uuid(cls, v: str) -> str:
        """Reject tokens where sub is not a parseable UUID string."""
        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError("Token 'sub' claim is not a valid UUID.")
        return v

    @field_validator("role")
    @classmethod
    def role_must_be_known(cls, v: str) -> str:
        """Reject tokens with an unrecognised role claim."""
        valid_roles = {r.value for r in UserRole}
        if v not in valid_roles:
            raise ValueError(f"Token 'role' claim '{v}' is not a valid role.")
        return v
