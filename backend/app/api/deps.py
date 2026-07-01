"""
api/deps.py — FastAPI dependency injection for auth and DB session.

Every protected route declares its auth requirement by depending on one
of the functions here.  FastAPI resolves the dependency graph automatically.

Dependency hierarchy:

  get_db                 — yields an async DB session for the request
      │
  get_current_user       — verifies JWT, loads User from DB
      │
      ├── require_admin             — allows only ADMIN
      └── require_faculty_or_ta    — allows FACULTY or TA

Usage in a route:

  @router.get("/example")
  async def example(
      current_user: User = Depends(require_admin),
      db: AsyncSession = Depends(get_db),
  ):
      ...

Design principles:
  - get_db is re-exported here so that route files only need to import
    from app.api.deps, not from app.core.database directly.
  - get_current_user always hits the DB (one SELECT per request).  This
    is intentional: it makes is_active revocation effective immediately
    without waiting for token expiry.
  - Role guards raise 403 Forbidden (not 401) because the user IS
    authenticated — they just lack the required permission.  This follows
    RFC 9110 §15.5 semantics.
  - All error messages are deliberately vague to avoid leaking internal
    role structure to unauthenticated callers.
"""

import uuid

from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db  # re-exported for convenience
from app.core.security import TokenDecodeError, decode_access_token
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.auth import TokenPayload

# ── OAuth2 scheme ─────────────────────────────────────────────────────────────

# tokenUrl points to the login endpoint (used by the OpenAPI /docs UI).
# It does NOT validate anything — it only tells FastAPI where the token
# comes from so that the Swagger "Authorize" button works correctly.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


# ── Core dependency ───────────────────────────────────────────────────────────

async def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Resolve a Bearer JWT to an active User ORM object.

    Steps:
      1. Decode + validate the JWT (signature, expiry, claim structure).
      2. Extract the user UUID from the "sub" claim.
      3. Load the User row from the database.
      4. Verify the user exists and is_active = True.

    Raises:
      401 Unauthorized — if the token is missing, invalid, expired,
                         or the user no longer exists / is deactivated.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    import traceback
    print("====== DEBUG GET_CURRENT_USER ======")
    print("DEBUG RAW AUTH HEADER:", request.headers.get("Authorization"))
    print("DEBUG EXTRACTED TOKEN:", token)

    # ── Step 1: Decode JWT ────────────────────────────────────────────
    try:
        raw_payload = decode_access_token(token)
        print("DEBUG DECODED PAYLOAD:", raw_payload)
    except Exception as e:
        print("EXCEPTION IN DECODE:", repr(e))
        traceback.print_exc()
        raise credentials_exception

    # ── Step 2: Validate payload structure ────────────────────────────
    try:
        payload = TokenPayload(**raw_payload)
        print("DEBUG VALIDATED PAYLOAD:", payload)
    except Exception as e:
        print("EXCEPTION IN VALIDATE:", repr(e))
        traceback.print_exc()
        raise credentials_exception

    # ── Step 3: Load user from DB ─────────────────────────────────────
    try:
        user_id = uuid.UUID(payload.sub)
        print("DEBUG USER_ID:", user_id)
    except Exception as e:
        print("EXCEPTION IN UUID PARSE:", repr(e))
        traceback.print_exc()
        raise credentials_exception

    from app.services.auth_service import get_user_by_id

    try:
        user = await get_user_by_id(db=db, user_id=user_id)
        print("DEBUG DB RESULT:", user)
    except Exception as e:
        print("EXCEPTION IN DB LOOKUP:", repr(e))
        traceback.print_exc()
        raise credentials_exception

    if user is None:
        print("DEBUG: USER IS NONE")
        raise credentials_exception

    # ── Step 4: Check is_active ───────────────────────────────────────
    if not user.is_active:
        # Return 401 (not 403) — a deactivated account is treated as if
        # it does not exist from an authentication standpoint.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is deactivated.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


# ── Role guards ───────────────────────────────────────────────────────────────

async def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Allow only users with role = ADMIN.

    Use this for all admin-only endpoints:
      - Semester / section / course / room management
      - Course assignment management
      - Timetable generation and deletion

    Raises:
      403 Forbidden — if the authenticated user is FACULTY or TA.
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    return current_user


async def require_faculty_or_ta(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Allow FACULTY and TA users (but not ADMIN).

    Use this for endpoints that Faculty and TA can access but Admin cannot
    — specifically: marking own availability slots.

    Note: Admin can view the timetable, but availability marking is a
    self-service action for Faculty/TA.  If Admin needs to manage
    availability on behalf of a user, that is a separate admin endpoint
    (to be built later) using require_admin.

    Raises:
      403 Forbidden — if the authenticated user is ADMIN.
    """
    if current_user.role not in (UserRole.FACULTY, UserRole.TA):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Faculty or TA access required.",
        )
    return current_user


async def require_authenticated(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Allow any authenticated user regardless of role.

    Use this for read-only endpoints that all roles can access:
      - GET /timetable (view the current timetable)
      - GET /auth/me (view own profile)

    This dependency is provided for clarity — it is semantically identical
    to get_current_user but its name makes the intent explicit at the
    route definition level.
    """
    return current_user


# ── Re-exports ────────────────────────────────────────────────────────────────

# Route files only need to import from app.api.deps — one import location
# for all injectable dependencies.

__all__ = [
    "get_db",
    "get_current_user",
    "require_admin",
    "require_faculty_or_ta",
    "require_authenticated",
]
