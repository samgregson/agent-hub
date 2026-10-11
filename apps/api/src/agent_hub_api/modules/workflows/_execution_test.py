import asyncio
from collections.abc import Mapping
from typing import cast

import pytest

from agent_hub_api.modules.datasets import DatasetModule, DatasetRecordInput, MemoryDatasetStore
from agent_hub_api.modules.plugin_gateway import PluginGatewayModule, PluginToolResult
from agent_hub_api.modules.project_files import create_memory_project_files
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module
from agent_hub_api.modules.transforms import (
    MemoryTransformRunStore,
    MemoryTransformStore,
    TransformInitiation,
    TransformModule,
    TransformRun,
    TransformRuntimeIdentity,
)
from agent_hub_api.modules.workflows import (
    MemoryWorkflowRunStore,
    MemoryWorkflowStore,
    WorkflowDefinitionModule,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowNode,
    WorkflowOutput,
    WorkflowRunModule,
    WorkflowValidationError,
)


class _Schemas:
    async def input_schema(self, *_: object) -> dict[str, object]:
        return {"type": "object"}


class _Runner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.active_calls = 0
        self.maximum_active_calls = 0

    async def identity(self) -> TransformRuntimeIdentity:
        return TransformRuntimeIdentity("fixture", "fixture-hash")

    async def execute(
        self, source: str, inputs: dict[str, object], parameters: dict[str, object]
    ) -> tuple[object, str]:
        del parameters
        self.calls.append((source, inputs))
        self.active_calls += 1
        self.maximum_active_calls = max(self.maximum_active_calls, self.active_calls)
        await asyncio.sleep(0.01)
        self.active_calls -= 1
        if "# double" in source:
            value = cast(dict[str, int], inputs["record"])
            return {"value": value["value"] * 2}, "fixture"
        if "# triple" in source:
            value = cast(dict[str, int], inputs["record"])
            return {"value": value["value"] * 3}, "fixture"
        if "# combine" in source:
            left = cast(list[dict[str, int]], inputs["left"])
            right = cast(list[dict[str, int]], inputs["right"])
            return {"total": sum(item["value"] for item in left + right)}, "fixture"
        if "# template" in source:
            return {"template": inputs["template"]}, "fixture"
        raise AssertionError("Unexpected transform source")


@pytest.mark.asyncio
async def test_workflow_captures_project_file_content_before_execution() -> None:
    projects = create_memory_project_module()
    access = ProjectAccess(subject="owner")
    project = await projects.create(access, "Workflow files")
    datasets = DatasetModule(projects, MemoryDatasetStore(), _Schemas())
    project_files = create_memory_project_files(projects)
    file = await project_files.write(project.id, "/calculations/check.py", "template-v1")
    runner = _Runner()
    transforms = TransformModule(
        projects, MemoryTransformStore(), runner, MemoryTransformRunStore()
    )
    function = await transforms.define(
        access,
        project.id,
        "Use template",
        "# template\ndef transform(inputs, parameters):\n    return {}\n",
        {"template": ""},
        {
            "type": "object",
            "required": ["template"],
            "properties": {"template": {"type": "string"}},
        },
    )
    definitions = WorkflowDefinitionModule(
        projects,
        datasets,
        transforms,
        None,
        MemoryWorkflowStore(),
        project_files=project_files,
    )
    graph = WorkflowGraph(
        (
            WorkflowNode("file", "file", f"/project{file.path}", file.version),
            WorkflowNode("function", "python", function.id, function.revision),
        ),
        (WorkflowEdge("file", "content", "function", "template"),),
        (WorkflowOutput("rendered", "function", "result"),),
    )
    definition = await definitions.create(access, project.id, "Use a project file", graph)
    runs = WorkflowRunModule(
        definitions,
        datasets,
        transforms,
        None,
        MemoryWorkflowRunStore(),
        project_files=project_files,
    )

    prepared = await runs.prepare(access, project.id, definition.id, "file-run", expected_version=1)
    await project_files.write(project.id, file.path, "template-v2")
    with pytest.raises(WorkflowValidationError, match="Project File version changed"):
        await runs.prepare(access, project.id, definition.id, "new-file-run", expected_version=1)
    completed = await runs.execute(access, project.id, prepared.id)

    assert completed.status == "succeeded", completed.execution
    sources = cast(dict[str, object], prepared.snapshot["sources"])
    assert sources["file"] == {
        "path": f"/project{file.path}",
        "version": 1,
        "content": "template-v1",
    }
    nodes = cast(dict[str, object], completed.execution["nodes"])
    assert cast(dict[str, object], nodes["function"])["inputs"] == {"template": "template-v1"}
    assert completed.execution["outputs"] == {"rendered": {"template": "template-v1"}}


