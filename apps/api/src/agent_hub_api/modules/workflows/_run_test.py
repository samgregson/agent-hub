import json
from dataclasses import asdict
from typing import Any, cast

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from agent_hub_api.modules.datasets import DatasetModule, DatasetRecordInput, MemoryDatasetStore
from agent_hub_api.modules.identity import create_identity_module
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module
from agent_hub_api.modules.transforms import MemoryTransformStore, TransformModule
from agent_hub_api.modules.workflows import (
    MemoryWorkflowRunStore,
    MemoryWorkflowStore,
    WorkflowDefinitionModule,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowNode,
    WorkflowNotFound,
    WorkflowOutput,
    WorkflowRunConflict,
    WorkflowRunModule,
    WorkflowValidationError,
    create_workflow_router,
)
from agent_hub_api.settings import Settings


class _Schemas:
    async def input_schema(self, *_: object) -> dict[str, object]:
        return {"type": "object"}


@pytest.mark.asyncio
async def test_prepared_run_captures_dataset_values_and_definition_before_edits() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="owner")
    project = await projects.create(owner, "Analysis")
    datasets = DatasetModule(projects, MemoryDatasetStore(), _Schemas())
    dataset = await datasets.create_dataset(
        owner, project.id, "Inputs", [DatasetRecordInput({"value": 2})]
    )
    transforms = TransformModule(projects, MemoryTransformStore())
    definitions = WorkflowDefinitionModule(
        projects, datasets, transforms, None, MemoryWorkflowStore()
    )
    graph = WorkflowGraph(
        (WorkflowNode("source", "dataset", dataset.id, dataset.version),),
        (),
        (WorkflowOutput("result", "source", "records"),),
    )
    definition = await definitions.create(owner, project.id, "Inspection", graph)
    runs = WorkflowRunModule(definitions, datasets, transforms, None, MemoryWorkflowRunStore())

    prepared = await runs.prepare(owner, project.id, definition.id, "request-1", expected_version=1)
    assert prepared.status == "prepared"
    assert prepared.definition_version == 1
    assert prepared.initiator_subject == "owner"
    sources = cast(dict[str, Any], prepared.snapshot["sources"])
    assert sources["source"]["records"][0]["value"] == {"value": 2}
    assert (
        await runs.prepare(owner, project.id, definition.id, "request-1", expected_version=1)
    ).id == prepared.id
    assert (await runs.load(owner, project.id, prepared.id)) == prepared
    assert [run.id for run in await runs.list(owner, project.id, definition.id)] == [prepared.id]

    await definitions.revise(owner, project.id, definition.id, "Renamed", graph, expected_version=1)
    assert (
        await runs.prepare(owner, project.id, definition.id, "request-1", expected_version=1)
    ).id == prepared.id
    with pytest.raises(WorkflowValidationError, match="Workflow version changed"):
        await runs.prepare(owner, project.id, definition.id, "request-2", expected_version=1)

    await datasets.update_dataset(
        owner, project.id, dataset.id, "Inputs", [DatasetRecordInput({"value": 3})]
    )
    assert (await runs.load(owner, project.id, prepared.id)).snapshot == prepared.snapshot
    with pytest.raises(WorkflowValidationError, match="version changed"):
        await runs.prepare(owner, project.id, definition.id, "request-2", expected_version=2)
    with pytest.raises(WorkflowNotFound):
        await runs.load(ProjectAccess(subject="other"), project.id, prepared.id)


@pytest.mark.asyncio
async def test_prepared_run_idempotency_key_cannot_switch_workflows() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="owner")
    project = await projects.create(owner, "Analysis")
    datasets = DatasetModule(projects, MemoryDatasetStore(), _Schemas())
    dataset = await datasets.create_dataset(owner, project.id, "Inputs", [])
    definitions = WorkflowDefinitionModule(
        projects,
        datasets,
        TransformModule(projects, MemoryTransformStore()),
        None,
        MemoryWorkflowStore(),
    )
    graph = WorkflowGraph(
        (WorkflowNode("source", "dataset", dataset.id, dataset.version),),
        (),
        (WorkflowOutput("result", "source", "records"),),
    )
    first = await definitions.create(owner, project.id, "First", graph)
    second = await definitions.create(owner, project.id, "Second", graph)
    runs = WorkflowRunModule(
        definitions,
        datasets,
        TransformModule(projects, MemoryTransformStore()),
        None,
        MemoryWorkflowRunStore(),
    )
    await runs.prepare(owner, project.id, first.id, "same-key", expected_version=1)
    with pytest.raises(WorkflowRunConflict):
        await runs.prepare(owner, project.id, second.id, "same-key", expected_version=1)


