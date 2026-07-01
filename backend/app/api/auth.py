"""
api/auth.py — Authentication endpoints.

Endpoints:
  POST /api/v1/auth/login
    - Accepts email + password (JSON body, not form-encoded).
    - Returns a JWT access token + public user profile.
    - No authentication required (this is the entry point).

  GET /api/v1/auth/me
    - Requires a valid Bearer token.
    - Returns the public profile of the currently authenticated user.
    - Useful for the frontend to refresh Zustand auth state after a
      page component mounts.

Design notes:

  Login uses OAuth2 form encoding:
    The OAuth2 spec defines a form-encoded password flow. We use 
    OAuth2PasswordRequestForm as the FastAPI dependency to consume the 
    credentials. This ensures the correct OpenAPI documentation and allows
    the Swagger "Authorize" button to function seamlessly. Clients (like 
    the frontend) must send `application/x-www-form-urlencoded` payloads 
    (`grant_type=password`, `username=...`, `password=...`).

  No refresh token endpoint yet:
    The architecture mentions a refresh flow, but the frontend stores the
    JWT in memory (Zustand).  On hard refresh, the user logs in again.
    A refresh token endpoint is a future enhancement; adding it now would
    require a token blacklist or rotation table that doesn't exist yet.

  Rate limiting:
    The login endpoint should be rate-limited in production.  This is
    handled at the Nginx reverse-proxy layer (not in FastAPI) to avoid
    adding state to the stateless backend.

  Audit log:
    Failed login attempts are not logged here.  In production, this would
    be done via a middleware or the Nginx access log.  Not in scope for v1.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_authenticated
from app.schemas.auth import TokenResponse, UserPublic
from app.services.auth_service import authenticate_user, create_token_for_user

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)


# ── POST /auth/login ──────────────────────────────────────────────────────────

@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Login",
    description=(
        "Authenticate with email (as username) and password using OAuth2 form data. "
        "Returns a JWT access token and the user's public profile. "
        "The token must be attached to all subsequent requests as: "
        "`Authorization: Bearer <token>`."
    ),
)
async def login(
    credentials: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """
    Validate credentials and issue a JWT access token.

    On success → 200 with TokenResponse (token + UserPublic).
    On failure → 401 Unauthorized.

    The error message is intentionally generic ("Invalid credentials.")
    regardless of whether the email is unknown or the password is wrong.
    This prevents user-enumeration attacks.
    """
    user = await authenticate_user(
        db=db,
        email=credentials.username,
        password=credentials.password,
    )

    if user is None:
        # authenticate_user returns None for: unknown email, wrong password,
        # deactivated account.  All map to the same 401 response.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_token_for_user(user)

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user=UserPublic.model_validate(user),
    )


# ── GET /auth/me ──────────────────────────────────────────────────────────────

@router.get(
    "/me",
    response_model=UserPublic,
    status_code=status.HTTP_200_OK,
    summary="Get current user",
    description=(
        "Return the public profile of the currently authenticated user. "
        "Requires a valid Bearer token. "
        "Useful for the frontend to verify token validity and re-populate "
        "its auth state after a component remount."
    ),
)
async def get_me(
    # require_authenticated accepts any valid active user (Admin, Faculty, TA).
    # The dependency also validates the JWT and loads the user from the DB,
    # so this endpoint is a 'free' liveness check for the token.
    current_user=Depends(require_authenticated),
) -> UserPublic:
    """
    Return the authenticated user's public profile.

    On success → 200 with UserPublic.
    On failure → 401 if token is missing/invalid/expired.
    """
    return UserPublic.model_validate(current_user)