@pytest.mark.asyncio
async def test_execute_runs_branching_python_map_dag_and_is_idempotent() -> None:
    projects = create_memory_project_module()
    access = ProjectAccess(subject="owner")
    project = await projects.create(access, "Workflow execution")
    datasets = DatasetModule(projects, MemoryDatasetStore(), _Schemas())
    dataset = await datasets.create_dataset(
        access,
        project.id,
        "Inputs",
        [DatasetRecordInput({"value": 2}), DatasetRecordInput({"value": 4})],
    )
    runner = _Runner()
    transform_runs = MemoryTransformRunStore()
    transforms = TransformModule(projects, MemoryTransformStore(), runner, transform_runs)
    double = await transforms.define(
        access,
        project.id,
        "Double",
        "# double\ndef transform(inputs, parameters):\n    return {}\n",
        {"record": ""},
        {"type": "object", "required": ["value"], "properties": {"value": {"type": "integer"}}},
    )
    triple = await transforms.define(
        access,
        project.id,
        "Triple",
        "# triple\ndef transform(inputs, parameters):\n    return {}\n",
        {"record": ""},
        {"type": "object", "required": ["value"], "properties": {"value": {"type": "integer"}}},
    )
    combine = await transforms.define(
        access,
        project.id,
        "Combine",
        "# combine\ndef transform(inputs, parameters):\n    return {}\n",
        {"left": "", "right": ""},
        {"type": "object", "required": ["total"], "properties": {"total": {"type": "integer"}}},
    )
    definitions = WorkflowDefinitionModule(
        projects, datasets, transforms, None, MemoryWorkflowStore()
    )
    graph = WorkflowGraph(
        (
            WorkflowNode("source", "dataset", dataset.id, dataset.version),
            WorkflowNode("double", "python", double.id, double.revision, shape="map"),
            WorkflowNode("triple", "python", triple.id, triple.revision, shape="map"),
            WorkflowNode("combine", "python", combine.id, combine.revision),
        ),
        (
            WorkflowEdge("source", "records", "double", "items"),
            WorkflowEdge("source", "records", "triple", "items"),
            WorkflowEdge("double", "result", "combine", "left"),
            WorkflowEdge("triple", "result", "combine", "right"),
        ),
        (WorkflowOutput("summary", "combine", "result"),),
    )
    definition = await definitions.create(access, project.id, "Calculate", graph)
    workflows = WorkflowRunModule(definitions, datasets, transforms, None, MemoryWorkflowRunStore())
    prepared = await workflows.prepare(
        access, project.id, definition.id, "request-1", expected_version=1
    )
    await datasets.update_dataset(
        access,
        project.id,
        dataset.id,
        "Inputs revised",
        [DatasetRecordInput({"value": 100})],
    )

    completed = await workflows.execute(access, project.id, prepared.id)

    assert completed.status == "succeeded"
    assert completed.execution["outputs"] == {"summary": {"total": 30}}
    nodes = cast(dict[str, object], completed.execution["nodes"])
    assert cast(dict[str, object], nodes["double"])["items"]
    assert len(runner.calls) == 5
    assert runner.maximum_active_calls >= 2
    assert await workflows.execute(access, project.id, prepared.id) == completed
    assert len(runner.calls) == 5


