"""
api/courses.py — Admin-only Course Management endpoints.

All endpoints require role = ADMIN (enforced via Depends(require_admin)).

Endpoint map:

  POST   /api/v1/courses                  Create a course in a semester
  GET    /api/v1/courses                  List courses (?semester_id= required)
  GET    /api/v1/courses/{course_id}      Get a single course by UUID
  PATCH  /api/v1/courses/{course_id}      Update course name / code / tier
  DELETE /api/v1/courses/{course_id}      Delete a course (hard delete, CASCADE)

Design principles:
  - Thin routes: validate → call service → return schema.
  - ValueError → HTTP status via _handle_value_error helper.
  - Every mutating route wraps in try/commit + except/rollback.
  - All endpoints have unique operation_id for OpenAPI client generation.

Why does GET /courses require ?semester_id=?
  Courses only make sense in the context of a semester.  Returning all
  courses from all semesters in one list would be a large, unsortable blob.
  Requiring semester_id on the list endpoint forces the frontend to always
  scope its queries correctly.  The GET /{course_id} endpoint works without
  semester_id since it resolves by PK.

Why is DELETE safe without a guard?
  Deleting a course cascades to course_assignments (fk_ca_course_id CASCADE)
  which then cascades to timetable_entries (fk_te_assignment_id CASCADE).
  All downstream data is removed cleanly.  No RESTRICT FK on course_id
  exists in the migration, so no IntegrityError will occur.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin
from app.models.user import User
from app.schemas.course import CourseCreate, CourseListResponse, CourseRead, CourseUpdate
from app.services import course_service

router = APIRouter(
    prefix="/courses",
    tags=["courses"],
)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _handle_value_error(exc: ValueError) -> HTTPException:
    """
    Convert a service-layer ValueError to the appropriate HTTPException.

    Mapping:
      message contains "not found"       → 404 Not Found
      message contains "already exists"  → 409 Conflict
      anything else                      → 400 Bad Request
    """
    message = str(exc)
    low = message.lower()

    if "not found" in low:
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=message,
        )
    if "already exists" in low:
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=message,
        )
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=message,
    )


# ── POST /courses — Create ────────────────────────────────────────────────────

@router.post(
    "",
    response_model=CourseRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create course",
    description=(
        "Admin-only. Create a new course in a semester. "
        "The course code must be unique within the semester. "
        "tier encodes the L-T-P pattern: "
        "TIER_1 (4-credit), TIER_2 (3-credit), "
        "TIER_3 (2-credit lab), TIER_4 (1-credit lab)."
    ),
    operation_id="create_course",
)
async def create_course(
    body: CourseCreate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> CourseRead:
    """
    Create a course.

    201 Created  — course created.
    404 Not Found — semester_id does not exist.
    409 Conflict — code already exists in this semester.
    422 Unprocessable — invalid tier, missing fields.
    """
    try:
        course = await course_service.create_course(db=db, data=body)
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise _handle_value_error(exc)

    return CourseRead.model_validate(course)


# ── GET /courses — List ───────────────────────────────────────────────────────

@router.get(
    "",
    response_model=CourseListResponse,
    status_code=status.HTTP_200_OK,
    summary="List courses",
    description=(
        "Admin-only. List courses for a semester. "
        "semester_id is required. "
        "Courses are ordered by tier (TIER_1 first) then name. "
        "Supports offset pagination via ?skip and ?limit."
    ),
    operation_id="list_courses",
)
async def list_courses(
    semester_id: uuid.UUID = Query(
        ...,
        description="UUID of the semester to list courses for. Required.",
    ),
    skip: int = Query(default=0, ge=0, description="Number of records to skip."),
    limit: int = Query(default=100, ge=1, le=200, description="Max records per page (1–200)."),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> CourseListResponse:
    """
    Return courses for a semester.

    200 OK — always (empty list if no courses in this semester).
    """
    total, courses = await course_service.list_courses(
        db=db,
        semester_id=semester_id,
        skip=skip,
        limit=limit,
    )
    return CourseListResponse(
        semester_id=semester_id,
        total=total,
        items=[CourseRead.model_validate(c) for c in courses],
    )


# ── GET /courses/{course_id} — Get single ─────────────────────────────────────

@router.get(
    "/{course_id}",
    response_model=CourseRead,
    status_code=status.HTTP_200_OK,
    summary="Get course",
    description="Admin-only. Return a single course by UUID.",
    operation_id="get_course",
)
async def get_course(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> CourseRead:
    """
    Return a single course by UUID.

    200 OK        — course found.
    404 Not Found — no course with that UUID.
    """
    course = await course_service.get_course_by_id(db=db, course_id=course_id)
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Course {course_id} not found.",
        )
    return CourseRead.model_validate(course)


# ── PATCH /courses/{course_id} — Update ──────────────────────────────────────

@router.patch(
    "/{course_id}",
    response_model=CourseRead,
    status_code=status.HTTP_200_OK,
    summary="Update course",
    description=(
        "Admin-only. Partially update a course's name, code, and/or tier. "
        "semester_id cannot be changed — delete and recreate in the target semester. "
        "code must be unique within the course's current semester. "
        "An empty body {} is a valid no-op."
    ),
    operation_id="update_course",
)
async def update_course(
    course_id: uuid.UUID,
    body: CourseUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> CourseRead:
    """
    Partially update a course.

    200 OK        — update applied (or no-op if body was empty).
    404 Not Found — no course with that UUID.
    409 Conflict  — new code already taken in this semester.
    422 Unprocessable — invalid tier value.
    """
    try:
        course = await course_service.update_course(
            db=db,
            course_id=course_id,
            data=body,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise _handle_value_error(exc)

    return CourseRead.model_validate(course)


# ── DELETE /courses/{course_id} — Hard delete ─────────────────────────────────

@router.delete(
    "/{course_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete course",
    description=(
        "Admin-only. Permanently delete a course. "
        "All associated course assignments and timetable entries "
        "are automatically deleted via CASCADE. "
        "This action is irreversible."
    ),
    operation_id="delete_course",
)
async def delete_course(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> None:
    """
    Hard-delete a course and all its cascaded data.

    204 No Content — course deleted.
    404 Not Found  — no course with that UUID.
    """
    try:
        await course_service.delete_course(db=db, course_id=course_id)
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise _handle_value_error(exc)
