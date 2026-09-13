from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from psycopg import AsyncConnection

from agent_hub_api.settings import Settings

ReadinessCheck = Callable[[Settings], Awaitable[None]]


async def check_database(settings: Settings) -> None:
    """Raise when PostgreSQL cannot serve a trivial query."""

    connection = await AsyncConnection.connect(
        str(settings.database_url),
        connect_timeout=settings.database_connect_timeout_seconds,
    )
    async with connection:
        await connection.execute("SELECT 1")


router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", responses={503: {"description": "A required dependency is unavailable"}})
async def readiness(request: Request) -> JSONResponse:
    settings: Settings = request.app.state.settings
    readiness_check: ReadinessCheck = request.app.state.readiness_check

    try:
        await readiness_check(settings)
    except Exception:
        return JSONResponse({"status": "unavailable"}, status_code=503)

    return JSONResponse({"status": "ready"})
