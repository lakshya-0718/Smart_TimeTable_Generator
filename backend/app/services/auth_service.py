"""
services/auth_service.py — Business logic for authentication.

Responsibilities:
  - Load users from the database (by email, by UUID).
  - Authenticate a login attempt (email + password → User or None).
  - Build the JWT token string for a given user.

Design principles:
  - NO HTTP knowledge.  No Request, no HTTPException, no status codes.
    Callers (api/auth.py) decide what HTTP response to produce.
  - Every function is async and accepts an AsyncSession parameter.
    Sessions are provided by the dependency injection in api/deps.py
    and are never created inside the service.
  - Queries use SQLAlchemy 2.0 select() API (not the legacy Query API).
  - authenticate_user returns None on failure (not an exception) because
    failed login is expected business logic, not an exceptional condition.
    The route layer converts None → 401.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, verify_password
from app.models.user import User


# ── Read helpers ──────────────────────────────────────────────────────────────

async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    """
    Return the User with the given email, or None if not found.

    The email lookup is case-sensitive at the DB level because the
    `users.email` column stores lowercase values (enforced by
    LoginRequest.normalise_email in schemas/auth.py and by the
    user-creation service).  No LOWER() call needed here.

    Used by:
      - authenticate_user (login path)
      - admin user-creation service (duplicate-email check, built later)
    """
    result = await db.execute(
        select(User).where(User.email == email)
    )
    return result.scalars().first()


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    """
    Return the User with the given UUID primary key, or None if not found.

    Used by:
      - deps.get_current_user (called on every authenticated request)

    Uses db.get() which hits the session identity-map cache first
    (no DB round-trip if the object was already loaded in this session).
    Falls back to a SELECT if not cached.
    """
    return await db.get(User, user_id)


# ── Login ─────────────────────────────────────────────────────────────────────

async def authenticate_user(
    db: AsyncSession,
    email: str,
    password: str,
) -> User | None:
    """
    Validate email + password against the database.

    Returns the User object on success, None on any failure.

    Failure cases (all return None — deliberately no distinction):
      - Email not found in the database.
      - Password does not match the stored bcrypt hash.
      - User account is deactivated (is_active = False).

    Returning None for all failure cases prevents user-enumeration attacks:
    a caller cannot determine whether the email exists or the password
    was wrong — both look identical.

    Note on is_active:
      Deactivated users cannot log in and cannot obtain new tokens.
      However, tokens issued before deactivation remain valid until they
      expire.  This is acceptable because:
        1. Token lifetime is short (60 minutes by default).
        2. deps.get_current_user checks is_active on every request,
           so a deactivated user's existing token is blocked immediately.
    """
    user = await get_user_by_email(db=db, email=email)

    if user is None:
        # Run a dummy verify to prevent timing oracle attacks.
        # If we return immediately on "email not found", the response time
        # is shorter than a "wrong password" response that calls bcrypt.verify().
        # An attacker could use this timing difference to enumerate valid emails.
        # The dummy verify call makes both paths take ~same time.
        _dummy_hash = "$2b$12$KIXm4O5G7e5F1hUQSW8Q.OFBZjPQD3VHW1XSIl5E2fXN9EqFQRziy"
        verify_password(password, _dummy_hash)
        return None

    if not verify_password(password, user.hashed_password):
        return None

    if not user.is_active:
        return None

    return user


# ── Token creation ────────────────────────────────────────────────────────────

def create_token_for_user(user: User) -> str:
    """
    Create a JWT access token for the given User.

    Wraps security.create_access_token with the correct subject and role.
    Separating this from authenticate_user allows the admin user-creation
    endpoint to optionally issue a token without going through the login
    flow (future use).

    The `sub` claim is the user UUID serialised as a lowercase hyphenated
    string (Python's default UUID.__str__()).  This is consistent with
    how deps.py parses it back: uuid.UUID(payload.sub).
    """
    return create_access_token(
        subject=str(user.id),
        role=user.role.value,
    )