@pytest.mark.asyncio
async def test_prepared_run_pins_python_source_and_rejects_changed_revision() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="owner")
    project = await projects.create(owner, "Analysis")
    datasets = DatasetModule(projects, MemoryDatasetStore(), _Schemas())
    dataset = await datasets.create_dataset(owner, project.id, "Inputs", [])
    transforms = TransformModule(projects, MemoryTransformStore())
    function = await transforms.define(
        owner,
        project.id,
        "Count",
        "def transform(inputs, parameters):\n    return 0\n",
        {"items": "/items"},
        {"type": "integer"},
    )
    definitions = WorkflowDefinitionModule(
        projects, datasets, transforms, None, MemoryWorkflowStore()
    )
    graph = WorkflowGraph(
        (
            WorkflowNode("source", "dataset", dataset.id, dataset.version),
            WorkflowNode("count", "python", function.id, function.revision),
        ),
        (WorkflowEdge("source", "records", "count", "items"),),
        (WorkflowOutput("result", "count", "result"),),
    )
    definition = await definitions.create(owner, project.id, "Count records", graph)
    runs = WorkflowRunModule(definitions, datasets, transforms, None, MemoryWorkflowRunStore())
    prepared = await runs.prepare(owner, project.id, definition.id, "first", expected_version=1)
    targets = cast(dict[str, Any], prepared.snapshot["targets"])
    assert targets["count"]["source"] == function.source
    assert targets["count"]["sourceHash"] == function.source_hash
    await transforms.revise(
        owner,
        project.id,
        function.id,
        "Count",
        "def transform(inputs, parameters):\n    return 1\n",
        {"items": "/items"},
        {"type": "integer"},
    )
    with pytest.raises(WorkflowValidationError, match="version changed"):
        await runs.prepare(owner, project.id, definition.id, "second", expected_version=1)


@pytest.mark.asyncio
async def test_prepared_run_route_round_trips_without_dispatching_calls() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="owner")
    project = await projects.create(owner, "Analysis")
    datasets = DatasetModule(projects, MemoryDatasetStore(), _Schemas())
    dataset = await datasets.create_dataset(owner, project.id, "Inputs", [])
    transforms = TransformModule(projects, MemoryTransformStore())
    definitions = WorkflowDefinitionModule(
        projects, datasets, transforms, None, MemoryWorkflowStore()
    )
    graph = WorkflowGraph(
        (WorkflowNode("source", "dataset", dataset.id, dataset.version),),
        (),
        (WorkflowOutput("result", "source", "records"),),
    )
    definition = await definitions.create(owner, project.id, "Inspection", graph)
    runs = WorkflowRunModule(definitions, datasets, transforms, None, MemoryWorkflowRunStore())
    app = FastAPI()
    app.include_router(
        create_workflow_router(
            create_identity_module(Settings(environment="test", fixed_identity_subject="owner")),
            definitions,
            runs,
        ),
        prefix="/api",
    )
    base = f"/api/projects/{project.id}/workflows/{definition.id}/runs"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            f"{base}/prepare", json={"idempotencyKey": "request-1", "expectedVersion": 1}
        )
        assert created.status_code == 201
        assert created.json()["status"] == "prepared"
        assert created.json()["snapshot"]["graph"] == json.loads(json.dumps(asdict(graph)))
        assert (await client.get(base)).json()[0]["id"] == created.json()["id"]
        assert (await client.get(f"{base}/{created.json()['id']}")).json() == created.json()
