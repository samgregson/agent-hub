import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import cast

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from agent_hub_api.modules.batch_execution import (
    BatchExecutionModule,
    BatchInitiation,
    BatchRun,
    BatchRunOrder,
    BatchRunStatus,
    McpCallValidationError,
    MemoryBatchRunStore,
    create_batch_execution_router,
)
from agent_hub_api.modules.datasets import (
    DatasetModule,
    DatasetRecordInput,
    DatasetValidationError,
    MemoryDatasetStore,
)
from agent_hub_api.modules.identity import create_identity_module
from agent_hub_api.modules.plugin_gateway import PluginGatewayModule, PluginToolResult
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module
from agent_hub_api.modules.transforms import (
    MemoryTransformStore,
    TransformModule,
    TransformRuntimeIdentity,
)
from agent_hub_api.settings import Settings


class ToolSchemas:
    async def input_schema(self, *_: object) -> Mapping[str, object]:
        return {
            "type": "object",
            "required": ["load"],
            "properties": {"load": {"type": "number"}},
        }


class Gateway:
    def __init__(
        self, fail_loads: set[int] | None = None, invalid_loads: set[int] | None = None
    ) -> None:
        self.calls: list[int] = []
        self.fail_loads = fail_loads or set()
        self.invalid_loads = invalid_loads or set()
        self.active = 0
        self.maximum_active = 0

    async def batch_call(
        self,
        _access: ProjectAccess,
        _project_id: str,
        _plugin_id: str,
        _tool_name: str,
        arguments: Mapping[str, object],
    ) -> PluginToolResult:
        raw_load = arguments["load"]
        assert isinstance(raw_load, (int, float))
        load = int(raw_load)
        self.calls.append(load)
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        await asyncio.sleep(0)
        self.active -= 1
        if load in self.fail_loads:
            raise RuntimeError(f"load {load} failed")
        if load in self.invalid_loads:
            return PluginToolResult((), {"unexpected": load})
        return PluginToolResult((), {"result": load * 2})

    async def output_schema(self, *_: object) -> Mapping[str, object]:
        return {
            "type": "object",
            "required": ["result"],
            "properties": {"result": {"type": "number"}},
        }

    async def input_schema(self, *_: object) -> Mapping[str, object]:
        return {
            "type": "object",
            "required": ["load"],
            "properties": {"load": {"type": "number"}},
        }

    async def tool_version(self, *_: object) -> str:
        return "fixture-v1"


@pytest.mark.asyncio
async def test_direct_mcp_call_retains_one_reviewed_input_and_output() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="sam")
    project = await projects.create(owner, "Direct MCP call")
    datasets = DatasetModule(projects, MemoryDatasetStore(), ToolSchemas())

    class DirectGateway(Gateway):
        version = "1.0.0"

        async def tool_version(self, *_: object) -> str:
            return self.version

        async def output_schema(self, *_: object, **__: object) -> Mapping[str, object]:
            return await super().output_schema()

        async def call(
            self,
            _access: ProjectAccess,
            _project_id: str,
            _plugin_id: str,
            _tool_name: str,
            arguments: Mapping[str, object],
        ) -> PluginToolResult:
            return await self.batch_call(_access, _project_id, _plugin_id, _tool_name, arguments)

    gateway = DirectGateway()
    batches = BatchExecutionModule(
        projects, datasets, cast(PluginGatewayModule, gateway), MemoryBatchRunStore()
    )
    plan = await batches.plan_mcp_call(owner, project.id, "fixture", "double", {"load": 3})
    assert plan.snapshot()["invocationCount"] == 1
    assert plan.snapshot()["inputs"] == {"load": 3}
    assert plan.snapshot()["pluginVersion"] == "1.0.0"
    assert plan.snapshot()["review"] == {
        "target": {"kind": "mcp", "id": "fixture/double", "version": "1.0.0", "name": "double"},
        "shape": "single",
        "source": {"kind": "direct"},
        "inputPorts": {"load": {"type": "number"}},
        "outputPorts": {
            "result": {
                "type": "object",
                "required": ["result"],
                "properties": {"result": {"type": "number"}},
            }
        },
        "bindings": [{"inputs": {"load": 3}}],
        "invocationCount": 1,
        "maxInvocations": 1,
        "outputKind": "batchResultSet",
        "agentApproval": "required",
    }

    queued = await batches.submit_mcp_call(
        owner, project.id, "fixture", "double", {"load": 3}, "1.0.0", "call-1"
    )
    completed = await batches.execute(owner, project.id, queued.id)
    assert completed.status == BatchRunStatus.succeeded
    assert completed.definition_snapshot["callKind"] == "mcpCall"
    assert completed.definition_snapshot["review"] == plan.snapshot()["review"]
    assert completed.records[0].input == {"load": 3}
    assert completed.records[0].structured_output == {"result": 6}
    assert gateway.calls == [3]
    assert (
        await batches.submit_mcp_call(
            owner, project.id, "fixture", "double", {"load": 3}, "1.0.0", "call-1"
        )
    ).id == queued.id

    with pytest.raises(McpCallValidationError, match="version changed"):
        await batches.submit_mcp_call(owner, project.id, "fixture", "double", {"load": 3}, "0.9.0")
    with pytest.raises(McpCallValidationError, match="input schema"):
        await batches.plan_mcp_call(owner, project.id, "fixture", "double", {"bad": 3})
    with pytest.raises(McpCallValidationError, match="exceed 64000 bytes"):
        await batches.plan_mcp_call(
            owner, project.id, "fixture", "double", {"load": 2, "padding": "x" * 64_000}
        )

    stale = await batches.submit_mcp_call(
        owner, project.id, "fixture", "double", {"load": 4}, "1.0.0"
    )
    gateway.version = "1.0.1"
    failed = await batches.execute(owner, project.id, stale.id)
    assert failed.status == BatchRunStatus.failed
    assert failed.records[0].error == (
        "MCP tool version changed since this Run was queued (1.0.0 → 1.0.1)."
    )
    assert gateway.calls == [3]


