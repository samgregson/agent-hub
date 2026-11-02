import base64
import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from agent_hub_api.modules.datasets import DatasetModule, DatasetRecordInput, MemoryDatasetStore
from agent_hub_api.modules.functions import FunctionModule, MemoryFunctionStore
from agent_hub_api.modules.identity import create_identity_module
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module
from agent_hub_api.modules.workflows import (
    MemoryWorkflowRunStore,
    MemoryWorkflowStore,
    WorkflowDefinitionModule,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowInput,
    WorkflowNode,
    WorkflowNotFound,
    WorkflowOutput,
    WorkflowRun,
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
    datasets = DatasetModule(projects, MemoryDatasetStore())
    dataset = await datasets.create_dataset(
        owner, project.id, "Inputs", [DatasetRecordInput({"value": 2})]
    )
    functions = FunctionModule(projects, MemoryFunctionStore())
    definitions = WorkflowDefinitionModule(
        projects, datasets, functions, None, MemoryWorkflowStore()
    )
    graph = WorkflowGraph(
        (WorkflowNode("source", "dataset", dataset.id, dataset.version),),
        (),
        (WorkflowOutput("result", "source", "records"),),
    )
    definition = await definitions.create(owner, project.id, "Inspection", graph)
    runs = WorkflowRunModule(definitions, datasets, functions, None, MemoryWorkflowRunStore())

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
async def test_load_image_accepts_image_nested_in_named_workflow_output() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="owner")
    project = await projects.create(owner, "Image output")
    datasets = DatasetModule(projects, MemoryDatasetStore())
    dataset = await datasets.create_dataset(owner, project.id, "Inputs", [])
    definitions = WorkflowDefinitionModule(
        projects,
        datasets,
        FunctionModule(projects, MemoryFunctionStore()),
        None,
        MemoryWorkflowStore(),
    )
    definition = await definitions.create(
        owner,
        project.id,
        "Chart",
        WorkflowGraph(
            (WorkflowNode("source", "dataset", dataset.id, dataset.version),),
            (),
            (WorkflowOutput("chart", "source", "records"),),
        ),
    )
    store = MemoryWorkflowRunStore()
    runs = WorkflowRunModule(
        definitions,
        datasets,
        FunctionModule(projects, MemoryFunctionStore()),
        None,
        store,
    )
    png = b"\x89PNG\r\n\x1a\n" + bytes(8) + (1).to_bytes(4, "big") * 2
    data_base64 = base64.b64encode(png).decode("ascii")
    run = WorkflowRun(
        id="run-with-nested-image",
        project_id=project.id,
        workflow_id=definition.id,
        definition_version=definition.version,
        status="succeeded",
        snapshot={},
        execution={
            "outputs": {
                "chart": {
                    "image": {
                        "kind": "image",
                        "mimeType": "image/png",
                        "dataBase64": data_base64,
                        "altText": "A chart",
                    }
                }
            }
        },
        initiator_subject=owner.subject,
        idempotency_key="nested-image",
        created_at=datetime.now(UTC),
    )
    await store.create_or_load(run)

    image = await runs.load_image(owner, project.id, run.id, "chart")

    assert image.data == png
    assert image.data_base64 == data_base64
    assert image.alt_text == "A chart"


@pytest.mark.asyncio
async def test_prepared_run_idempotency_key_cannot_switch_workflows() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="owner")
    project = await projects.create(owner, "Analysis")
    datasets = DatasetModule(projects, MemoryDatasetStore())
    dataset = await datasets.create_dataset(owner, project.id, "Inputs", [])
    definitions = WorkflowDefinitionModule(
        projects,
        datasets,
        FunctionModule(projects, MemoryFunctionStore()),
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
        FunctionModule(projects, MemoryFunctionStore()),
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
    datasets = DatasetModule(projects, MemoryDatasetStore())
    dataset = await datasets.create_dataset(owner, project.id, "Inputs", [])
    functions = FunctionModule(projects, MemoryFunctionStore())
    function = await functions.define(
        owner,
        project.id,
        "Count",
        "def transform(inputs, parameters):\n    return 0\n",
        {"type": "object", "properties": {"items": {"type": "array"}}, "required": ["items"]},
        {"type": "integer"},
    )
    definitions = WorkflowDefinitionModule(
        projects, datasets, functions, None, MemoryWorkflowStore()
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
    runs = WorkflowRunModule(definitions, datasets, functions, None, MemoryWorkflowRunStore())
    prepared = await runs.prepare(owner, project.id, definition.id, "first", expected_version=1)
    targets = cast(dict[str, Any], prepared.snapshot["targets"])
    assert targets["count"]["source"] == function.source
    assert targets["count"]["sourceHash"] == function.source_hash
    await functions.revise(
        owner,
        project.id,
        function.id,
        "Count",
        "def transform(inputs, parameters):\n    return 1\n",
        {"type": "object", "properties": {"items": {"type": "array"}}, "required": ["items"]},
        {"type": "integer"},
    )
    with pytest.raises(WorkflowValidationError, match="version changed"):
        await runs.prepare(owner, project.id, definition.id, "second", expected_version=1)


@pytest.mark.asyncio
async def test_prepared_run_route_round_trips_without_dispatching_calls() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="owner")
    project = await projects.create(owner, "Analysis")
    datasets = DatasetModule(projects, MemoryDatasetStore())
    dataset = await datasets.create_dataset(owner, project.id, "Inputs", [])
    functions = FunctionModule(projects, MemoryFunctionStore())
    definitions = WorkflowDefinitionModule(
        projects, datasets, functions, None, MemoryWorkflowStore()
    )
    graph = WorkflowGraph(
        (WorkflowNode("source", "dataset", dataset.id, dataset.version),),
        (),
        (WorkflowOutput("result", "source", "records"),),
        (WorkflowInput("comment", {"type": "string"}),),
    )
    definition = await definitions.create(owner, project.id, "Inspection", graph)
    runs = WorkflowRunModule(definitions, datasets, functions, None, MemoryWorkflowRunStore())
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
            f"{base}/prepare",
            json={
                "idempotencyKey": "request-1",
                "expectedVersion": 1,
                "workflowInputs": {"comment": "route test"},
            },
        )
        assert created.status_code == 201
        assert created.json()["status"] == "prepared"
        assert created.json()["snapshot"]["workflowInputs"] == {"comment": "route test"}
        assert created.json()["snapshot"]["graph"] == json.loads(json.dumps(asdict(graph)))
        assert (await client.get(base)).json()[0]["id"] == created.json()["id"]
        assert (await client.get(f"{base}/{created.json()['id']}")).json() == created.json()
        executed = await client.post(f"{base}/{created.json()['id']}/execute")
        assert executed.status_code == 200
        assert executed.json()["status"] == "succeeded"
        assert executed.json()["execution"]["outputs"] == {"result": []}


