import pytest
from psycopg import AsyncConnection, OperationalError
from pydantic import PostgresDsn

from agent_hub_api.modules.projects import ProjectAccess, create_postgres_project_module
from agent_hub_api.modules.transforms import create_postgres_transform_module
from agent_hub_api.settings import Settings


@pytest.mark.asyncio
async def test_transform_definition_round_trips_through_postgres() -> None:
    settings = Settings(
        environment="test",
        database_url=PostgresDsn("postgresql://agent_hub:agent_hub@127.0.0.1:5432/agent_hub"),
    )
    try:
        connection = await AsyncConnection.connect(str(settings.database_url))
    except OperationalError:
        pytest.skip("Local PostgreSQL is unavailable")
    await connection.close()

    access = ProjectAccess(subject="transform-postgres-integration")
    projects = create_postgres_project_module(settings)
    transforms = create_postgres_transform_module(settings, projects)
    project = await projects.create(access, "Transform integration")
    try:
        definition = await transforms.define(
            access, project.id, "Double", "def transform(inputs, parameters):\n    return {}\n",
            {"load": "/load"}, {"type": "object"},
        )
        loaded = await transforms.load(access, project.id, definition.id)
        assert loaded == definition
        assert (await transforms.list(access, project.id)) == (definition,)

        revised = await transforms.revise(
            access, project.id, definition.id, "Triple",
            "def transform(inputs, parameters):\n    return {'triple': 3}\n",
            {"load": "/load"}, {"type": "object"},
        )
        assert revised.revision == 2
        assert await transforms.load(access, project.id, definition.id) == revised
        await transforms.delete(access, project.id, definition.id)
        assert await transforms.list(access, project.id) == ()
    finally:
        connection = await AsyncConnection.connect(str(settings.database_url))
        async with connection:
            await connection.execute("DELETE FROM projects WHERE id=%s", (project.id,))