@pytest.mark.asyncio
async def test_direct_mcp_call_http_reviews_and_starts_one_invocation() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="sam")
    project = await projects.create(owner, "Direct MCP call")
    datasets = DatasetModule(projects, MemoryDatasetStore(), ToolSchemas())

    class DirectGateway(Gateway):
        async def tool_version(self, *_: object) -> str:
            return "1.0.0"

        async def output_schema(self, *_: object, **__: object) -> Mapping[str, object]:
            return await super().output_schema()

    batches = BatchExecutionModule(
        projects, datasets, cast(PluginGatewayModule, DirectGateway()), MemoryBatchRunStore()
    )
    app = FastAPI()
    app.include_router(
        create_batch_execution_router(
            create_identity_module(Settings(environment="test", fixed_identity_subject="sam")),
            batches,
        ),
        prefix="/api",
    )
    base = f"/api/projects/{project.id}/batch-runs/mcp-call"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        plan = await client.post(
            f"{base}/plan",
            json={"pluginId": "fixture", "toolName": "double", "arguments": {"load": 3}},
        )
        started = await client.post(
            base,
            json={
                "pluginId": "fixture",
                "toolName": "double",
                "arguments": {"load": 3},
                "expectedPluginVersion": "1.0.0",
            },
        )
    assert plan.status_code == 200
    assert plan.json()["inputs"] == {"load": 3}
    assert started.status_code == 201
    assert started.json()["recordCount"] == 1


@pytest.mark.asyncio
async def test_direct_mcp_map_uses_dataset_records_without_a_batch_definition() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="sam")
    project = await projects.create(owner, "Direct MCP map")
    datasets = DatasetModule(projects, MemoryDatasetStore(), ToolSchemas())
    dataset = await datasets.create_dataset(
        owner,
        project.id,
        "Inputs",
        [DatasetRecordInput({"load": 2}), DatasetRecordInput({"load": 3})],
    )
    gateway = Gateway(fail_loads={3})
    batches = BatchExecutionModule(
        projects, datasets, cast(PluginGatewayModule, gateway), MemoryBatchRunStore()
    )

    plan = await batches.plan_mcp_dataset(owner, project.id, "fixture", "double", dataset.id)
    assert plan.dataset_version == dataset.version
    assert plan.record_ids == tuple(record.id for record in dataset.records)
    assert plan.invocation_count == 2
    assert plan.snapshot()["pluginVersion"] == "fixture-v1"
    assert plan.snapshot()["inputSchema"] == dict(plan.input_schema)
    review = cast(Mapping[str, object], plan.snapshot()["review"])
    assert review["shape"] == "map"
    assert review["source"] == {"kind": "dataset", "id": dataset.id, "version": dataset.version}
    assert review["bindings"] == [
        {"recordId": record.id, "inputs": dict(record.value)} for record in dataset.records
    ]
    assert review["maxInvocations"] == 100

    queued = await batches.submit_mcp_dataset(
        owner,
        project.id,
        "fixture",
        "double",
        dataset.id,
        plan.dataset_version,
        "fixture-v1",
        "approved-map-1",
    )
    completed = await batches.execute(owner, project.id, queued.id)

    assert len(await datasets.list_definitions(owner, project.id)) == 0
    assert completed.status == BatchRunStatus.partial
    assert gateway.calls == [2, 3]
    assert [record.dataset_record_id for record in completed.records] == list(plan.record_ids)
    assert completed.records[0].structured_output == {"result": 4}
    assert completed.records[1].error == "load 3 failed"
    assert completed.definition_snapshot["datasetVersion"] == dataset.version
    assert completed.definition_snapshot["callKind"] == "mcpMap"
    assert completed.definition_snapshot["pluginVersion"] == "fixture-v1"
    assert completed.definition_snapshot["review"] == plan.snapshot()["review"]
    assert (
        await batches.submit_mcp_dataset(
            owner,
            project.id,
            "fixture",
            "double",
            dataset.id,
            plan.dataset_version,
            "fixture-v1",
            "approved-map-1",
        )
    ).id == queued.id


