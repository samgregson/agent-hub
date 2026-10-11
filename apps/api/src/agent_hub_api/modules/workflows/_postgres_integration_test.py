import pytest
from psycopg import AsyncConnection, OperationalError
from pydantic import PostgresDsn

from agent_hub_api.modules.datasets import DatasetRecordInput, create_postgres_dataset_module
from agent_hub_api.modules.projects import ProjectAccess, create_postgres_project_module
from agent_hub_api.modules.transforms import create_postgres_transform_module
from agent_hub_api.modules.workflows import (
    WorkflowGraph,
    WorkflowNode,
    WorkflowOutput,
    create_postgres_workflow_module,
)
from agent_hub_api.settings import Settings


@pytest.mark.asyncio
async def test_workflow_definition_round_trips_through_postgres() -> None:
    settings = Settings(
        environment="test",
        database_url=PostgresDsn("postgresql://agent_hub:agent_hub@127.0.0.1:5432/agent_hub"),
    )
    try:
        connection = await AsyncConnection.connect(str(settings.database_url))
    except OperationalError:
        pytest.skip("Local PostgreSQL is unavailable")
    await connection.close()

    class Schemas:
        async def input_schema(self, *_: object) -> dict[str, object]:
            return {"type": "object"}

    access = ProjectAccess(subject="workflow-postgres-integration")
    projects = create_postgres_project_module(settings)
    datasets = create_postgres_dataset_module(settings, projects, Schemas())
    transforms = create_postgres_transform_module(settings, projects)
    workflows = create_postgres_workflow_module(settings, projects, datasets, transforms, None)
    project = await projects.create(access, "Workflow integration")
    try:
        dataset = await datasets.create_dataset(
            access, project.id, "Inputs", [DatasetRecordInput({"value": 2})]
        )
        graph = WorkflowGraph(
            (WorkflowNode("source", "dataset", dataset.id, dataset.version),),
            (),
            (WorkflowOutput("records", "source", "records"),),
        )
        saved = await workflows.create(access, project.id, "Inspection", graph)
        assert await workflows.load(access, project.id, saved.id) == saved
        assert [item.id for item in await workflows.list(access, project.id)] == [saved.id]
        revised = await workflows.revise(
            access, project.id, saved.id, "Revised", graph, expected_version=1
        )
        assert (await workflows.load(access, project.id, saved.id)).version == revised.version == 2
    finally:
        connection = await AsyncConnection.connect(str(settings.database_url))
        async with connection:
            await connection.execute("DELETE FROM projects WHERE id=%s", (project.id,))
