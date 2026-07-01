"""
FastAPI application entry point.

Responsibilities:
1. Create the FastAPI app with metadata
2. Configure CORS middleware
3. Mount API routers (added in later chunks)
4. Health-check endpoint
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown hooks."""
    # Startup: nothing needed yet (engine creates pool lazily)
    yield
    # Shutdown: dispose the connection pool
    from app.core.database import engine
    await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "Smart Academic Timetable Generator — conflict-free scheduling "
        "using graph coloring, constraint satisfaction, and optimization."
    ),
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health check ──────────────────────────────────────────────────────
@app.get("/health", tags=["system"])
async def health_check():
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
    }


# ── API routers ───────────────────────────────────────────────────────
# Import order follows dependency order: auth first (no deps), then
# resource routers (depend on auth), then timetable (depends on resources).
from app.api import auth as auth_router                   # noqa: E402
from app.api import users as users_router                 # noqa: E402
from app.api import semesters as semesters_router         # noqa: E402
from app.api import sections as sections_router           # noqa: E402
from app.api import rooms as rooms_router                 # noqa: E402
from app.api import courses as courses_router             # noqa: E402
from app.api import assignments as assignments_router     # noqa: E402
from app.api import availability as availability_router   # noqa: E402
from app.api import timetable as timetable_router         # noqa: E402

app.include_router(auth_router.router,          prefix="/api/v1")
app.include_router(users_router.router,         prefix="/api/v1")
app.include_router(semesters_router.router,     prefix="/api/v1")
app.include_router(sections_router.router,      prefix="/api/v1")
app.include_router(rooms_router.router,         prefix="/api/v1")
app.include_router(courses_router.router,       prefix="/api/v1")
app.include_router(assignments_router.router,   prefix="/api/v1")
app.include_router(availability_router.router,  prefix="/api/v1")
app.include_router(timetable_router.router,     prefix="/api/v1")








