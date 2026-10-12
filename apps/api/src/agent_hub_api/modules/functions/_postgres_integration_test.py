import pytest
from psycopg import AsyncConnection, OperationalError
from pydantic import PostgresDsn

from agent_hub_api.modules.functions import create_postgres_function_module
from agent_hub_api.modules.projects import ProjectAccess, create_postgres_project_module
from agent_hub_api.settings import Settings


@pytest.mark.asyncio
async def test_function_definition_round_trips_through_postgres() -> None:
    settings = Settings(
        environment="test",
        database_url=PostgresDsn("postgresql://agent_hub:agent_hub@127.0.0.1:5432/agent_hub"),
    )
    try:
        connection = await AsyncConnection.connect(str(settings.database_url))
    except OperationalError:
        pytest.skip("Local PostgreSQL is unavailable")
    await connection.close()

    access = ProjectAccess(subject="function-postgres-integration")
    projects = create_postgres_project_module(settings)
    functions = create_postgres_function_module(settings, projects)
    project = await projects.create(access, "Function integration")
    input_schema = {
        "type": "object",
        "properties": {"load": {"type": "number"}},
        "required": ["load"],
        "additionalProperties": False,
    }
    try:
        function = await functions.define(
            access,
            project.id,
            "Double",
            "def transform(inputs, parameters):\n    return {'value': inputs['load'] * 2}\n",
            input_schema,
            {"type": "object", "properties": {"value": {"type": "number"}}},
        )
        assert await functions.load(access, project.id, function.id) == function
        assert await functions.list(access, project.id) == (function,)

        revised = await functions.revise(
            access,
            project.id,
            function.id,
            "Triple",
            "def transform(inputs, parameters):\n    return {'value': inputs['load'] * 3}\n",
            input_schema,
            {"type": "object", "properties": {"value": {"type": "number"}}},
        )
        assert revised.revision == 2
        assert await functions.load(access, project.id, function.id) == revised
        await functions.delete(access, project.id, function.id)
        assert await functions.list(access, project.id) == ()
    finally:
        connection = await AsyncConnection.connect(str(settings.database_url))
        async with connection:
            await connection.execute("DELETE FROM projects WHERE id=%s", (project.id,))