@pytest.mark.asyncio
async def test_saved_mcp_output_app_enforces_scope_and_captured_version_without_execution() -> None:
    from agent_hub_api.modules.plugin_gateway import (
        MemoryPluginEnablementStore,
        PluginDiscoveredTool,
        PluginGatewayModule,
        PluginManifest,
        PluginTool,
        PluginUiResource,
    )

    class AppClient:
        async def discover_tools(self) -> tuple[PluginDiscoveredTool, ...]:
            return (
                PluginDiscoveredTool(
                    name="render",
                    description="Render",
                    read_only=True,
                    app_resource_uri="ui://fixture/view.html",
                ),
            )

        async def read_ui_resource(self, uri: str) -> PluginUiResource:
            return PluginUiResource(uri, "<h1>Captured result</h1>")

        async def call_tool(self, *_: Any) -> Any:
            pytest.fail("Opening a saved App must not execute tools")

    projects = create_memory_project_module()
    owner = ProjectAccess(subject="owner")
    project = await projects.create(owner, "Saved MCP output")
    manifest = PluginManifest(
        id="fixture",
        name="Fixture",
        version="1",
        endpoint="http://fixture/mcp",
        tools=(PluginTool("render", read_only=True),),
        app_resource_uri="ui://fixture/view.html",
        app_allow_wasm=True,
    )
    gateway = PluginGatewayModule(
        projects, [manifest], MemoryPluginEnablementStore(), {"fixture": AppClient()}
    )
    await gateway.enable(owner, project.id, "fixture")
    datasets = DatasetModule(projects, MemoryDatasetStore())
    functions = FunctionModule(projects, MemoryFunctionStore())
    definitions = WorkflowDefinitionModule(
        projects, datasets, functions, gateway, MemoryWorkflowStore()
    )
    graph = WorkflowGraph(
        (WorkflowNode("view", "mcp", "fixture", "1", tool_name="render"),),
        (),
        (WorkflowOutput("model", "view", "result"),),
    )
    store = MemoryWorkflowRunStore()
    run = WorkflowRun(
        id="saved-app-run",
        project_id=project.id,
        workflow_id="saved-workflow",
        definition_version=1,
        status="succeeded",
        snapshot={
            "graph": asdict(graph),
            "targets": {"view": {"pluginId": "fixture", "toolName": "render", "version": "1"}},
        },
        execution={
            "outputs": {"model": {"value": 42}},
            "nodes": {"view": {"status": "succeeded", "inputs": {}, "output": {"value": 42}}},
        },
        initiator_subject="owner",
        idempotency_key="saved-app",
        created_at=datetime.now(UTC),
    )
    await store.create_or_load(run)
    runs = WorkflowRunModule(definitions, datasets, functions, gateway, store)
    app = FastAPI()
    app.include_router(
        create_workflow_router(
            create_identity_module(Settings(environment="test", fixed_identity_subject="owner")),
            definitions,
            runs,
        ),
        prefix="/api",
    )
    path = f"/api/projects/{project.id}/workflows/saved-workflow/runs/{run.id}/outputs/model/app"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(path)
        assert response.status_code == 200, response.text
        assert response.text == "<h1>Captured result</h1>"
        assert "'wasm-unsafe-eval'" in response.headers["content-security-policy"]
        assert "connect-src 'none'" in response.headers["content-security-policy"]
        assert response.headers["cache-control"] == "no-store"
        assert (
            await client.get(path.replace("saved-workflow", "wrong-workflow"))
        ).status_code == 404
        assert (
            await client.get(path.replace("outputs/model", "outputs/unknown"))
        ).status_code == 404
        await gateway.disable(owner, project.id, "fixture")
        assert (await client.get(path)).status_code == 422
        await gateway.enable(owner, project.id, "fixture")
        # A captured old version cannot silently render with the currently deployed App.
        stale = {
            **run.snapshot,
            "targets": {"view": {"pluginId": "fixture", "toolName": "render", "version": "old"}},
        }
        from dataclasses import replace

        await store.update(replace(run, snapshot=stale), expected_status="succeeded")
        assert (await client.get(path)).status_code == 422
    with pytest.raises(WorkflowNotFound):
        await runs.app_resource(
            ProjectAccess(subject="other"), project.id, run.workflow_id, run.id, "model"
        )
