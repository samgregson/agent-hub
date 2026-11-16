import pytest
from psycopg import AsyncConnection, OperationalError
from pydantic import PostgresDsn

from agent_hub_api.modules.plugin_gateway import create_postgres_plugin_gateway
from agent_hub_api.modules.projects import ProjectAccess, create_postgres_project_module
from agent_hub_api.settings import Settings


@pytest.mark.asyncio
async def test_new_projects_get_defaults_and_can_disable_them() -> None:
    settings = Settings(
        environment="test",
        database_url=PostgresDsn("postgresql://agent_hub:agent_hub@127.0.0.1:5432/agent_hub"),
    )
    try:
        connection = await AsyncConnection.connect(str(settings.database_url))
    except OperationalError:
        pytest.skip("Local PostgreSQL is unavailable")
    await connection.close()
    access = ProjectAccess(subject="plugin-default-integration")
    projects = create_postgres_project_module(settings)
    gateway = create_postgres_plugin_gateway(settings, projects)
    project = await projects.create(access, "Plugin defaults integration")
    try:
        selections = await gateway.selections(access, project.id)
        assert {item.manifest.id for item in selections if item.enabled} == {
            "ifc-viewer",
            "calculation-source-object",
        }
        await gateway.disable(access, project.id, "ifc-viewer")
        selections = await gateway.selections(access, project.id)
        assert {item.manifest.id for item in selections if item.enabled} == {
            "calculation-source-object"
        }
    finally:
        connection = await AsyncConnection.connect(str(settings.database_url))
        async with connection:
            await connection.execute("DELETE FROM projects WHERE id=%s", (project.id,))
