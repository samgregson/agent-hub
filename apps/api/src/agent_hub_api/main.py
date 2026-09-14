from fastapi import FastAPI

from agent_hub_api.health import ReadinessCheck, check_database
from agent_hub_api.health import router as health_router
from agent_hub_api.modules.identity import IdentityModule, create_identity_module
from agent_hub_api.modules.projects import (
    ProjectModule,
    create_postgres_project_module,
    create_project_router,
)
from agent_hub_api.settings import Settings, get_settings


def create_app(
    *,
    settings: Settings | None = None,
    readiness_check: ReadinessCheck = check_database,
    identity: IdentityModule | None = None,
    projects: ProjectModule | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    resolved_identity = identity or create_identity_module(resolved_settings)
    resolved_projects = projects or create_postgres_project_module(resolved_settings)

    application = FastAPI(
        description="Agent Hub foundation API",
        title="Agent Hub API",
        version="0.0.0",
    )
    application.state.settings = resolved_settings
    application.state.readiness_check = readiness_check
    application.include_router(health_router)
    application.include_router(
        create_project_router(resolved_identity, resolved_projects), prefix="/api"
    )
    return application


app = create_app()