@pytest.mark.asyncio
async def test_direct_mcp_map_http_reviews_then_starts_the_same_captured_records() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="sam")
    project = await projects.create(owner, "Direct MCP map")
    datasets = DatasetModule(projects, MemoryDatasetStore(), ToolSchemas())
    dataset = await datasets.create_dataset(
        owner, project.id, "Inputs", [DatasetRecordInput({"load": 2})]
    )
    batches = BatchExecutionModule(
        projects, datasets, cast(PluginGatewayModule, Gateway()), MemoryBatchRunStore()
    )
    app = FastAPI()
    app.include_router(
        create_batch_execution_router(
            create_identity_module(Settings(environment="test", fixed_identity_subject="sam")),
            batches,
        ),
        prefix="/api",
    )

    base = f"/api/projects/{project.id}/batch-runs/mcp-map"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        plan = await client.post(
            f"{base}/plan",
            json={"datasetId": dataset.id, "pluginId": "fixture", "toolName": "double"},
        )
        started = await client.post(
            base,
            json={
                "datasetId": dataset.id,
                "pluginId": "fixture",
                "toolName": "double",
                "expectedDatasetVersion": dataset.version,
                "expectedPluginVersion": "fixture-v1",
            },
        )

    assert plan.status_code == 200
    assert plan.json()["recordIds"] == [dataset.records[0].id]
    assert plan.json()["inputs"] == [{"load": 2}]
    assert plan.json()["pluginVersion"] == "fixture-v1"
    assert started.status_code == 201
    assert started.json()["recordCount"] == 1


@pytest.mark.asyncio
async def test_direct_mcp_map_rejects_invalid_and_stale_dataset_inputs() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="sam")
    project = await projects.create(owner, "Direct MCP map")
    datasets = DatasetModule(projects, MemoryDatasetStore(), ToolSchemas())
    dataset = await datasets.create_dataset(
        owner, project.id, "Inputs", [DatasetRecordInput({"other": 2})]
    )
    gateway = Gateway()
    batches = BatchExecutionModule(
        projects, datasets, cast(PluginGatewayModule, gateway), MemoryBatchRunStore()
    )

    with pytest.raises(DatasetValidationError, match="Record 1"):
        await batches.plan_mcp_dataset(owner, project.id, "fixture", "double", dataset.id)
    updated = await datasets.update_dataset(
        owner,
        project.id,
        dataset.id,
        dataset.name,
        [DatasetRecordInput({"load": 2}, id=dataset.records[0].id)],
        expected_version=dataset.version,
    )
    with pytest.raises(DatasetValidationError, match="changed"):
        await batches.submit_mcp_dataset(
            owner, project.id, "fixture", "double", dataset.id, dataset.version, "fixture-v1"
        )
    with pytest.raises(McpCallValidationError, match="version changed"):
        await batches.submit_mcp_dataset(
            owner, project.id, "fixture", "double", dataset.id, updated.version, "old-version"
        )
    assert updated.version == dataset.version + 1
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_queued_mcp_map_fails_before_dispatch_when_plugin_version_changes() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="sam")
    project = await projects.create(owner, "Pinned MCP map")
    datasets = DatasetModule(projects, MemoryDatasetStore(), ToolSchemas())
    dataset = await datasets.create_dataset(
        owner,
        project.id,
        "Inputs",
        [DatasetRecordInput({"load": 2}), DatasetRecordInput({"load": 3})],
    )

    class VersionedGateway(Gateway):
        version = "fixture-v1"

        async def tool_version(self, *_: object) -> str:
            return self.version

    gateway = VersionedGateway()
    batches = BatchExecutionModule(
        projects, datasets, cast(PluginGatewayModule, gateway), MemoryBatchRunStore()
    )
    run = await batches.submit_mcp_dataset(
        owner, project.id, "fixture", "double", dataset.id, dataset.version, "fixture-v1"
    )
    gateway.version = "fixture-v2"
    completed = await batches.execute(owner, project.id, run.id)
    assert completed.status == BatchRunStatus.failed
    assert gateway.calls == []
    assert [record.error for record in completed.records] == [
        "MCP tool version changed since this Run was queued (fixture-v1 → fixture-v2)."
    ] * 2


