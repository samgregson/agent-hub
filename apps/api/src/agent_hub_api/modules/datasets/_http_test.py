from typing import cast

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from agent_hub_api.modules.batch_execution import BatchExecutionModule, MemoryBatchRunStore
from agent_hub_api.modules.datasets import (
    DatasetModule,
    MemoryDatasetStore,
    create_dataset_router,
)
from agent_hub_api.modules.identity import create_identity_module
from agent_hub_api.modules.plugin_gateway import PluginGatewayModule
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module
from agent_hub_api.modules.transforms import (
    MemoryTransformStore,
    TransformModule,
    TransformRuntimeIdentity,
)
from agent_hub_api.settings import Settings


class ToolSchemas:
    async def input_schema(self, *_: object) -> dict[str, object]:
        return {
            "type": "object",
            "required": ["length_m"],
            "properties": {"length_m": {"type": "number"}},
        }


@pytest.mark.asyncio
async def test_direct_user_dataset_and_definition_actions_are_project_scoped() -> None:
    settings = Settings(environment="test", fixed_identity_subject="sam")
    projects = create_memory_project_module()
    datasets = DatasetModule(projects, MemoryDatasetStore(), ToolSchemas())
    app = FastAPI()
    app.include_router(
        create_dataset_router(create_identity_module(settings), datasets), prefix="/api"
    )
    project = await projects.create(ProjectAccess(subject="sam"), "Bridge")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            f"/api/projects/{project.id}/datasets",
            json={
                "name": "Loads",
                "records": [{"sourceKey": "LC-1", "value": {"length": 2}}],
            },
        )
        dataset = created.json()
        definition = await client.post(
            f"/api/projects/{project.id}/batch-definitions",
            json={
                "datasetId": dataset["id"],
                "name": "Calculate",
                "pluginId": "reference-calculation",
                "toolName": "calculate_cantilever_tip_load",
                "argumentMappings": {"length_m": "/length"},
            },
        )
        deleted = await client.delete(f"/api/projects/{project.id}/datasets/{dataset['id']}")
        listed = await client.get(f"/api/projects/{project.id}/batch-definitions")

    assert created.status_code == 201
    assert dataset["records"][0]["position"] == 0
    assert definition.status_code == 201
    assert deleted.status_code == 204
    assert listed.json()[0]["datasetAvailable"] is False


@pytest.mark.asyncio
async def test_user_can_save_a_transform_targeted_batch_definition() -> None:
    settings = Settings(environment="test", fixed_identity_subject="sam")
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="sam")
    project = await projects.create(owner, "Bridge")
    datasets = DatasetModule(projects, MemoryDatasetStore(), ToolSchemas())
    dataset = await datasets.create_dataset(owner, project.id, "Loads", [])

    class Runner:
        async def identity(self) -> TransformRuntimeIdentity:
            return TransformRuntimeIdentity("deno:test;pyodide:test", "a" * 64)

        async def execute(
            self, source: str, inputs: dict[str, object], parameters: dict[str, object]
        ) -> tuple[object, str]:
            return inputs, "deno:test;pyodide:test"

    transforms = TransformModule(projects, MemoryTransformStore(), Runner())
    transform = await transforms.define(
        owner, project.id, "Double", "def transform(inputs, parameters):\n    return {}\n",
        {"load": "/load"}, {"type": "object"},
    )
    batches = BatchExecutionModule(
        projects, datasets, cast(PluginGatewayModule, object()),
        MemoryBatchRunStore(), transforms=transforms,
    )
    app = FastAPI()
    app.include_router(
        create_dataset_router(create_identity_module(settings), datasets, batches),
        prefix="/api",
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            f"/api/projects/{project.id}/batch-definitions",
            json={
                "name": "Double loads", "datasetId": dataset.id,
                "transformDefinitionId": transform.id,
            },
        )
        listed = await client.get(f"/api/projects/{project.id}/batch-definitions")

    assert created.status_code == 201
    assert created.json()["transformDefinitionId"] == transform.id
    assert created.json()["pluginId"] is None
    assert listed.json()[0]["id"] == created.json()["id"]
