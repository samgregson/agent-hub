from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from agent_hub_api.health import ReadinessCheck, check_database
from agent_hub_api.health import router as health_router
from agent_hub_api.settings import Settings, get_settings


def create_app(
    *,
    settings: Settings | None = None,
    readiness_check: ReadinessCheck = check_database,
) -> FastAPI:
    resolved_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.settings = resolved_settings
        application.state.readiness_check = readiness_check
        yield

    application = FastAPI(
        description="Agent Hub foundation API",
        lifespan=lifespan,
        title="Agent Hub API",
        version="0.0.0",
    )
    application.include_router(health_router)
    return application


app = create_app()