@pytest.mark.asyncio
async def test_per_record_transform_run_needs_no_batch_definition() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="sam")
    project = await projects.create(owner, "Transform run")
    datasets = DatasetModule(projects, MemoryDatasetStore(), ToolSchemas())
    dataset = await datasets.create_dataset(
        owner,
        project.id,
        "Loads",
        [DatasetRecordInput({"load": 2}), DatasetRecordInput({"load": 3})],
    )

    class Runner:
        fail_loads: set[int] = set()

        async def identity(self) -> TransformRuntimeIdentity:
            return TransformRuntimeIdentity("deno:test;pyodide:test", "a" * 64)

        async def execute(
            self, _source: str, inputs: dict[str, object], _parameters: dict[str, object]
        ) -> tuple[object, str]:
            if inputs["load"] in self.fail_loads:
                raise ValueError("record rejected")
            return {"result": cast(int, inputs["load"]) * 2}, "deno:test;pyodide:test"

    runner = Runner()
    transforms = TransformModule(projects, MemoryTransformStore(), runner)
    transform = await transforms.define(
        owner,
        project.id,
        "Double",
        "def transform(inputs, parameters):\n    return {}\n",
        {"load": "/load"},
        {"type": "object"},
    )
    batches = BatchExecutionModule(
        projects,
        datasets,
        cast(PluginGatewayModule, Gateway()),
        MemoryBatchRunStore(),
        transforms=transforms,
    )

    queued = await batches.submit_transform_dataset(
        owner,
        project.id,
        transform.id,
        dataset.id,
        dataset.version,
        transform.revision,
        "approved-call-1",
    )
    completed = await batches.execute(owner, project.id, queued.id)

    assert completed.definition_id == transform.id
    assert completed.status == BatchRunStatus.succeeded
    assert [item.structured_output for item in completed.records] == [{"result": 4}, {"result": 6}]
    assert completed.definition_snapshot["datasetVersion"] == dataset.version
    assert len(await datasets.list_definitions(owner, project.id)) == 0
    assert (
        await batches.submit_transform_dataset(
            owner,
            project.id,
            transform.id,
            dataset.id,
            dataset.version,
            transform.revision,
            "approved-call-1",
        )
    ).id == queued.id

    runner.fail_loads = {2}
    partial_run = await batches.submit_transform_dataset(
        owner,
        project.id,
        transform.id,
        dataset.id,
        dataset.version,
        transform.revision,
        "approved-call-2",
    )
    partial = await batches.execute(owner, project.id, partial_run.id)
    assert partial.status == BatchRunStatus.partial
    assert partial.records[0].error == "record rejected"
    assert partial.records[1].structured_output == {"result": 6}

    runner.fail_loads = {2, 3}
    failed_run = await batches.submit_transform_dataset(
        owner,
        project.id,
        transform.id,
        dataset.id,
        dataset.version,
        transform.revision,
        "approved-call-3",
    )
    failed = await batches.execute(owner, project.id, failed_run.id)
    assert failed.status == BatchRunStatus.failed
    assert [record.error for record in failed.records] == ["record rejected"] * 2


