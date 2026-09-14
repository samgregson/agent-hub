from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from agent_hub_api.health import ReadinessCheck, check_database
from agent_hub_api.health import router as health_router
from agent_hub_api.modules.agent_execution import (
    AgentExecutionModule,
    PostgresDeepAgentRunner,
    create_postgres_agent_execution,
)
from agent_hub_api.modules.agent_transport import (
    AgentTransportModule,
    create_agent_transport_router,
)
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
    agent_execution: AgentExecutionModule | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    resolved_identity = identity or create_identity_module(resolved_settings)
    resolved_projects = projects or create_postgres_project_module(resolved_settings)
    deep_agent_runner = None
    if agent_execution is None:
        deep_agent_runner = PostgresDeepAgentRunner(resolved_settings)
        resolved_agent_execution = create_postgres_agent_execution(
            resolved_settings, deep_agent_runner
        )
    else:
        resolved_agent_execution = agent_execution

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if deep_agent_runner is not None:
            await deep_agent_runner.close()

    application = FastAPI(
        description="Agent Hub foundation API",
        title="Agent Hub API",
        version="0.0.0",
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    application.state.readiness_check = readiness_check
    application.include_router(health_router)
    application.include_router(
        create_project_router(resolved_identity, resolved_projects), prefix="/api"
    )
    application.include_router(
        create_agent_transport_router(
            resolved_identity,
            AgentTransportModule(resolved_projects, resolved_agent_execution),
        ),
        prefix="/api",
    )
    return application


app = create_app()
