"""
services/section_service.py — Business logic for Section Management.

Responsibilities:
  - Create sections (with name uniqueness + year/label uniqueness checks).
  - List all sections (ordered by year ASC, label ASC).
  - Get a single section by UUID.
  - Update a section's strength.
  - Delete a section (guarded by RESTRICT FK on course_assignments).

Design principles:
  - NO HTTP knowledge.  No FastAPI, no HTTPException, no status codes.
    Business-rule violations raise plain ValueError.  The route layer
    (api/sections.py) converts these to HTTP responses.
  - Every function is async and receives an AsyncSession from DI.
  - SQLAlchemy 2.0 select() API throughout.
  - db.flush() after writes, never db.commit() — the route layer commits.

Name derivation:
  The service derives the canonical section name as f"Y{year}{label}"
  (e.g. year=2, label='A' → "Y2A").  This keeps the `name` column and the
  `(year, label)` composite unique constraint perfectly consistent.
  The admin never supplies `name` directly.

Delete guard:
  sections.id is referenced by course_assignments.section_id with
  ON DELETE RESTRICT.  Attempting to delete a section with live course
  assignments will raise an IntegrityError from PostgreSQL.  We catch this
  and convert it to a clear ValueError so the route can return 409 Conflict.
  We do NOT pre-check the count (that would be a TOCTOU race); instead we
  let the DB be the authoritative enforcer and catch the error.

Error contract:
  get_section_by_id → None if not found (route returns 404)
  create_section    → ValueError("Section Y{y}{l} already exists.")
                      if name or (year, label) is already taken
  update_section    → ValueError("Section not found.")
  delete_section    → ValueError("Section not found.")
                   → ValueError("Cannot delete section with live course assignments.")
                      if the RESTRICT FK fires
"""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.section import Section
from app.schemas.section import SectionCreate, SectionUpdate


# ── Name derivation ───────────────────────────────────────────────────────────

def _derive_name(year: int, label: str) -> str:
    """
    Compute the canonical section name from year and label.

    Convention: "Y{year}{label}", e.g. Y1A, Y2B, Y4A.
    This is the project's standard naming scheme documented in the
    database_schema.md examples.
    """
    return f"Y{year}{label}"


# ── Read helpers ──────────────────────────────────────────────────────────────

async def get_section_by_id(
    db: AsyncSession,
    section_id: uuid.UUID,
) -> Section | None:
    """
    Return the Section with the given UUID, or None if not found.

    Uses db.get() for identity-map cache benefit.
    """
    return await db.get(Section, section_id)


async def get_section_by_name(
    db: AsyncSession,
    name: str,
) -> Section | None:
    """Return the Section with the given name, or None."""
    result = await db.execute(
        select(Section).where(Section.name == name)
    )
    return result.scalars().first()


async def get_section_by_year_label(
    db: AsyncSession,
    year: int,
    label: str,
) -> Section | None:
    """
    Return the Section matching (year, label), or None.

    Used internally for the composite uniqueness check during creation.
    The DB also enforces uq_sections_year_label, but checking here first
    gives a cleaner error message than catching an IntegrityError.
    """
    result = await db.execute(
        select(Section).where(
            Section.year == year,
            Section.label == label,
        )
    )
    return result.scalars().first()


async def list_sections(db: AsyncSession) -> list[Section]:
    """
    Return all sections ordered by year ASC, label ASC.

    This ordering matches the natural academic grouping:
    Y1A, Y1B, Y2A, Y2B, Y3A, Y3B, Y4A, Y4B.

    No pagination — the system scope is exactly 8 sections.
    """
    result = await db.execute(
        select(Section).order_by(Section.year.asc(), Section.label.asc())
    )
    return list(result.scalars().all())


# ── Mutations ─────────────────────────────────────────────────────────────────

async def create_section(
    db: AsyncSession,
    data: SectionCreate,
) -> Section:
    """
    Create a new section.

    Steps:
      1. Derive canonical name from year + label.
      2. Check that no section with the same name exists.
      3. Check that no section with the same (year, label) exists.
         (Both checks are required because the DB has two separate unique
         constraints.  In practice they are redundant given the derivation
         rule, but checking explicitly produces a clean error message.)
      4. Create the Section ORM object and flush().

    Raises:
      ValueError — if the section already exists (name or year+label conflict).
    """
    name = _derive_name(data.year, data.label)

    # Check 1: name uniqueness
    existing_by_name = await get_section_by_name(db=db, name=name)
    if existing_by_name is not None:
        raise ValueError(f"Section '{name}' already exists.")

    # Check 2: (year, label) uniqueness — defensive, covers edge cases
    existing_by_yl = await get_section_by_year_label(
        db=db, year=data.year, label=data.label
    )
    if existing_by_yl is not None:
        raise ValueError(
            f"A section for Year {data.year}, Label '{data.label}' already exists "
            f"(as '{existing_by_yl.name}')."
        )

    section = Section(
        name=name,
        year=data.year,
        label=data.label,
        strength=data.strength,
    )

    db.add(section)
    await db.flush()
    await db.refresh(section)
    return section


async def update_section(
    db: AsyncSession,
    section_id: uuid.UUID,
    data: SectionUpdate,
) -> Section:
    """
    Update a section's strength.

    Uses model_fields_set for true PATCH semantics — an empty body {} is a
    valid no-op that returns the unchanged section.

    Only `strength` is updatable.  year, label, and name are structural
    identities that cannot change after creation.

    Raises:
      ValueError("Section not found.") — if section_id doesn't exist.
    """
    section = await get_section_by_id(db=db, section_id=section_id)
    if section is None:
        raise ValueError("Section not found.")

    if "strength" in data.model_fields_set and data.strength is not None:
        section.strength = data.strength

    await db.flush()
    await db.refresh(section)
    return section


async def delete_section(
    db: AsyncSession,
    section_id: uuid.UUID,
) -> None:
    """
    Hard-delete a section.

    Guard:
      course_assignments.section_id has ON DELETE RESTRICT.  PostgreSQL
      will raise an IntegrityError if any course assignment references this
      section.  We catch that error and re-raise as a ValueError so the
      route can return 409 Conflict with a clear message.

    This is the correct pattern for RESTRICT FKs:
      - Do NOT pre-check with a SELECT COUNT — that creates a TOCTOU race.
      - Let the DB enforce the constraint.
      - Catch IntegrityError and translate to a business-layer error.

    Raises:
      ValueError("Section not found.")
      ValueError("Cannot delete section with live course assignments. ...")
    """
    section = await get_section_by_id(db=db, section_id=section_id)
    if section is None:
        raise ValueError("Section not found.")

    try:
        await db.delete(section)
        await db.flush()
    except IntegrityError:
        # PostgreSQL raised the RESTRICT FK violation.
        # Roll back the flush to leave the session in a clean state.
        await db.rollback()
        raise ValueError(
            f"Cannot delete section '{section.name}' because it has live course "
            "assignments. Remove all course assignments for this section first."
        )