@pytest.mark.asyncio
async def test_recovery_reuses_completed_function_call_after_checkpoint_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects = create_memory_project_module()
    access = ProjectAccess(subject="owner")
    project = await projects.create(access, "Workflow recovery")
    datasets = DatasetModule(projects, MemoryDatasetStore(), _Schemas())
    dataset = await datasets.create_dataset(
        access,
        project.id,
        "Inputs",
        [DatasetRecordInput({"value": 2}), DatasetRecordInput({"value": 4})],
    )
    runner = _Runner()
    transforms = TransformModule(
        projects, MemoryTransformStore(), runner, MemoryTransformRunStore()
    )
    function = await transforms.define(
        access,
        project.id,
        "Double",
        "# double\ndef transform(inputs, parameters):\n    return {}\n",
        {"record": ""},
        {"type": "object", "required": ["value"], "properties": {"value": {"type": "integer"}}},
    )
    definitions = WorkflowDefinitionModule(
        projects, datasets, transforms, None, MemoryWorkflowStore()
    )
    graph = WorkflowGraph(
        (
            WorkflowNode("source", "dataset", dataset.id, dataset.version),
            WorkflowNode("map", "python", function.id, function.revision, shape="map"),
        ),
        (WorkflowEdge("source", "records", "map", "items"),),
        (WorkflowOutput("results", "map", "result"),),
    )
    definition = await definitions.create(access, project.id, "Double records", graph)
    store = MemoryWorkflowRunStore()
    workflows = WorkflowRunModule(definitions, datasets, transforms, None, store)
    prepared = await workflows.prepare(
        access, project.id, definition.id, "request-1", expected_version=1
    )
    start_function_call = transforms.start_function_call
    crashed = False

    async def crash_after_function_call(
        call_access: ProjectAccess,
        call_project_id: str,
        definition_id: str,
        inputs: Mapping[str, object],
        parameters: Mapping[str, object],
        *,
        expected_revision: int,
        initiation: TransformInitiation | None = None,
        run_id: str | None = None,
    ) -> TransformRun:
        nonlocal crashed
        child = await start_function_call(
            call_access,
            call_project_id,
            definition_id,
            inputs,
            parameters,
            expected_revision=expected_revision,
            initiation=initiation,
            run_id=run_id,
        )
        if not crashed:
            crashed = True
            raise RuntimeError("simulated interruption after child completion")
        return child

    monkeypatch.setattr(transforms, "start_function_call", crash_after_function_call)
    with pytest.raises(RuntimeError, match="after child completion"):
        await workflows.execute(access, project.id, prepared.id)
    assert len(runner.calls) == 1

    assert await workflows.recover() == 1
    completed = await workflows.execute(access, project.id, prepared.id)

    assert completed.status == "succeeded"
    assert completed.execution["outputs"] == {"results": [{"value": 4}, {"value": 8}]}
    assert len(runner.calls) == 2


