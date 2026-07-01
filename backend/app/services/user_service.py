"""
services/user_service.py — Business logic for User Management.

Responsibilities:
  - Create Faculty and TA accounts (with duplicate-email check, bcrypt hash).
  - List users (with optional role filter and offset/limit pagination).
  - Retrieve a single user by UUID.
  - Update email and/or full_name (with uniqueness re-check on email).
  - Deactivate a user (soft delete — sets is_active=False).
  - Reactivate a previously deactivated user.

Design principles:
  - NO HTTP knowledge.  No FastAPI, no Request, no HTTPException, no status
    codes.  Business-rule violations raise plain ValueError with a human-
    readable message.  The route layer in api/users.py converts them to
    appropriate HTTP responses.
  - Every function is async and receives an AsyncSession from dependency
    injection.  Sessions are never created inside the service.
  - SQLAlchemy 2.0 select() API throughout.  No legacy Query API.
  - The service calls db.flush() after writes so that the ORM object gets
    its server-side defaults populated (e.g. created_at, updated_at from
    the DB trigger) before the response schema reads them.  db.commit() is
    NOT called here — the route layer commits, keeping transaction control
    at the API boundary.

Error contract (what callers should expect):
  create_user    → raises ValueError("Email already registered.")
                          if the email exists
  update_user    → raises ValueError("Email already registered.")
                          if the new email conflicts with another account
                 → raises ValueError("User not found.")
                          if user_id doesn't exist (let route return 404)
  deactivate_user → raises ValueError("User not found.")
  reactivate_user → raises ValueError("User not found.")
  get_user_by_id  → returns None if not found (route returns 404)

Why use ValueError instead of custom exceptions?
  For a project of this scale, plain ValueError with a message string is
  perfectly readable and requires no extra exception hierarchy.  If the
  project grows, a custom AppError class can be dropped in without changing
  the service signatures.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate


# ── Read helpers ──────────────────────────────────────────────────────────────

async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    """
    Return the User with the given UUID, or None if not found.

    Uses db.get() which checks the session identity-map cache before
    issuing a SELECT.  On a typical request this avoids an extra DB
    round-trip when the same user is looked up by both deps.get_current_user
    (via auth_service.get_user_by_id) and a subsequent service call.
    """
    return await db.get(User, user_id)


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    """
    Return the User with the given email, or None if not found.

    Used internally for duplicate-email checks during create and update.
    """
    result = await db.execute(select(User).where(User.email == email))
    return result.scalars().first()


async def list_users(
    db: AsyncSession,
    role: UserRole | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[int, list[User]]:
    """
    Return a (total_count, page_of_users) tuple.

    Args:
        db:    Async DB session.
        role:  Optional filter.  If provided, only users with that role are
               returned.  If None, all users are returned.
        skip:  Number of rows to skip (for offset pagination).
        limit: Maximum rows to return per page (capped at 200 by the route).

    Returns:
        A tuple of (total_matching_count, list_of_User_objects).
        `total` is the count *before* pagination so the frontend can compute
        total pages without a separate request.

    Ordering: created_at DESC (newest accounts first) then email ASC as a
    stable tie-breaker.  This order is deterministic and makes sense for an
    admin user list.
    """
    base_filter = []
    if role is not None:
        base_filter.append(User.role == role)

    # COUNT query
    count_result = await db.execute(
        select(func.count()).select_from(User).where(*base_filter)
    )
    total: int = count_result.scalar_one()

    # Data query with pagination
    data_result = await db.execute(
        select(User)
        .where(*base_filter)
        .order_by(User.created_at.desc(), User.email.asc())
        .offset(skip)
        .limit(limit)
    )
    users = list(data_result.scalars().all())

    return total, users


# ── Mutations ─────────────────────────────────────────────────────────────────

async def create_user(db: AsyncSession, data: UserCreate) -> User:
    """
    Create a new FACULTY or TA user account.

    Steps:
      1. Check that the email is not already registered (case-insensitive
         because UserCreate.normalise_email already lowercases the input,
         and stored emails are always lowercase).
      2. Hash the plaintext password with bcrypt.
      3. Create and persist the User ORM object.
      4. flush() so the DB populates server-side defaults (id, created_at,
         updated_at).

    Raises:
      ValueError — if the email is already taken.

    Note on role restriction:
      UserCreate.role_must_not_be_admin already rejects role=ADMIN at the
      Pydantic validation layer.  The service does not need to re-check this
      — Pydantic is the boundary.
    """
    existing = await get_user_by_email(db=db, email=data.email)
    if existing is not None:
        raise ValueError("Email already registered.")

    user = User(
        email=data.email,
        hashed_password=get_password_hash(data.password),
        full_name=data.full_name,
        role=data.role,
        is_active=True,
    )

    db.add(user)
    await db.flush()   # populate id / created_at / updated_at from DB
    await db.refresh(user)
    return user


async def update_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    data: UserUpdate,
) -> User:
    """
    Partially update a user's email and/or full_name.

    Only fields present in the request body are updated.  This is achieved
    by checking `data.model_fields_set` — the set of field names that were
    explicitly provided (not defaulted to None) by the caller.

    Example:
      PATCH /users/{id}  body: {"full_name": "Dr. New Name"}
      → only full_name is updated, email is left unchanged.

      PATCH /users/{id}  body: {}
      → no-op: returns the user unchanged.

    Raises:
      ValueError("User not found.")    — if user_id doesn't exist.
      ValueError("Email already registered.")  — if new email conflicts.
    """
    user = await get_user_by_id(db=db, user_id=user_id)
    if user is None:
        raise ValueError("User not found.")

    if "email" in data.model_fields_set and data.email is not None:
        # Only check uniqueness if the email is actually changing
        if data.email != user.email:
            conflict = await get_user_by_email(db=db, email=data.email)
            if conflict is not None:
                raise ValueError("Email already registered.")
        user.email = data.email

    if "full_name" in data.model_fields_set and data.full_name is not None:
        user.full_name = data.full_name

    await db.flush()
    await db.refresh(user)
    return user


async def deactivate_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    """
    Soft-deactivate a user by setting is_active = False.

    The user record is retained in the database.  All their course
    assignments, timetable entries, and availability records remain intact.
    They can no longer log in (authenticate_user rejects inactive accounts),
    and any existing valid tokens will be rejected on the next request by
    deps.get_current_user.

    Idempotent: deactivating an already-deactivated user is a no-op
    (returns the user with is_active=False without error).

    Raises:
      ValueError("User not found.") — if user_id doesn't exist.
    """
    user = await get_user_by_id(db=db, user_id=user_id)
    if user is None:
        raise ValueError("User not found.")

    user.is_active = False
    await db.flush()
    await db.refresh(user)
    return user


async def reactivate_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    """
    Re-enable a previously deactivated user by setting is_active = True.

    Idempotent: reactivating an already-active user is a no-op.

    Raises:
      ValueError("User not found.") — if user_id doesn't exist.
    """
    user = await get_user_by_id(db=db, user_id=user_id)
    if user is None:
        raise ValueError("User not found.")

    user.is_active = True
    await db.flush()
    await db.refresh(user)
    return user


async def delete_user(db: AsyncSession, user_id: uuid.UUID) -> None:
    """
    Permanently delete a user account.

    Raises:
      ValueError("User not found.")
      ValueError("User cannot be deleted because they are assigned to courses or timetables.")
    """
    user = await get_user_by_id(db=db, user_id=user_id)
    if user is None:
        raise ValueError("User not found.")

    try:
        await db.delete(user)
        await db.flush()
    except IntegrityError:
        raise ValueError("User cannot be deleted because they are assigned to courses or timetables.")