@pytest.mark.asyncio
async def test_python_function_map_passes_each_record_to_one_named_input() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="sam")
    project = await projects.create(owner, "Function Map")
    datasets = DatasetModule(projects, MemoryDatasetStore(), ToolSchemas())
    dataset = await datasets.create_dataset(
        owner,
        project.id,
        "Loads",
        [DatasetRecordInput({"load": 2}), DatasetRecordInput({"load": 3})],
    )

    class Runner:
        calls: list[dict[str, object]] = []

        async def identity(self) -> TransformRuntimeIdentity:
            return TransformRuntimeIdentity("deno:test;pyodide:test", "a" * 64)

        async def execute(
            self, _source: str, inputs: dict[str, object], _parameters: dict[str, object]
        ) -> tuple[object, str]:
            self.calls.append(inputs)
            item = cast(dict[str, int], inputs["item"])
            if item["load"] == 3:
                raise ValueError("record rejected")
            return {"result": item["load"] * 2}, "deno:test;pyodide:test"

    runner = Runner()
    transforms = TransformModule(projects, MemoryTransformStore(), runner)
    definition = await transforms.define(
        owner,
        project.id,
        "Double",
        "def transform(inputs, parameters):\n    return {'result': inputs['item']['load'] * 2}\n",
        {"item": "/not-used-by-map"},
        {"type": "object", "required": ["result"]},
    )
    batches = BatchExecutionModule(
        projects,
        datasets,
        cast(PluginGatewayModule, Gateway()),
        MemoryBatchRunStore(),
        transforms=transforms,
    )

    plan = await batches.plan_python_dataset_map(owner, project.id, definition.id, dataset.id)
    assert plan.snapshot()["itemInputName"] == "item"
    assert plan.snapshot()["invocationCount"] == 2
    assert plan.snapshot()["recordIds"] == [record.id for record in dataset.records]
    review = cast(Mapping[str, object], plan.snapshot()["review"])
    assert review["target"] == {
        "kind": "python",
        "id": definition.id,
        "version": definition.revision,
        "name": definition.name,
    }
    assert review["shape"] == "map"
    assert review["source"] == {"kind": "dataset", "id": dataset.id, "version": dataset.version}
    assert review["inputPorts"] == {"item": {}}
    assert review["invocationCount"] == 2
    assert cast(list[object], plan.snapshot()["boundInputs"])[0] == {
        "recordId": dataset.records[0].id,
        "inputs": {"item": {"load": 2}},
    }

    queued = await batches.submit_python_dataset_map(
        owner,
        project.id,
        definition.id,
        dataset.id,
        plan.dataset_version,
        plan.definition_revision,
        "approved-map-1",
    )
    completed = await batches.execute(owner, project.id, queued.id)
    assert completed.status == BatchRunStatus.partial
    assert runner.calls == [
        {"item": {"load": 2}},
        {"item": {"load": 3}},
    ]
    assert completed.records[0].structured_output == {"result": 4}
    assert completed.records[1].error == "record rejected"
    assert completed.definition_snapshot["review"] == plan.snapshot()["review"]
    assert completed.definition_snapshot["callKind"] == "pythonMap"
    assert (
        await batches.submit_python_dataset_map(
            owner,
            project.id,
            definition.id,
            dataset.id,
            plan.dataset_version,
            plan.definition_revision,
            "approved-map-1",
        )
    ).id == queued.id

    await transforms.revise(
        owner,
        project.id,
        definition.id,
        definition.name,
        definition.source,
        definition.input_selectors,
        definition.output_schema,
    )
    with pytest.raises(DatasetValidationError, match="changed"):
        await batches.submit_python_dataset_map(
            owner,
            project.id,
            definition.id,
            dataset.id,
            plan.dataset_version,
            plan.definition_revision,
        )
    revised_plan = await batches.plan_python_dataset_map(
        owner, project.id, definition.id, dataset.id
    )

    await datasets.update_dataset(
        owner,
        project.id,
        dataset.id,
        dataset.name,
        [DatasetRecordInput(record.value, id=record.id) for record in dataset.records],
        expected_version=dataset.version,
    )
    with pytest.raises(DatasetValidationError, match="changed"):
        await batches.submit_python_dataset_map(
            owner,
            project.id,
            definition.id,
            dataset.id,
            revised_plan.dataset_version,
            revised_plan.definition_revision,
        )


@pytest.mark.asyncio
async def test_python_function_map_http_reviews_then_starts() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="sam")
    project = await projects.create(owner, "Function Map HTTP")
    datasets = DatasetModule(projects, MemoryDatasetStore(), ToolSchemas())
    dataset = await datasets.create_dataset(
        owner, project.id, "Loads", [DatasetRecordInput({"load": 2})]
    )

    class Runner:
        async def identity(self) -> TransformRuntimeIdentity:
            return TransformRuntimeIdentity("deno:test;pyodide:test", "a" * 64)

        async def execute(
            self, _source: str, inputs: dict[str, object], _parameters: dict[str, object]
        ) -> tuple[object, str]:
            return {"copied": inputs["item"]}, "deno:test;pyodide:test"

    transforms = TransformModule(projects, MemoryTransformStore(), Runner())
    definition = await transforms.define(
        owner,
        project.id,
        "Copy",
        "def transform(inputs, parameters):\n    return {'copied': inputs['item']}\n",
        {"item": "/ignored"},
        {"type": "object"},
    )
    batches = BatchExecutionModule(
        projects,
        datasets,
        cast(PluginGatewayModule, Gateway()),
        MemoryBatchRunStore(),
        transforms=transforms,
    )
    app = FastAPI()
    app.include_router(
        create_batch_execution_router(
            create_identity_module(Settings(environment="test", fixed_identity_subject="sam")),
            batches,
        ),
        prefix="/api",
    )
    base = f"/api/projects/{project.id}/batch-runs/python-map"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        planned = await client.post(
            f"{base}/plan",
            json={"definitionId": definition.id, "datasetId": dataset.id},
        )
        started = await client.post(
            base,
            json={
                "definitionId": definition.id,
                "datasetId": dataset.id,
                "expectedDatasetVersion": dataset.version,
                "expectedDefinitionRevision": definition.revision,
            },
        )
    assert planned.status_code == 200
    assert planned.json()["itemInputName"] == "item"
    assert planned.json()["invocationCount"] == 1
    assert started.status_code == 201
    assert started.json()["recordCount"] == 1