@pytest.mark.asyncio
async def test_mcp_workflow_without_structured_output_fails_after_dispatch() -> None:
    projects = create_memory_project_module()
    access = ProjectAccess(subject="owner")
    project = await projects.create(access, "Workflow execution")
    datasets = DatasetModule(projects, MemoryDatasetStore(), _Schemas())
    dataset = await datasets.create_dataset(
        access, project.id, "Inputs", [DatasetRecordInput({"value": 1})]
    )

    class Gateway:
        async def tool_version(self, *_: object) -> str:
            return "v1"

        async def input_schema(self, *_: object) -> dict[str, object]:
            return {"type": "object", "properties": {"items": {"type": "array"}}}

        async def output_schema(
            self, *_: object, require_repeat_safe: bool = False
        ) -> dict[str, object]:
            return {"type": "object"}

        async def call(self, *_: object) -> PluginToolResult:
            return PluginToolResult(("done",), None)

    transforms = TransformModule(projects, MemoryTransformStore())
    definitions = WorkflowDefinitionModule(
        projects,
        datasets,
        transforms,
        cast(PluginGatewayModule, Gateway()),
        MemoryWorkflowStore(),
    )
    graph = WorkflowGraph(
        (
            WorkflowNode("source", "dataset", dataset.id, dataset.version),
            WorkflowNode("remote", "mcp", "plugin", "v1", tool_name="run"),
        ),
        (WorkflowEdge("source", "records", "remote", "items"),),
        (WorkflowOutput("result", "remote", "result"),),
    )
    definition = await definitions.create(access, project.id, "Remote", graph)
    workflows = WorkflowRunModule(
        definitions,
        datasets,
        transforms,
        cast(PluginGatewayModule, Gateway()),
        MemoryWorkflowRunStore(),
    )
    prepared = await workflows.prepare(
        access, project.id, definition.id, "request-1", expected_version=1
    )

    completed = await workflows.execute(access, project.id, prepared.id)
    assert completed.status == "failed"
    assert completed.execution["error"] == {
        "nodeId": "remote",
        "code": "missing_structured_output",
    }


@pytest.mark.asyncio
async def test_recovery_does_not_repeat_an_unconfirmed_single_mcp_call() -> None:
    projects = create_memory_project_module()
    access = ProjectAccess(subject="owner")
    project = await projects.create(access, "Workflow recovery")
    datasets = DatasetModule(projects, MemoryDatasetStore(), _Schemas())
    dataset = await datasets.create_dataset(
        access, project.id, "Inputs", [DatasetRecordInput({"value": 1})]
    )

    class Gateway:
        calls = 0

        async def tool_version(self, *_: object) -> str:
            return "v1"

        async def input_schema(self, *_: object) -> dict[str, object]:
            return {
                "type": "object",
                "properties": {"items": {"type": "array"}},
                "required": ["items"],
            }

        async def output_schema(
            self, *_: object, require_repeat_safe: bool = False
        ) -> dict[str, object]:
            return {"type": "object"}

        async def call(self, *_: object) -> PluginToolResult:
            self.calls += 1
            raise RuntimeError("response lost after remote invocation")

    gateway = Gateway()
    transforms = TransformModule(projects, MemoryTransformStore())
    definitions = WorkflowDefinitionModule(
        projects,
        datasets,
        transforms,
        cast(PluginGatewayModule, gateway),
        MemoryWorkflowStore(),
    )
    graph = WorkflowGraph(
        (
            WorkflowNode("source", "dataset", dataset.id, dataset.version),
            WorkflowNode("remote", "mcp", "plugin", "v1", tool_name="count"),
        ),
        (WorkflowEdge("source", "records", "remote", "items"),),
        (WorkflowOutput("result", "remote", "result"),),
    )
    definition = await definitions.create(access, project.id, "Count", graph)
    workflows = WorkflowRunModule(
        definitions,
        datasets,
        transforms,
        cast(PluginGatewayModule, gateway),
        MemoryWorkflowRunStore(),
    )
    prepared = await workflows.prepare(
        access, project.id, definition.id, "request-1", expected_version=1
    )

    with pytest.raises(RuntimeError, match="response lost"):
        await workflows.execute(access, project.id, prepared.id)
    assert gateway.calls == 1

    assert await workflows.recover() == 1
    recovered = await workflows.execute(access, project.id, prepared.id)

    assert recovered.status == "failed"
    assert recovered.execution["error"] == {
        "nodeId": "remote",
        "code": "mcp_outcome_unknown",
    }
    assert gateway.calls == 1


