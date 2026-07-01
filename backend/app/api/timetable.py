"""
api/timetable.py — Timetable generation, viewing, and export endpoints.

All endpoints require role = ADMIN (enforced via Depends(require_admin)).

Endpoint map:

  POST   /api/v1/timetable/generate
         Generate a new timetable for the active semester.
         Body: {"semester_id": "<uuid>"}
         Returns: GenerateResponse (timetable_id, warnings, conflict_count)

  GET    /api/v1/timetable/active/{semester_id}
         Get the current ACTIVE timetable header for a semester.
         Returns: TimetableRead or 404 if no timetable has been generated.

  GET    /api/v1/timetable/{timetable_id}/entries
         Get timetable session entries with optional filters + pagination.
         Query params: ?section_id= ?faculty_id= ?room_id= ?day= ?skip= ?limit=
         Returns: TimetableEntriesResponse

  GET    /api/v1/timetable/{timetable_id}/conflicts
         Get the conflict report for a timetable.
         Returns: ConflictReportRead

  DELETE /api/v1/timetable/{timetable_id}
         Hard-delete a timetable (CASCADE removes entries + conflict report).
         Returns: 204 No Content

  GET    /api/v1/timetable/{timetable_id}/export
         Export timetable as a CSV file download.
         Query params: ?export_type=SECTION|FACULTY|ROOM|FULL &filter_id=<uuid>
         Returns: text/csv with Content-Disposition: attachment

Design principles:
  - Thin routes: validate → call service → return schema.
  - ValueError → HTTP status via _handle_value_error helper.
  - Generation wraps in try/commit + except/rollback (large transaction).
  - All endpoints have unique operation_id for OpenAPI client generation.

Route ordering:
  /generate must be registered BEFORE /{timetable_id} to avoid FastAPI
  matching "generate" as a UUID path parameter.
  /active/{semester_id} must also come before /{timetable_id}.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin
from app.models.enums import DayOfWeek
from app.models.user import User
from app.schemas.timetable import (
    ConflictReportRead,
    ExportType,
    GenerateRequest,
    GenerateResponse,
    TimetableEntriesResponse,
    TimetableEntryRead,
    TimetableRead,
)
from app.services import timetable_service

router = APIRouter(
    prefix="/timetable",
    tags=["timetable"],
)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _handle_value_error(exc: ValueError) -> HTTPException:
    """
    Convert a service-layer ValueError to the appropriate HTTPException.

    Mapping:
      message contains "not found"       → 404 Not Found
      message contains "not active"      → 400 Bad Request
        (semester is not the active one)
      message contains "no course"       → 400 Bad Request
        (no assignments to schedule)
      message contains "required"        → 400 Bad Request
        (missing required filter)
      anything else                      → 400 Bad Request
    """
    message = str(exc)
    low = message.lower()

    if "not found" in low:
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=message,
        )
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=message,
    )


# ── POST /timetable/generate ─────────────────────────────────────────────────

@router.post(
    "/generate",
    response_model=GenerateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate timetable",
    description=(
        "Admin-only. Generate a new timetable for the active semester. "
        "The previous ACTIVE timetable (if any) becomes a SNAPSHOT. "
        "The previous SNAPSHOT (if any) is deleted. "
        "Returns the new timetable_id, any pre-generation warnings, "
        "and the count of sessions that could not be scheduled."
    ),
    operation_id="generate_timetable",
)
async def generate_timetable(
    body: GenerateRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> GenerateResponse:
    """
    Generate a new timetable.

    201 Created     — generation completed (even if some sessions are unscheduled;
                      check conflict_count to determine if conflicts exist).
    400 Bad Request — semester is not active, or no course assignments found.
    404 Not Found   — semester_id does not exist.
    """
    try:
        result = await timetable_service.generate_timetable(
            db=db,
            semester_id=body.semester_id,
            admin_id=admin.id,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise _handle_value_error(exc)

    return GenerateResponse(
        timetable_id=result["timetable_id"],
        warnings=result["warnings"],
        conflict_count=result["conflict_count"],
        snapshot_id=result["snapshot_id"],
    )


# ── GET /timetable/active/{semester_id} ──────────────────────────────────────

@router.get(
    "/active/{semester_id}",
    response_model=TimetableRead,
    status_code=status.HTTP_200_OK,
    summary="Get active timetable",
    description=(
        "Admin-only. Return the ACTIVE timetable header for a semester. "
        "Returns 404 if no timetable has been generated yet."
    ),
    operation_id="get_active_timetable",
)
async def get_active_timetable(
    semester_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> TimetableRead:
    """
    Return the ACTIVE timetable for a semester.

    200 OK        — timetable found.
    404 Not Found — no ACTIVE timetable for this semester.
    """
    timetable = await timetable_service.get_active_timetable(
        db=db, semester_id=semester_id
    )
    if timetable is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active timetable found for semester {semester_id}.",
        )
    return TimetableRead.model_validate(timetable)


# ── GET /timetable/{timetable_id}/entries ─────────────────────────────────────

@router.get(
    "/{timetable_id}/entries",
    response_model=TimetableEntriesResponse,
    status_code=status.HTTP_200_OK,
    summary="List timetable entries",
    description=(
        "Admin-only. Return session entries for a timetable, "
        "with optional filters by section, faculty, room, and/or day. "
        "Ordered by day then start_slot. "
        "Supports ?skip and ?limit pagination."
    ),
    operation_id="list_timetable_entries",
)
async def list_timetable_entries(
    timetable_id: uuid.UUID,
    section_id: uuid.UUID | None = Query(default=None, description="Filter by section UUID."),
    faculty_id: uuid.UUID | None = Query(default=None, description="Filter by faculty UUID."),
    room_id: uuid.UUID | None = Query(default=None, description="Filter by room UUID."),
    day: DayOfWeek | None = Query(default=None, description="Filter by day: MON|TUE|WED|THU|FRI."),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> TimetableEntriesResponse:
    """
    Return timetable entries with optional filters.

    200 OK — always (empty list if no entries match).
    """
    day_str = day.value if day is not None else None
    total, entries = await timetable_service.get_timetable_entries(
        db=db,
        timetable_id=timetable_id,
        section_id=section_id,
        faculty_id=faculty_id,
        room_id=room_id,
        day=day_str,
        skip=skip,
        limit=limit,
    )
    return TimetableEntriesResponse(
        timetable_id=timetable_id,
        total=total,
        items=[TimetableEntryRead.model_validate(e) for e in entries],
    )


# ── GET /timetable/{timetable_id}/conflicts ───────────────────────────────────

@router.get(
    "/{timetable_id}/conflicts",
    response_model=ConflictReportRead,
    status_code=status.HTTP_200_OK,
    summary="Get conflict report",
    description=(
        "Admin-only. Return the conflict report for a timetable. "
        "An empty conflicts list means all sessions were successfully scheduled. "
        "Non-empty means some sessions could not be placed — see reason_code "
        "and reason_detail for guidance."
    ),
    operation_id="get_conflict_report",
)
async def get_conflict_report(
    timetable_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> ConflictReportRead:
    """
    Return the conflict report for a timetable.

    200 OK        — report returned (may have zero conflicts).
    404 Not Found — timetable not found.
    """
    try:
        result = await timetable_service.get_conflict_report(
            db=db, timetable_id=timetable_id
        )
    except ValueError as exc:
        raise _handle_value_error(exc)

    from app.schemas.timetable import ConflictItemRead
    return ConflictReportRead(
        timetable_id=result["timetable_id"],
        total=result["total"],
        conflicts=result["conflicts"],
    )


# ── DELETE /timetable/{timetable_id} ──────────────────────────────────────────

@router.delete(
    "/{timetable_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete timetable",
    description=(
        "Admin-only. Permanently delete a timetable. "
        "All timetable entries and the conflict report are automatically "
        "deleted via CASCADE. "
        "The admin can then call POST /generate to create a new one."
    ),
    operation_id="delete_timetable",
)
async def delete_timetable(
    timetable_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> None:
    """
    Hard-delete a timetable and all its cascaded data.

    204 No Content — deleted.
    404 Not Found  — timetable not found.
    """
    try:
        await timetable_service.delete_timetable(
            db=db, timetable_id=timetable_id
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise _handle_value_error(exc)


# ── GET /timetable/{timetable_id}/export ──────────────────────────────────────

@router.get(
    "/{timetable_id}/export",
    status_code=status.HTTP_200_OK,
    summary="Export timetable as CSV",
    description=(
        "Admin-only. Export timetable entries as a downloadable CSV file. "
        "export_type controls the scope: "
        "SECTION (requires filter_id=section_uuid), "
        "FACULTY (requires filter_id=user_uuid), "
        "ROOM (requires filter_id=room_uuid), "
        "FULL (no filter_id needed — exports everything). "
        "Response: text/csv with Content-Disposition attachment."
    ),
    operation_id="export_timetable_csv",
    response_class=Response,
)
async def export_timetable_csv(
    timetable_id: uuid.UUID,
    export_type: ExportType = Query(
        default=ExportType.FULL,
        description="Export scope: SECTION | FACULTY | ROOM | FULL.",
    ),
    filter_id: uuid.UUID | None = Query(
        default=None,
        description=(
            "UUID of the entity to filter by (section, faculty, or room). "
            "Required for SECTION, FACULTY, ROOM exports. "
            "Ignored for FULL exports."
        ),
    ),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> Response:
    """
    Export timetable as a CSV file.

    200 OK        — returns text/csv file.
    400 Bad Request — filter_id missing for non-FULL export.
    404 Not Found   — timetable not found.
    """
    try:
        csv_string, filename = await timetable_service.export_timetable_csv(
            db=db,
            timetable_id=timetable_id,
            export_type=export_type.value,
            filter_id=filter_id,
        )
    except ValueError as exc:
        raise _handle_value_error(exc)

    return Response(
        content=csv_string,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