@pytest.mark.asyncio
async def test_transform_batch_uses_captured_definition_and_first_record_guard() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="sam")
    project = await projects.create(owner, "Bridge")
    datasets = DatasetModule(projects, MemoryDatasetStore(), ToolSchemas())
    dataset = await datasets.create_dataset(
        owner,
        project.id,
        "Loads",
        [DatasetRecordInput({"load": value}) for value in (2, 3, 4)],
    )

    class Runner:
        calls: list[int] = []

        async def identity(self) -> TransformRuntimeIdentity:
            return TransformRuntimeIdentity("deno:test;pyodide:test", "a" * 64)

        async def execute(
            self, source: str, inputs: dict[str, object], parameters: dict[str, object]
        ) -> tuple[object, str]:
            assert parameters == {}
            assert "return {}" in source
            load = cast(int, inputs["load"])
            self.calls.append(load)
            return {"result": load * 2}, "deno:test;pyodide:test"

    runner = Runner()
    transforms = TransformModule(projects, MemoryTransformStore(), runner)
    transform = await transforms.define(
        owner,
        project.id,
        "Double",
        "def transform(inputs, parameters):\n    return {}\n",
        {"load": "/load"},
        {"type": "object", "required": ["result"], "properties": {"result": {"type": "number"}}},
    )
    batches = BatchExecutionModule(
        projects,
        datasets,
        cast(PluginGatewayModule, Gateway()),
        MemoryBatchRunStore(),
        transforms=transforms,
    )
    definition = await batches.define_transform_batch(
        owner,
        project.id,
        dataset.id,
        "Double loads",
        transform.id,
    )
    queued = await batches.submit_all(owner, project.id, definition.id)
    await transforms.revise(
        owner,
        project.id,
        transform.id,
        "Changed",
        "def transform(inputs, parameters):\n    return {'result': 999}\n",
        {"load": "/load"},
        {"type": "object"},
    )
    run = await batches.execute(owner, project.id, queued.id)
    page = await batches.inspect_results(owner, project.id, run.id, limit=2)

    assert run.status is BatchRunStatus.succeeded
    assert runner.calls == [2, 3, 4]
    assert [item.structured_output for item in page.items] == [
        {"result": 4},
        {"result": 6},
    ]
    assert run.definition_snapshot["transformDefinitionId"] == transform.id
    assert run.definition_snapshot["definitionName"] == "Double loads"
    assert run.definition_snapshot["sourceHash"] == transform.source_hash
    assert run.definition_snapshot["packageHash"] == transform.package_hash


@pytest.mark.asyncio
async def test_transform_batch_stops_when_first_output_breaks_contract() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="sam")
    project = await projects.create(owner, "Bridge")
    datasets = DatasetModule(projects, MemoryDatasetStore(), ToolSchemas())
    dataset = await datasets.create_dataset(
        owner,
        project.id,
        "Loads",
        [DatasetRecordInput({"load": value}) for value in (1, 2, 3)],
    )

    class Runner:
        calls: list[int] = []

        async def identity(self) -> TransformRuntimeIdentity:
            return TransformRuntimeIdentity("deno:test;pyodide:test", "a" * 64)

        async def execute(
            self, source: str, inputs: dict[str, object], parameters: dict[str, object]
        ) -> tuple[object, str]:
            self.calls.append(cast(int, inputs["load"]))
            return {"unexpected": 1}, "deno:test;pyodide:test"

    runner = Runner()
    transforms = TransformModule(projects, MemoryTransformStore(), runner)
    transform = await transforms.define(
        owner,
        project.id,
        "Double",
        "def transform(inputs, parameters):\n    return {}\n",
        {"load": "/load"},
        {"type": "object", "required": ["result"]},
    )
    batches = BatchExecutionModule(
        projects,
        datasets,
        cast(PluginGatewayModule, Gateway()),
        MemoryBatchRunStore(),
        transforms=transforms,
    )
    definition = await batches.define_transform_batch(
        owner,
        project.id,
        dataset.id,
        "Double loads",
        transform.id,
    )

    run = await batches.start_all(owner, project.id, definition.id)

    assert run.status is BatchRunStatus.failed
    assert runner.calls == [1]
    assert run.records[0].error == "Transform output does not match its output schema."


async def create_module(
    gateway: Gateway, max_concurrency: int = 4
) -> tuple[ProjectAccess, str, BatchExecutionModule, str]:
    projects = create_memory_project_module()
    access = ProjectAccess(subject="sam")
    project = await projects.create(access, "Bridge")
    datasets = DatasetModule(projects, MemoryDatasetStore(), ToolSchemas())
    dataset = await datasets.create_dataset(
        access,
        project.id,
        "Load cases",
        [DatasetRecordInput({"load": load}, source_key=f"LC-{load}") for load in range(1, 6)],
    )
    definition = await datasets.create_definition(
        access,
        project.id,
        dataset.id,
        "Double loads",
        "reference-calculation",
        "double_load",
        {"load": "/load"},
    )
    return (
        access,
        project.id,
        BatchExecutionModule(
            projects,
            datasets,
            cast(PluginGatewayModule, gateway),
            MemoryBatchRunStore(),
            max_concurrency=max_concurrency,
        ),
        definition.id,
    )


