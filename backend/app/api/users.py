"""
api/users.py — Admin-only User Management endpoints.

All endpoints require role = ADMIN (enforced via Depends(require_admin)).
No Faculty or TA user can access any route in this router.

Endpoint map:

  POST   /api/v1/users                      Create a FACULTY or TA account
  GET    /api/v1/users                      List users (with filter + pagination)
  GET    /api/v1/users/{user_id}            Get a single user by UUID
  PATCH  /api/v1/users/{user_id}            Update email / full_name
  POST   /api/v1/users/{user_id}/deactivate Soft-deactivate a user
  POST   /api/v1/users/{user_id}/reactivate Re-enable a deactivated user

Design principles:
  - Thin routes: validate input → call service → return schema.
    Zero DB logic here.  Zero bcrypt calls here.
  - service.ValueError → HTTP 400 or 404 (see _handle_service_error).
  - A helper _get_user_or_404 centralises the "look up user, raise 404 if
    missing" pattern that four endpoints share.
  - PATCH uses UserUpdate (all optional fields).  An empty body is a no-op.
  - Admin cannot deactivate themselves via this endpoint (prevents lockout).
  - Deactivate/reactivate use POST (not DELETE/PUT) because they are actions
    on a sub-resource, not idempotent replacements of the full resource.
    POST is the correct HTTP verb for "perform this action".

Route IDs:
  Every endpoint has a unique `operation_id` so the OpenAPI-generated
  TypeScript client (future) gets unambiguous function names.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.user import UserCreate, UserListResponse, UserRead, UserUpdate
from app.services import user_service

router = APIRouter(
    prefix="/users",
    tags=["users"],
)


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _get_user_or_404(db: AsyncSession, user_id: uuid.UUID) -> User:
    """
    Fetch a user by UUID.  Raise 404 if not found.

    Shared by GET /users/{id}, PATCH /users/{id},
    POST /users/{id}/deactivate, POST /users/{id}/reactivate.
    """
    user = await user_service.get_user_by_id(db=db, user_id=user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id} not found.",
        )
    return user


def _handle_value_error(exc: ValueError) -> HTTPException:
    """
    Convert a service-layer ValueError to the appropriate HTTPException.

    Mapping:
      "User not found."        → 404
      "Email already registered." → 409 Conflict
      anything else            → 400 Bad Request
    """
    message = str(exc)
    if "not found" in message.lower():
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=message,
        )
    if "already registered" in message.lower() or "cannot be deleted" in message.lower():
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=message,
        )
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=message,
    )


# ── POST /users — Create a new Faculty or TA account ─────────────────────────

@router.post(
    "",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create user",
    description=(
        "Admin-only. Create a new FACULTY or TA account. "
        "ADMIN accounts cannot be created via this endpoint. "
        "Returns the created user's public profile (no hashed_password)."
    ),
    operation_id="create_user",
)
async def create_user(
    body: UserCreate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> UserRead:
    """
    Create a new Faculty or TA user.

    201 Created  — user created successfully, returns UserRead.
    409 Conflict — email is already registered.
    422 Unprocessable — validation failed (e.g. role=ADMIN, password too short).
    """
    try:
        user = await user_service.create_user(db=db, data=body)
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise _handle_value_error(exc)

    return UserRead.model_validate(user)


# ── GET /users — List users ───────────────────────────────────────────────────

@router.get(
    "",
    response_model=UserListResponse,
    status_code=status.HTTP_200_OK,
    summary="List users",
    description=(
        "Admin-only. Return a paginated list of all users. "
        "Filter by role with ?role=FACULTY or ?role=TA. "
        "Supports offset pagination via ?skip and ?limit."
    ),
    operation_id="list_users",
)
async def list_users(
    role: UserRole | None = Query(
        default=None,
        description="Filter by role. Omit to return all users.",
    ),
    skip: int = Query(default=0, ge=0, description="Number of records to skip."),
    limit: int = Query(default=50, ge=1, le=200, description="Max records per page (1–200)."),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> UserListResponse:
    """
    Return a paginated list of users.

    200 OK — always (even if the list is empty).

    The response includes `total` (count before pagination) so the
    frontend can render pagination controls without a separate COUNT call.
    """
    total, users = await user_service.list_users(
        db=db,
        role=role,
        skip=skip,
        limit=limit,
    )
    return UserListResponse(
        total=total,
        items=[UserRead.model_validate(u) for u in users],
    )


# ── GET /users/{user_id} — Get a single user ─────────────────────────────────

@router.get(
    "/{user_id}",
    response_model=UserRead,
    status_code=status.HTTP_200_OK,
    summary="Get user",
    description="Admin-only. Return the public profile of a single user by UUID.",
    operation_id="get_user",
)
async def get_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> UserRead:
    """
    Return a single user by UUID.

    200 OK  — user found.
    404 Not Found — no user with that UUID.
    """
    user = await _get_user_or_404(db=db, user_id=user_id)
    return UserRead.model_validate(user)


# ── PATCH /users/{user_id} — Update email / full_name ────────────────────────

@router.patch(
    "/{user_id}",
    response_model=UserRead,
    status_code=status.HTTP_200_OK,
    summary="Update user",
    description=(
        "Admin-only. Partially update a user's email and/or full_name. "
        "Omitting a field leaves it unchanged. "
        "Role and password cannot be changed via this endpoint. "
        "An empty body is a valid no-op."
    ),
    operation_id="update_user",
)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> UserRead:
    """
    Partially update a user record.

    200 OK       — update applied (or no-op if body was empty).
    404 Not Found — no user with that UUID.
    409 Conflict  — new email is already taken by another account.
    422 Unprocessable — validation failed (e.g. name too short).
    """
    try:
        user = await user_service.update_user(db=db, user_id=user_id, data=body)
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise _handle_value_error(exc)

    return UserRead.model_validate(user)


# ── POST /users/{user_id}/deactivate — Soft-deactivate ───────────────────────

@router.post(
    "/{user_id}/deactivate",
    response_model=UserRead,
    status_code=status.HTTP_200_OK,
    summary="Deactivate user",
    description=(
        "Admin-only. Soft-deactivate a user account. "
        "The user can no longer log in and all existing tokens are immediately "
        "rejected. Their data (assignments, timetable entries) is preserved. "
        "Admin cannot deactivate their own account through this endpoint."
    ),
    operation_id="deactivate_user",
)
async def deactivate_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> UserRead:
    """
    Deactivate a user account.

    200 OK       — user is now deactivated (idempotent: already-deactivated
                   user returns 200 with is_active=False).
    400 Bad Request — admin cannot deactivate themselves.
    404 Not Found   — no user with that UUID.
    """
    # Prevent admin self-lockout
    if user_id == current_admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot deactivate your own account.",
        )

    try:
        user = await user_service.deactivate_user(db=db, user_id=user_id)
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise _handle_value_error(exc)

    return UserRead.model_validate(user)


# ── POST /users/{user_id}/reactivate — Re-enable a deactivated user ──────────

@router.post(
    "/{user_id}/reactivate",
    response_model=UserRead,
    status_code=status.HTTP_200_OK,
    summary="Reactivate user",
    description=(
        "Admin-only. Re-enable a previously deactivated user account. "
        "The user can log in again immediately after reactivation. "
        "Idempotent: reactivating an already-active user returns 200."
    ),
    operation_id="reactivate_user",
)
async def reactivate_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> UserRead:
    """
    Re-enable a deactivated user account.

    200 OK        — user is now active.
    404 Not Found — no user with that UUID.
    """
    try:
        user = await user_service.reactivate_user(db=db, user_id=user_id)
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise _handle_value_error(exc)

    return UserRead.model_validate(user)


# ── DELETE /users/{user_id} — Delete user ────────────────────────────────────

@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete user",
    description=(
        "Admin-only. Permanently delete a user account. "
        "Fails with 409 Conflict if the user is assigned to courses or timetables."
    ),
    operation_id="delete_user",
)
async def delete_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> None:
    """
    Delete a user account.

    204 No Content — user is deleted.
    400 Bad Request — admin cannot delete themselves.
    404 Not Found   — no user with that UUID.
    409 Conflict    — user is assigned and cannot be deleted.
    """
    if user_id == current_admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete your own account.",
        )

    try:
        await user_service.delete_user(db=db, user_id=user_id)
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise _handle_value_error(exc)