@pytest.mark.asyncio
async def test_execute_dispatches_single_mcp_call_and_retains_output() -> None:
    projects = create_memory_project_module()
    access = ProjectAccess(subject="owner")
    project = await projects.create(access, "Workflow execution")
    datasets = DatasetModule(projects, MemoryDatasetStore(), _Schemas())
    dataset = await datasets.create_dataset(
        access, project.id, "Inputs", [DatasetRecordInput({"value": 2})]
    )

    class Gateway:
        calls: list[tuple[str, str, dict[str, object]]]

        def __init__(self) -> None:
            self.calls = []

        async def tool_version(self, *_: object) -> str:
            return "v1"

        async def input_schema(self, *_: object) -> dict[str, object]:
            return {
                "type": "object",
                "properties": {"items": {"type": "array"}},
                "required": ["items"],
            }

        async def output_schema(
            self, *_: object, require_repeat_safe: bool = False
        ) -> dict[str, object]:
            return {
                "type": "object",
                "required": ["count"],
                "properties": {"count": {"type": "integer"}},
            }

        async def call(
            self,
            _access: object,
            _project_id: str,
            plugin_id: str,
            tool_name: str,
            arguments: dict[str, object],
        ) -> PluginToolResult:
            self.calls.append((plugin_id, tool_name, arguments))
            return PluginToolResult((), {"count": len(cast(list[object], arguments["items"]))})

    gateway = Gateway()
    transforms = TransformModule(projects, MemoryTransformStore())
    definitions = WorkflowDefinitionModule(
        projects,
        datasets,
        transforms,
        cast(PluginGatewayModule, gateway),
        MemoryWorkflowStore(),
    )
    graph = WorkflowGraph(
        (
            WorkflowNode("source", "dataset", dataset.id, dataset.version),
            WorkflowNode("remote", "mcp", "plugin", "v1", tool_name="count"),
        ),
        (WorkflowEdge("source", "records", "remote", "items"),),
        (WorkflowOutput("result", "remote", "result"),),
    )
    definition = await definitions.create(access, project.id, "Count", graph)
    workflows = WorkflowRunModule(
        definitions,
        datasets,
        transforms,
        cast(PluginGatewayModule, gateway),
        MemoryWorkflowRunStore(),
    )
    prepared = await workflows.prepare(
        access, project.id, definition.id, "request-1", expected_version=1
    )

    completed = await workflows.execute(access, project.id, prepared.id)

    assert completed.status == "succeeded"
    assert completed.execution["outputs"] == {"result": {"count": 1}}
    nodes = cast(dict[str, object], completed.execution["nodes"])
    assert cast(dict[str, object], nodes["remote"])["output"] == {"count": 1}
    assert gateway.calls == [("plugin", "count", {"items": [{"value": 2}]})]