@pytest.mark.asyncio
async def test_first_failed_record_stops_the_batch_before_fanout() -> None:
    gateway = Gateway({1})
    access, project_id, batches, definition_id = await create_module(gateway)

    run = await batches.start_all(access, project_id, definition_id)

    assert run.status is BatchRunStatus.failed
    assert gateway.calls == [1]
    assert run.records[0].error == "load 1 failed"


@pytest.mark.asyncio
async def test_first_schema_invalid_result_stops_the_batch_before_fanout() -> None:
    gateway = Gateway(invalid_loads={1})
    access, project_id, batches, definition_id = await create_module(gateway)

    run = await batches.start_all(access, project_id, definition_id)

    assert run.status is BatchRunStatus.failed
    assert gateway.calls == [1]
    assert run.records[0].error is not None


@pytest.mark.asyncio
async def test_batch_limits_concurrency_persists_partial_results_and_lists_newest_first() -> None:
    gateway = Gateway({4})
    access, project_id, batches, definition_id = await create_module(gateway, max_concurrency=2)

    run = await batches.start_all(access, project_id, definition_id)
    page = await batches.list(access, project_id, definition_id, limit=1)

    assert run.status is BatchRunStatus.partial
    assert len(run.records) == 5
    assert [record.error for record in run.records if record.error] == ["load 4 failed"]
    assert gateway.maximum_active <= 2
    assert run.definition_snapshot["recordIds"] == [
        record.dataset_record_id for record in run.records
    ]
    assert page.items == (run,)
    assert page.next_offset is None


@pytest.mark.asyncio
async def test_run_inspection_pages_filters_and_orders_persisted_runs() -> None:
    gateway = Gateway()
    access, project_id, batches, definition_id = await create_module(gateway)
    first = await batches.start_all(access, project_id, definition_id)
    second = await batches.start_all(access, project_id, definition_id)

    newest = await batches.list(access, project_id, definition_id, limit=1)
    oldest = await batches.list(
        access,
        project_id,
        definition_id,
        order=BatchRunOrder.oldest,
        limit=1,
    )
    failed = await batches.list(access, project_id, definition_id, status=BatchRunStatus.failed)

    assert newest.items == (second,)
    assert newest.next_offset == 1
    assert oldest.items == (first,)
    assert failed.items == ()


@pytest.mark.asyncio
async def test_result_set_inspection_pages_records_without_losing_the_run_snapshot() -> None:
    gateway = Gateway()
    access, project_id, batches, definition_id = await create_module(gateway)
    run = await batches.start_all(access, project_id, definition_id)

    first_page = await batches.inspect_results(access, project_id, run.id, limit=2)
    second_page = await batches.inspect_results(access, project_id, run.id, limit=2, offset=2)

    assert [record.input for record in first_page.items] == [{"load": 1}, {"load": 2}]
    assert first_page.next_offset == 2
    assert [record.input for record in second_page.items] == [{"load": 3}, {"load": 4}]
    assert second_page.next_offset == 4


@pytest.mark.asyncio
async def test_result_set_filters_then_sorts_before_pagination() -> None:
    access, project_id, batches, definition_id = await create_module(Gateway())
    run = await batches.start_all(access, project_id, definition_id)

    page = await batches.inspect_results(
        access,
        project_id,
        run.id,
        limit=2,
        filter_path="/structuredOutput/result",
        minimum=4,
        maximum=10,
        sort_path="/structuredOutput/result",
        descending=True,
    )

    assert [record.structured_output for record in page.items] == [
        {"result": 10},
        {"result": 8},
    ]
    assert page.next_offset == 2


@pytest.mark.asyncio
async def test_result_set_equality_and_numeric_summary_use_all_matching_records() -> None:
    access, project_id, batches, definition_id = await create_module(Gateway({4}))
    run = await batches.start_all(access, project_id, definition_id)

    page = await batches.inspect_results(
        access,
        project_id,
        run.id,
        limit=1,
        filter_path="/input/load",
        minimum=2,
        aggregate_path="/structuredOutput/result",
    )
    equal = await batches.inspect_results(
        access,
        project_id,
        run.id,
        filter_path="/input/load",
        equals=3,
    )

    assert page.summary.total_count == 4
    assert page.summary.succeeded_count == 3
    assert page.summary.failed_count == 1
    assert page.summary.numeric_count == 3
    assert page.summary.numeric_sum == 20
    assert page.summary.numeric_min == 4
    assert page.summary.numeric_max == 10
    assert page.summary.numeric_average == pytest.approx(20 / 3)
    assert [record.input for record in equal.items] == [{"load": 3}]


