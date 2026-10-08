from collections.abc import Sized

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from agent_hub_api.modules.artifacts import create_memory_artifact_module
from agent_hub_api.modules.datasets import DatasetModule, DatasetRecordInput, MemoryDatasetStore
from agent_hub_api.modules.identity import create_identity_module
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module
from agent_hub_api.modules.transforms import (
    MemoryTransformRunStore,
    MemoryTransformStore,
    TransformModule,
    TransformRuntimeIdentity,
    create_transform_router,
)
from agent_hub_api.settings import Settings


class _PinnedRunner:
    async def identity(self) -> TransformRuntimeIdentity:
        return TransformRuntimeIdentity("deno:2.9.7;pyodide:314.0.7", "a" * 64)


@pytest.mark.asyncio
async def test_selection_plan_precedes_one_durable_transform_run() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="sam")
    project = await projects.create(owner, "Selection")
    datasets = DatasetModule(projects, MemoryDatasetStore(), _NoToolSchema())
    data = await datasets.create_dataset(
        owner, project.id, "Values",
        [DatasetRecordInput({"score": 1}), DatasetRecordInput({"score": 3})],
    )

    class Runner(_PinnedRunner):
        async def execute(
            self, source: str, inputs: dict[str, object], parameters: dict[str, object]
        ) -> tuple[object, str]:
            items = inputs["items"]
            assert isinstance(items, Sized)
            return {"count": len(items)}, "deno:2.9.7;pyodide:314.0.7"

    transforms = TransformModule(
        projects, MemoryTransformStore(), Runner(), MemoryTransformRunStore(), datasets
    )
    definition = await transforms.define(
        owner, project.id, "Count",
        "def transform(inputs, parameters):\n    return {'count': len(inputs['items'])}\n",
        {"items": "/selection/values"}, {"type": "object"},
    )
    app = FastAPI()
    app.include_router(
        create_transform_router(
            create_identity_module(Settings(environment="test", fixed_identity_subject="sam")),
            transforms,
        ),
        prefix="/api",
    )
    root = f"/api/projects/{project.id}/transforms/{definition.id}"
    body = {
        "datasetId": data.id,
        "expectedVersion": data.version,
        "expectedDefinitionRevision": definition.revision,
        "sortPath": "/score",
        "descending": True,
        "limit": 1,
        "parameters": {},
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        plan = await client.post(f"{root}/selection-plan", json=body)
        assert plan.status_code == 200
        assert plan.json()["selectedCount"] == 1
        assert plan.json()["invocationCount"] == 1
        assert plan.json()["selection"]["recordIds"] == [data.records[1].id]
        started = await client.post(f"{root}/selection-runs", json=body)
        assert started.status_code == 201
        assert started.json()["output"] == {"count": 1}
        assert started.json()["definitionSnapshot"]["selection"]["recordIds"] == [
            data.records[1].id
        ]
        await datasets.update_dataset(
            owner, project.id, data.id, "Changed", [], expected_version=data.version
        )
        stale = await client.post(f"{root}/selection-runs", json=body)
        assert stale.status_code == 422
        assert "version" in stale.json()["detail"]


class _NoToolSchema:
    async def input_schema(self, *_: object) -> dict[str, object]:
        return {"type": "object"}


@pytest.mark.asyncio
async def test_direct_user_explicitly_saves_run_output_as_artifact() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="sam")
    project = await projects.create(owner, "Bridge")

    class Runner(_PinnedRunner):
        async def execute(
            self, source: str, inputs: dict[str, object], parameters: dict[str, object]
        ) -> tuple[object, str]:
            return {"value": 6}, "deno:2.9.7;pyodide:314.0.7"

    transforms = TransformModule(
        projects, MemoryTransformStore(), Runner(), MemoryTransformRunStore(),
        artifacts=create_memory_artifact_module(projects),
    )
    definition = await transforms.define(
        owner, project.id, "Double", "def transform(inputs, parameters):\n    return {}\n",
        {"load": "/load"}, {"type": "object"},
    )
    run = await transforms.start_run(owner, project.id, definition.id, {"load": 3}, {})
    app = FastAPI()
    app.include_router(
        create_transform_router(
            create_identity_module(Settings(environment="test", fixed_identity_subject="sam")),
            transforms,
        ),
        prefix="/api",
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        saved = await client.post(
            f"/api/projects/{project.id}/transforms/runs/{run.id}/save-artifact",
            json={"title": "Checked loads"},
        )

    assert saved.status_code == 201
    assert saved.json()["artifact"]["title"] == "Checked loads"
    assert saved.json()["artifact"]["provenance"]["createdBy"]["kind"] == "userAction"
    assert saved.json()["payload"]["transformRunId"] == run.id


@pytest.mark.asyncio
async def test_transform_definition_http_round_trip() -> None:
    projects = create_memory_project_module()
    project = await projects.create(ProjectAccess(subject="sam"), "Bridge")
    app = FastAPI()
    app.include_router(
        create_transform_router(
            create_identity_module(Settings(environment="test", fixed_identity_subject="sam")),
            TransformModule(projects, MemoryTransformStore()),
        ),
        prefix="/api",
    )
    path = f"/api/projects/{project.id}/transforms"
    body = {
        "name": "Double loads",
        "source": "def transform(inputs, parameters):\n    return {}\n",
        "inputSelectors": {"load": "/load"},
        "outputSchema": {"type": "object"},
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(path, json=body)
        assert created.status_code == 201
        definition_id = created.json()["id"]
        loaded = await client.get(f"{path}/{definition_id}")
        listed = await client.get(path)
        invalid = await client.put(f"{path}/{definition_id}", json={**body, "source": " "})
        deleted = await client.delete(f"{path}/{definition_id}")
        missing = await client.get(f"{path}/{definition_id}")

    assert loaded.json()["sourceHash"] == created.json()["sourceHash"]
    assert [item["id"] for item in listed.json()] == [definition_id]
    assert invalid.status_code == 422
    assert deleted.status_code == 204
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_preview_http_uses_definition_and_returns_transient_output() -> None:
    projects = create_memory_project_module()
    project = await projects.create(ProjectAccess(subject="sam"), "Bridge")

    class Runner(_PinnedRunner):
        async def execute(
            self, source: str, inputs: dict[str, object], parameters: dict[str, object]
        ) -> tuple[object, str]:
            assert inputs == {"load": 3}
            return {"value": 6}, "deno:2.9.7;pyodide:314.0.7"

    transforms = TransformModule(projects, MemoryTransformStore(), Runner())
    definition = await transforms.define(
        ProjectAccess(subject="sam"), project.id, "Double",
        "def transform(inputs, parameters):\n    return {}\n",
        {"load": "/load"}, {"type": "object"},
    )
    app = FastAPI()
    app.include_router(
        create_transform_router(
            create_identity_module(Settings(environment="test", fixed_identity_subject="sam")),
            transforms,
        ),
        prefix="/api",
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/projects/{project.id}/transforms/{definition.id}/preview",
            json={"record": {"load": 3}, "parameters": {}},
        )
    assert response.status_code == 200
    assert response.json() == {
        "output": {"value": 6}, "runtime": "deno:2.9.7;pyodide:314.0.7",
        "sourceHash": definition.source_hash,
    }


@pytest.mark.asyncio
async def test_durable_run_http_can_be_inspected_after_execution() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="sam")
    project = await projects.create(owner, "Bridge")

    class Runner(_PinnedRunner):
        async def execute(
            self, source: str, inputs: dict[str, object], parameters: dict[str, object]
        ) -> tuple[object, str]:
            return {"value": 6}, "deno:2.9.7;pyodide:314.0.7"

    class ToolSchemas:
        async def input_schema(
            self, access: ProjectAccess, project_id: str, plugin_id: str, tool_name: str
        ) -> dict[str, object]:
            return {}

    datasets = DatasetModule(projects, MemoryDatasetStore(), ToolSchemas())
    transforms = TransformModule(
        projects, MemoryTransformStore(), Runner(), MemoryTransformRunStore(), datasets
    )
    definition = await transforms.define(
        owner, project.id, "Double", "def transform(inputs, parameters):\n    return {}\n",
        {"load": "/load"}, {"type": "object"},
    )
    app = FastAPI()
    app.include_router(
        create_transform_router(
            create_identity_module(Settings(environment="test", fixed_identity_subject="sam")),
            transforms,
        ),
        prefix="/api",
    )
    path = f"/api/projects/{project.id}/transforms"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        started = await client.post(
            f"{path}/{definition.id}/runs",
            json={"record": {"load": 3}, "parameters": {}},
        )
        assert started.status_code == 201
        loaded = await client.get(f"{path}/runs/{started.json()['id']}")
        listed = await client.get(f"{path}/runs?limit=1&definitionId={definition.id}")
        saved = await client.post(
            f"{path}/runs/{started.json()['id']}/save-dataset",
            json={"name": "Saved values"},
        )
    assert loaded.status_code == 200
    assert loaded.json() == started.json()
    assert listed.status_code == 200
    assert listed.json() == {"items": [started.json()], "nextOffset": None}
    assert saved.status_code == 201
    assert saved.json()["recordCount"] == 1
    stored = await datasets.load_dataset(owner, project.id, saved.json()["id"])
    assert stored.records[0].value == {"value": 6}
    assert loaded.json()["outputManifest"]["kind"] == "json"