@pytest.mark.asyncio
async def test_execute_maps_repeat_safe_mcp_tool_over_captured_records() -> None:
    projects = create_memory_project_module()
    access = ProjectAccess(subject="owner")
    project = await projects.create(access, "Workflow execution")
    datasets = DatasetModule(projects, MemoryDatasetStore(), _Schemas())
    dataset = await datasets.create_dataset(
        access,
        project.id,
        "Inputs",
        [DatasetRecordInput({"value": 2}), DatasetRecordInput({"value": 5})],
    )

    class Gateway:
        calls: list[tuple[str, dict[str, object]]]

        def __init__(self) -> None:
            self.calls = []

        async def tool_version(self, *_: object) -> str:
            return "v1"

        async def input_schema(self, *_: object) -> dict[str, object]:
            return {
                "type": "object",
                "properties": {"value": {"type": "integer"}},
                "required": ["value"],
            }

        async def output_schema(
            self, *_: object, require_repeat_safe: bool = False
        ) -> dict[str, object]:
            assert require_repeat_safe
            return {
                "type": "object",
                "required": ["doubled"],
                "properties": {"doubled": {"type": "integer"}},
            }

        async def batch_call(
            self,
            _access: object,
            _project_id: str,
            _plugin_id: str,
            tool_name: str,
            arguments: dict[str, object],
        ) -> PluginToolResult:
            self.calls.append((tool_name, arguments))
            return PluginToolResult((), {"doubled": cast(int, arguments["value"]) * 2})

    gateway = Gateway()
    transforms = TransformModule(projects, MemoryTransformStore())
    definitions = WorkflowDefinitionModule(
        projects,
        datasets,
        transforms,
        cast(PluginGatewayModule, gateway),
        MemoryWorkflowStore(),
    )
    graph = WorkflowGraph(
        (
            WorkflowNode("source", "dataset", dataset.id, dataset.version),
            WorkflowNode("mapped", "mcp", "plugin", "v1", shape="map", tool_name="double"),
        ),
        (WorkflowEdge("source", "records", "mapped", "items"),),
        (WorkflowOutput("results", "mapped", "result"),),
    )
    definition = await definitions.create(access, project.id, "Double values", graph)
    workflows = WorkflowRunModule(
        definitions,
        datasets,
        transforms,
        cast(PluginGatewayModule, gateway),
        MemoryWorkflowRunStore(),
    )
    prepared = await workflows.prepare(
        access, project.id, definition.id, "request-1", expected_version=1
    )

    completed = await workflows.execute(access, project.id, prepared.id)

    assert completed.status == "succeeded"
    assert completed.execution["outputs"] == {"results": [{"doubled": 4}, {"doubled": 10}]}
    node = cast(dict[str, object], cast(dict[str, object], completed.execution["nodes"])["mapped"])
    items = cast(list[dict[str, object]], node["items"])
    assert [item["itemId"] for item in items] == [record.id for record in dataset.records]
    assert gateway.calls == [("double", {"value": 2}), ("double", {"value": 5})]


@pytest.mark.asyncio
async def test_changed_python_target_fails_explicitly_after_snapshot_preparation() -> None:
    projects = create_memory_project_module()
    access = ProjectAccess(subject="owner")
    project = await projects.create(access, "Workflow execution")
    datasets = DatasetModule(projects, MemoryDatasetStore(), _Schemas())
    dataset = await datasets.create_dataset(
        access, project.id, "Inputs", [DatasetRecordInput({"value": 1})]
    )
    transforms = TransformModule(
        projects, MemoryTransformStore(), _Runner(), MemoryTransformRunStore()
    )
    function = await transforms.define(
        access,
        project.id,
        "Double",
        "# double\ndef transform(inputs, parameters):\n    return {}\n",
        {"record": ""},
        {"type": "object", "required": ["value"], "properties": {"value": {"type": "integer"}}},
    )
    definitions = WorkflowDefinitionModule(
        projects, datasets, transforms, None, MemoryWorkflowStore()
    )
    graph = WorkflowGraph(
        (
            WorkflowNode("source", "dataset", dataset.id, dataset.version),
            WorkflowNode("double", "python", function.id, function.revision),
        ),
        (WorkflowEdge("source", "records", "double", "record"),),
        (WorkflowOutput("result", "double", "result"),),
    )
    definition = await definitions.create(access, project.id, "Double records", graph)
    workflows = WorkflowRunModule(definitions, datasets, transforms, None, MemoryWorkflowRunStore())
    prepared = await workflows.prepare(
        access, project.id, definition.id, "request-1", expected_version=1
    )
    await transforms.revise(
        access,
        project.id,
        function.id,
        "Double revised",
        "# double\ndef transform(inputs, parameters):\n    return {}\n",
        {"record": ""},
        {"type": "object", "required": ["value"], "properties": {"value": {"type": "integer"}}},
    )

    completed = await workflows.execute(access, project.id, prepared.id)

    assert completed.status == "failed"
    assert completed.execution["error"] == {"nodeId": "double", "code": "stale_target"}