@pytest.mark.asyncio
async def test_result_set_http_query_returns_a_filtered_page_and_summary() -> None:
    access, project_id, batches, definition_id = await create_module(Gateway())
    run = await batches.start_all(access, project_id, definition_id)
    app = FastAPI()
    app.include_router(
        create_batch_execution_router(
            create_identity_module(Settings(environment="test", fixed_identity_subject="sam")),
            batches,
        ),
        prefix="/api",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        run_response = await client.get(f"/api/projects/{project_id}/batch-runs/{run.id}")
        response = await client.get(
            f"/api/projects/{project_id}/batch-runs/{run.id}/results",
            params={
                "filter_path": "/input/load",
                "minimum": 2,
                "limit": 1,
                "sort_path": "/structuredOutput/result",
                "descending": "true",
                "aggregate_path": "/structuredOutput/result",
            },
        )

    assert response.status_code == 200
    assert run_response.status_code == 200
    assert "records" not in run_response.json()
    assert run_response.json()["recordCount"] == 5
    assert run_response.json()["definitionName"] == "Double loads"
    assert run_response.json()["succeededCount"] == 5
    assert run_response.json()["initiatorSubject"] == "sam"
    assert run_response.json()["initiation"] == {
        "kind": "directUser",
        "approval": "notRequired",
        "threadId": None,
        "agentRunId": None,
        "toolCallId": None,
    }
    assert response.json()["items"][0]["structuredOutput"] == {"result": 10}
    assert response.json()["nextOffset"] == 1
    assert response.json()["summary"]["numericSum"] == 28


@pytest.mark.asyncio
async def test_repeated_idempotency_key_returns_the_original_run_without_reexecution() -> None:
    gateway = Gateway()
    access, project_id, batches, definition_id = await create_module(gateway)

    first = await batches.start_all(access, project_id, definition_id, "retry-123")
    repeated = await batches.start_all(access, project_id, definition_id, "retry-123")

    assert repeated == first
    assert len(gateway.calls) == 5


@pytest.mark.asyncio
async def test_approved_agent_batch_replay_retains_one_run_and_its_initiation() -> None:
    access, project_id, batches, definition_id = await create_module(Gateway())
    initiation = BatchInitiation(
        kind="agentRun",
        approval="approved",
        thread_id="thread-1",
        agent_run_id="agent-run-1",
        tool_call_id="call-1",
    )

    first = await batches.submit_all(
        access, project_id, definition_id, "agent-batch-call-1", initiation=initiation
    )
    replayed = await batches.submit_all(
        access, project_id, definition_id, "agent-batch-call-1", initiation=initiation
    )

    assert replayed.id == first.id
    assert first.initiation == {
        "kind": "agentRun",
        "approval": "approved",
        "threadId": "thread-1",
        "agentRunId": "agent-run-1",
        "toolCallId": "call-1",
    }
    assert (await batches.list(access, project_id)).items == (first,)


@pytest.mark.asyncio
async def test_enqueuing_the_same_batch_run_twice_executes_it_once() -> None:
    gateway = Gateway()
    access, project_id, batches, definition_id = await create_module(gateway)
    queued = await batches.submit_all(access, project_id, definition_id)

    first = await batches.enqueue(access, project_id, queued.id)
    second = await batches.enqueue(access, project_id, queued.id)
    completed = await first

    assert first is second
    assert completed.status is BatchRunStatus.succeeded
    assert gateway.calls == [1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_a_user_can_archive_a_completed_batch_run_without_losing_its_result_set() -> None:
    gateway = Gateway()
    access, project_id, batches, definition_id = await create_module(gateway)
    run = await batches.start_all(access, project_id, definition_id)

    assert run.archived_at is None
    archived = await batches.archive(access, project_id, run.id)

    assert (await batches.list(access, project_id)).items == ()
    assert archived.archived_at is not None
    assert (await batches.load(access, project_id, run.id)) == archived
    assert [record.structured_output for record in archived.records] == [
        {"result": 2},
        {"result": 4},
        {"result": 6},
        {"result": 8},
        {"result": 10},
    ]


@pytest.mark.asyncio
async def test_restart_reconciliation_fails_non_terminal_batch_runs() -> None:
    gateway = Gateway()
    access, project_id, batches, definition_id = await create_module(gateway)
    now = datetime.now(UTC)
    await batches._store.create_or_load(
        BatchRun("queued-run", project_id, definition_id, BatchRunStatus.queued, {}, (), now, now)
    )

    assert await batches.reconcile_non_terminal() == 1
    assert (await batches.load(access, project_id, "queued-run")).status is BatchRunStatus.failed


@pytest.mark.asyncio
async def test_captured_run_can_be_reclaimed_and_completed_after_restart() -> None:
    gateway = Gateway()
    access, project_id, batches, definition_id = await create_module(gateway)
    queued = await batches.submit_all(access, project_id, definition_id)

    recovered = await batches.recover()
    completed = await recovered[0]

    assert len(recovered) == 1
    assert queued.initiator_subject == "sam"
    assert [record.input for record in queued.records] == [
        {"load": 1},
        {"load": 2},
        {"load": 3},
        {"load": 4},
        {"load": 5},
    ]
    assert completed.status is BatchRunStatus.succeeded
