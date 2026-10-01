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
from agent_hub_api.modules.artifacts import (
    ArtifactModule,
    create_artifact_router,
    create_postgres_artifact_module,
)
from agent_hub_api.modules.batch_execution import (
    create_batch_execution_router,
    create_postgres_batch_execution_module,
)
from agent_hub_api.modules.datasets import create_dataset_router, create_postgres_dataset_module
from agent_hub_api.modules.identity import IdentityModule, create_identity_module
from agent_hub_api.modules.plugin_gateway import (
    PluginGatewayModule,
    create_plugin_gateway_router,
    create_postgres_plugin_gateway,
)
from agent_hub_api.modules.project_files import (
    create_postgres_project_files,
    create_project_files_router,
)
from agent_hub_api.modules.projects import (
    ProjectModule,
    create_postgres_project_module,
    create_project_router,
)
from agent_hub_api.modules.transforms import (
    create_postgres_transform_module,
    create_transform_router,
)
from agent_hub_api.settings import Settings, get_settings


def create_app(
    *,
    settings: Settings | None = None,
    readiness_check: ReadinessCheck = check_database,
    identity: IdentityModule | None = None,
    projects: ProjectModule | None = None,
    agent_execution: AgentExecutionModule | None = None,
    plugin_gateway: PluginGatewayModule | None = None,
    artifacts: ArtifactModule | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    resolved_identity = identity or create_identity_module(resolved_settings)
    resolved_projects = projects or create_postgres_project_module(resolved_settings)
    resolved_project_files = create_postgres_project_files(resolved_settings, resolved_projects)
    resolved_plugin_gateway = plugin_gateway or create_postgres_plugin_gateway(
        resolved_settings,
        resolved_projects,
    )
    resolved_artifacts = artifacts or create_postgres_artifact_module(
        resolved_settings,
        resolved_projects,
        resolved_plugin_gateway,
    )
    resolved_datasets = create_postgres_dataset_module(
        resolved_settings, resolved_projects, resolved_plugin_gateway
    )
    resolved_batches = create_postgres_batch_execution_module(
        resolved_settings, resolved_projects, resolved_datasets, resolved_plugin_gateway
    )
    resolved_transforms = create_postgres_transform_module(
        resolved_settings, resolved_projects, datasets=resolved_datasets
    )
    deep_agent_runner = None
    if agent_execution is None:
        deep_agent_runner = PostgresDeepAgentRunner(
            resolved_settings,
            resolved_project_files,
            resolved_plugin_gateway,
            resolved_artifacts,
            resolved_datasets,
            resolved_batches,
            resolved_transforms,
        )
        resolved_agent_execution = create_postgres_agent_execution(
            resolved_settings, deep_agent_runner
        )
    else:
        resolved_agent_execution = agent_execution

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await resolved_agent_execution.reconcile_non_terminal()
        await resolved_batches.recover()
        await resolved_transforms.recover()
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
        create_project_files_router(resolved_identity, resolved_project_files),
        prefix="/api",
    )
    application.include_router(
        create_artifact_router(resolved_identity, resolved_artifacts), prefix="/api"
    )
    application.include_router(
        create_dataset_router(resolved_identity, resolved_datasets), prefix="/api"
    )
    application.include_router(
        create_batch_execution_router(resolved_identity, resolved_batches),
        prefix="/api",
    )
    application.include_router(
        create_transform_router(resolved_identity, resolved_transforms), prefix="/api"
    )
    application.include_router(
        create_plugin_gateway_router(resolved_identity, resolved_plugin_gateway),
        prefix="/api",
    )
    application.include_router(
        create_agent_transport_router(
            resolved_identity,
            AgentTransportModule(
                resolved_projects, resolved_agent_execution, resolved_project_files
            ),
        ),
        prefix="/api",
    )
    return application


app = create_app()
