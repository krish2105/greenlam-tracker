"""Liveness and readiness.

`/health` is deliberately cheap and unauthenticated: it is what the GitHub
Actions keep-alive workflow pings during plant hours to keep Render awake, and
what an on-prem load balancer would poll. `/health/ready` touches the database,
so it tells you whether Neon has woken up too.
"""

from fastapi import APIRouter
from sqlalchemy import text

from ..config import get_settings
from ..deps import SessionDep
from ..schemas import HealthResponse

router = APIRouter(tags=["health"])
settings = get_settings()

VERSION = "0.1.0"


@router.get("/health", response_model=HealthResponse, summary="Liveness")
def health() -> HealthResponse:
    """Returns 200 as long as the process is up. Does not touch the database."""
    return HealthResponse(status="ok", version=VERSION, database="not_checked", env=settings.env)


@router.get("/health/ready", response_model=HealthResponse, summary="Readiness")
def ready(session: SessionDep) -> HealthResponse:
    """Confirms the database answers. Use this one before running a migration
    or an export, not for the keep-alive ping."""
    try:
        session.exec(text("SELECT 1"))
        db = "ok"
    except Exception:  # noqa: BLE001 - the status string is the whole point
        db = "unavailable"
    return HealthResponse(
        status="ok" if db == "ok" else "degraded",
        version=VERSION,
        database=db,
        env=settings.env,
    )
