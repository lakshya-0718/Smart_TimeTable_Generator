# PROJECT CONTEXT

This document serves as the master technical reference for the **Smart Timetable Generator** project. It is designed to quickly onboard other developers or AI assistants to the architecture, design patterns, and state of the system.

## 1. Project Overview
A full-stack application designed to automate university course scheduling. It takes in various entities (Rooms, Faculty, Sections, Courses) and their constraints, and uses a custom AI engine to generate conflict-free academic timetables.

## 2. Architecture
- **Frontend**: React 18, Vite, TypeScript, TailwindCSS, React Hook Form, Headless UI (Heroicons). Implements a glassmorphism/gradient aesthetic.
- **Backend**: FastAPI, Python 3.12, Pydantic, SQLAlchemy 2.0 (Async).
- **Database**: SQLite (via `aiosqlite`) with Alembic for schema migrations.

## 3. Folder Structure
- `backend/app/api/`: FastAPI route definitions, organized by domain.
- `backend/app/services/`: Pure business logic. Route handlers call these services.
- `backend/app/models/`: SQLAlchemy ORM models.
- `backend/app/schemas/`: Pydantic models for request/response validation.
- `backend/app/engine/`: The core constraint-based scheduling algorithm.
- `frontend/src/pages/`: Main UI views (Dashboard, Rooms, Users, etc.).
- `frontend/src/services/`: Axios-based API client methods.
- `frontend/src/components/common/`: Reusable UI elements (Modals, Alerts, DataTables).

## 4. Database Entities & Relationships
- **Semester**: The root entity. Has many Courses, Assignments, and Timetables. Can be Active/Inactive.
- **User**: Single table representing Admin, Faculty, and TA roles. 
  - 1:N with `FacultyAvailability` and `TAAvailability`.
- **Room**: Physical spaces. Typed as `LECTURE_HALL` or `LAB`.
- **Section**: Student cohorts (e.g., Year 1, Label A).
- **Course**: Curriculum definitions categorized by Credit Patterns (Tiers 1 to 4).
- **CourseAssignment**: The central atom binding a Course, Section, Faculty, and (optionally) TA together.
- **Timetable & TimetableEntry**: The generated output. Entries tie back to Assignments, Rooms, and specific time blocks.

## 5. Scheduling Engine Architecture
Located in `backend/app/engine/`. It operates primarily on the `CourseAssignment` entity.
1. **Context Initialization**: Gathers all constraints, assignments, availability, and active rooms.
2. **Deconstruction**: Expands a single `CourseAssignment` into distinct `Session` requirements based on the Course Tier:
   - *Tier 1*: 3x 1hr Lecture, 1x 1hr Tutorial, 1x 2hr Practical.
   - *Tier 2*: 3x 1hr Lecture, 1x 1hr Tutorial.
   - *Tier 3*: 1x 4hr Lab.
   - *Tier 4*: 1x 2hr Lab.
3. **Placement Logic**: Backtracking/Heuristic search to place sessions into a standard weekly grid (Mon-Fri, 8 AM - 5 PM).

## 6. Constraint Engine Rules
- **Lunch Break**: Hard constraint. No classes scheduled between 12:00 PM - 1:00 PM.
- **Availability Constraints**: The engine checks the `unavailability` arrays for Faculty and TAs before slotting.
- **Role Display Logic**:
  - Lectures = Faculty only.
  - Tutorials = TA only.
  - Labs = Both Faculty and TA.
- **Room Types**: Lectures/Tutorials strictly require `LECTURE_HALL`. Labs strictly require `LAB`.
- **Overlap Prevention**: Strict checks prevent Faculty, TA, Room, and Section double-booking.

## 7. Generation & Export Workflow
1. **Trigger**: Admin selects a Semester and hits "Generate Timetable".
2. **Backend Engine**: Flushes any existing `Timetable` for that semester and recalculates from scratch. Returns the new entries.
3. **Frontend Render**: The `Timetable Management` page maps the JSON response onto an interactive CSS grid.
4. **Export**: CSV parsing logic on the frontend processes the current filtered view (Full, by Section, by Faculty) and triggers a browser blob download.

## 8. Known Design Decisions
- **Unified User Table**: Admin, Faculty, and TAs share one `users` table discriminated by a `role` enum. This simplifies authentication and foreign key targeting.
- **Soft Deletion & Restrictions**: Assignments rely on `ON DELETE RESTRICT` for Faculty. To delete a user, they must first be unassigned.
- **Stateless Engine**: The scheduling engine pulls data, runs entirely in memory, and then bulk-inserts the final state. It does not update the database midway through calculation.

## 9. Current Completed State
- Full CRUD operations for all foundational entities.
- Complex constraint-based generation is functional.
- Glassmorphism UI is fully integrated and responsive.
- Delete capabilities for Users and Semesters have been implemented safely.

## 10. Remaining Improvements
- Handling of part-time Faculty load balancing.
- Providing visual "soft" warnings if a teacher is scheduled for too many consecutive hours.
- Adding a dedicated Faculty/TA login portal for them to mark their own unavailability.
