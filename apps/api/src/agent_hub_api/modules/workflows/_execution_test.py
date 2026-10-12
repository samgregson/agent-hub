import asyncio
from collections.abc import Mapping
from typing import cast

import pytest

from agent_hub_api.modules.datasets import DatasetModule, DatasetRecordInput, MemoryDatasetStore
from agent_hub_api.modules.functions import (
    FunctionModule,
    FunctionRuntimeIdentity,
    MemoryFunctionStore,
)
from agent_hub_api.modules.plugin_gateway import PluginGatewayModule, PluginToolResult
from agent_hub_api.modules.project_files import create_memory_project_files
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module
from agent_hub_api.modules.workflows import (
    MemoryWorkflowRunStore,
    MemoryWorkflowStore,
    WorkflowDefinitionModule,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowInput,
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
        self.active_by_function: dict[str, int] = {}
        self.maximum_active_by_function: dict[str, int] = {}

    async def identity(self) -> FunctionRuntimeIdentity:
        return FunctionRuntimeIdentity("fixture", "fixture-hash")

    async def execute(
        self, source: str, inputs: dict[str, object], parameters: dict[str, object]
    ) -> tuple[object, str]:
        del parameters
        self.calls.append((source, inputs))
        marker = next(
            (
                name
                for name in (
                    "# double",
                    "# triple",
                    "# combine",
                    "# template",
                    "# bind",
                    "# map-bindings",
                )
                if name in source
            ),
            "unknown",
        )
        self.active_calls += 1
        self.maximum_active_calls = max(self.maximum_active_calls, self.active_calls)
        self.active_by_function[marker] = self.active_by_function.get(marker, 0) + 1
        self.maximum_active_by_function[marker] = max(
            self.maximum_active_by_function.get(marker, 0), self.active_by_function[marker]
        )
        await asyncio.sleep(0.01)
        self.active_calls -= 1
        self.active_by_function[marker] -= 1
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
        if "# bind" in source:
            return inputs["payload"], "fixture"
        if "# map-bindings" in source:
            record = cast(dict[str, int], inputs["record"])
            return {"value": record["value"] * int(cast(float, inputs["scale"]))}, "fixture"
        raise AssertionError("Unexpected transform source")


@pytest.mark.asyncio
async def test_workflow_captures_project_file_content_before_execution() -> None:
    projects = create_memory_project_module()
    access = ProjectAccess(subject="owner")
    project = await projects.create(access, "Workflow files")
    datasets = DatasetModule(projects, MemoryDatasetStore())
    project_files = create_memory_project_files(projects)
    file = await project_files.write(project.id, "/calculations/check.py", "template-v1")
    runner = _Runner()
    functions = FunctionModule(projects, MemoryFunctionStore(), runner)
    function = await functions.define(
        access,
        project.id,
        "Use template",
        "# template\ndef transform(inputs, parameters):\n    return {}\n",
        {
            "type": "object",
            "properties": {"template": {"type": "string"}},
            "required": ["template"],
        },
        {
            "type": "object",
            "required": ["template"],
            "properties": {"template": {"type": "string"}},
        },
    )
    definitions = WorkflowDefinitionModule(
        projects,
        datasets,
        functions,
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
        functions,
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
async def test_workflow_captures_and_resolves_runtime_and_literal_bindings() -> None:
    projects = create_memory_project_module()
    access = ProjectAccess(subject="owner")
    project = await projects.create(access, "Workflow bindings")
    datasets = DatasetModule(projects, MemoryDatasetStore())
    dataset = await datasets.create_dataset(
        access,
        project.id,
        "Source records",
        [DatasetRecordInput({"oldName": "beam A"})],
    )
    runner = _Runner()
    functions = FunctionModule(projects, MemoryFunctionStore(), runner)
    function = await functions.define(
        access,
        project.id,
        "Assemble payload",
        "# bind\ndef transform(inputs, parameters):\n    return inputs['payload']\n",
        {
            "type": "object",
            "properties": {
                "payload": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "operator": {"type": "string"},
                        "retry_count": {"type": "integer"},
                    },
                    "required": ["label", "operator", "retry_count"],
                    "additionalProperties": False,
                }
            },
            "required": ["payload"],
        },
        {"type": "object"},
    )
    definitions = WorkflowDefinitionModule(
        projects, datasets, functions, None, MemoryWorkflowStore()
    )
    graph = WorkflowGraph(
        nodes=(
            WorkflowNode("source", "dataset", dataset.id, dataset.version),
            WorkflowNode("target", "python", function.id, function.revision),
        ),
        edges=(
            WorkflowEdge(
                "source",
                "records",
                "target",
                "payload",
                source_path="/0/oldName",
                target_path="/label",
            ),
            WorkflowEdge(
                None,
                None,
                "target",
                "payload",
                source_kind="workflowInput",
                source_input="request",
                source_path="/operatorName",
                target_path="/operator",
            ),
            WorkflowEdge(
                None,
                None,
                "target",
                "payload",
                source_kind="literal",
                literal=3,
                target_path="/retry_count",
            ),
        ),
        outputs=(WorkflowOutput("payload", "target", "result"),),
        inputs=(
            WorkflowInput(
                "request",
                {
                    "type": "object",
                    "properties": {"operatorName": {"type": "string"}},
                    "required": ["operatorName"],
                },
            ),
        ),
    )
    definition = await definitions.create(access, project.id, "Assemble", graph)
    runs = WorkflowRunModule(definitions, datasets, functions, None, MemoryWorkflowRunStore())

    with pytest.raises(WorkflowValidationError, match="Missing required Workflow Inputs"):
        await runs.prepare(access, project.id, definition.id, "missing-input", expected_version=1)
    with pytest.raises(WorkflowValidationError, match="does not match"):
        await runs.prepare(
            access,
            project.id,
            definition.id,
            "invalid-input",
            expected_version=1,
            workflow_inputs={"request": {"operatorName": 3}},
        )
    prepared = await runs.prepare(
        access,
        project.id,
        definition.id,
        "binding-run",
        expected_version=1,
        workflow_inputs={"request": {"operatorName": "engineer"}},
    )
    completed = await runs.execute(access, project.id, prepared.id)

    assert prepared.snapshot["workflowInputs"] == {"request": {"operatorName": "engineer"}}
    assert completed.status == "succeeded", completed.execution
    nodes = cast(dict[str, object], completed.execution["nodes"])
    assert cast(dict[str, object], nodes["target"])["inputs"] == {
        "payload": {"label": "beam A", "operator": "engineer", "retry_count": 3}
    }
    assert completed.execution["outputs"] == {
        "payload": {"label": "beam A", "operator": "engineer", "retry_count": 3}
    }


@pytest.mark.asyncio
async def test_map_workflow_binds_selected_item_fields_and_shared_values() -> None:
    projects = create_memory_project_module()
    access = ProjectAccess(subject="owner")
    project = await projects.create(access, "Mapped bindings")
    datasets = DatasetModule(projects, MemoryDatasetStore())
    dataset = await datasets.create_dataset(
        access,
        project.id,
        "Legacy values",
        [DatasetRecordInput({"legacy": 2}), DatasetRecordInput({"legacy": 5})],
    )
    runner = _Runner()
    functions = FunctionModule(projects, MemoryFunctionStore(), runner)
    transform_source = """# map-bindings
def transform(inputs, parameters):
    return {"value": inputs["record"]["value"] * inputs["scale"]}
"""
    function = await functions.define(
        access,
        project.id,
        "Scale item",
        transform_source,
        {
            "type": "object",
            "properties": {
                "record": {
                    "type": "object",
                    "properties": {"value": {"type": "integer"}},
                    "required": ["value"],
                },
                "scale": {"type": "number"},
            },
            "required": ["record", "scale"],
        },
        {"type": "object", "properties": {"value": {"type": "integer"}}},
    )
    definitions = WorkflowDefinitionModule(
        projects, datasets, functions, None, MemoryWorkflowStore()
    )
    graph = WorkflowGraph(
        nodes=(
            WorkflowNode("source", "dataset", dataset.id, dataset.version),
            WorkflowNode(
                "scale",
                "python",
                function.id,
                function.revision,
                shape="map",
                map_input="record",
            ),
        ),
        edges=(
            WorkflowEdge(
                "source",
                "records",
                "scale",
                "items",
                source_path="/legacy",
                target_path="/value",
            ),
            WorkflowEdge(
                None,
                None,
                "scale",
                "scale",
                source_kind="literal",
                literal=4,
            ),
        ),
        outputs=(WorkflowOutput("values", "scale", "result"),),
    )
    definitions_saved = await definitions.create(access, project.id, "Scale values", graph)
    runs = WorkflowRunModule(definitions, datasets, functions, None, MemoryWorkflowRunStore())

    prepared = await runs.prepare(
        access, project.id, definitions_saved.id, "map-bindings", expected_version=1
    )
    completed = await runs.execute(access, project.id, prepared.id)

    assert completed.status == "succeeded", completed.execution
    nodes = cast(dict[str, object], completed.execution["nodes"])
    assert cast(dict[str, object], nodes["scale"])["inputs"] == {
        "items": [{"value": 2}, {"value": 5}],
        "scale": 4,
    }
    assert completed.execution["outputs"] == {"values": [{"value": 8}, {"value": 20}]}


@pytest.mark.asyncio
async def test_execute_runs_branching_python_map_dag_and_is_idempotent() -> None:
    projects = create_memory_project_module()
    access = ProjectAccess(subject="owner")
    project = await projects.create(access, "Workflow execution")
    datasets = DatasetModule(projects, MemoryDatasetStore())
    dataset = await datasets.create_dataset(
        access,
        project.id,
        "Inputs",
        [DatasetRecordInput({"value": 2}), DatasetRecordInput({"value": 4})],
    )
    runner = _Runner()
    functions = FunctionModule(projects, MemoryFunctionStore(), runner)
    double = await functions.define(
        access,
        project.id,
        "Double",
        "# double\ndef transform(inputs, parameters):\n    return {}\n",
        {"type": "object", "properties": {"record": {}}, "required": ["record"]},
        {"type": "object", "required": ["value"], "properties": {"value": {"type": "integer"}}},
    )
    triple = await functions.define(
        access,
        project.id,
        "Triple",
        "# triple\ndef transform(inputs, parameters):\n    return {}\n",
        {"type": "object", "properties": {"record": {}}, "required": ["record"]},
        {"type": "object", "required": ["value"], "properties": {"value": {"type": "integer"}}},
    )
    combine = await functions.define(
        access,
        project.id,
        "Combine",
        "# combine\ndef transform(inputs, parameters):\n    return {}\n",
        {"type": "object", "properties": {"left": {}, "right": {}}, "required": ["left", "right"]},
        {"type": "object", "required": ["total"], "properties": {"total": {"type": "integer"}}},
    )
    definitions = WorkflowDefinitionModule(
        projects, datasets, functions, None, MemoryWorkflowStore()
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
    workflows = WorkflowRunModule(definitions, datasets, functions, None, MemoryWorkflowRunStore())
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
    assert runner.maximum_active_by_function["# double"] == 2
    assert runner.maximum_active_calls <= 4
    assert await workflows.execute(access, project.id, prepared.id) == completed
    assert len(runner.calls) == 5


@pytest.mark.asyncio
async def test_recovery_reexecutes_function_when_workflow_checkpoint_was_not_saved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects = create_memory_project_module()
    access = ProjectAccess(subject="owner")
    project = await projects.create(access, "Workflow recovery")
    datasets = DatasetModule(projects, MemoryDatasetStore())
    dataset = await datasets.create_dataset(
        access,
        project.id,
        "Inputs",
        [DatasetRecordInput({"value": 2}), DatasetRecordInput({"value": 4})],
    )
    runner = _Runner()
    functions = FunctionModule(projects, MemoryFunctionStore(), runner)
    function = await functions.define(
        access,
        project.id,
        "Double",
        "# double\ndef transform(inputs, parameters):\n    return {}\n",
        {"type": "object", "properties": {"record": {}}, "required": ["record"]},
        {"type": "object", "required": ["value"], "properties": {"value": {"type": "integer"}}},
    )
    definitions = WorkflowDefinitionModule(
        projects, datasets, functions, None, MemoryWorkflowStore()
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
    workflows = WorkflowRunModule(definitions, datasets, functions, None, store)
    prepared = await workflows.prepare(
        access, project.id, definition.id, "request-1", expected_version=1
    )
    execute_function = functions.execute_workflow_function
    crashed = False

    async def crash_after_function_execution(
        call_access: ProjectAccess,
        call_project_id: str,
        snapshot: Mapping[str, object],
        inputs: Mapping[str, object],
    ) -> object:
        nonlocal crashed
        output = await execute_function(call_access, call_project_id, snapshot, inputs)
        if not crashed:
            crashed = True
            raise RuntimeError("simulated interruption before workflow checkpoint")
        return output

    monkeypatch.setattr(functions, "execute_workflow_function", crash_after_function_execution)
    with pytest.raises(RuntimeError, match="before workflow checkpoint"):
        await workflows.execute(access, project.id, prepared.id)
    assert len(runner.calls) == 2

    assert await workflows.recover() == 1
    completed = await workflows.execute(access, project.id, prepared.id)

    assert completed.status == "succeeded"
    assert completed.execution["outputs"] == {"results": [{"value": 4}, {"value": 8}]}
    assert len(runner.calls) == 3


@pytest.mark.asyncio
async def test_mcp_workflow_without_structured_output_fails_after_dispatch() -> None:
    projects = create_memory_project_module()
    access = ProjectAccess(subject="owner")
    project = await projects.create(access, "Workflow execution")
    datasets = DatasetModule(projects, MemoryDatasetStore())
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

    functions = FunctionModule(projects, MemoryFunctionStore())
    definitions = WorkflowDefinitionModule(
        projects,
        datasets,
        functions,
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
        functions,
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
    datasets = DatasetModule(projects, MemoryDatasetStore())
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
    functions = FunctionModule(projects, MemoryFunctionStore())
    definitions = WorkflowDefinitionModule(
        projects,
        datasets,
        functions,
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
        functions,
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
    datasets = DatasetModule(projects, MemoryDatasetStore())
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
    functions = FunctionModule(projects, MemoryFunctionStore())
    definitions = WorkflowDefinitionModule(
        projects,
        datasets,
        functions,
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
        functions,
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
@pytest.mark.parametrize("first_item_succeeds", [True, False])
async def test_execute_maps_repeat_safe_mcp_tool_over_captured_records(
    first_item_succeeds: bool,
) -> None:
    projects = create_memory_project_module()
    access = ProjectAccess(subject="owner")
    project = await projects.create(access, "Workflow execution")
    datasets = DatasetModule(projects, MemoryDatasetStore())
    dataset = await datasets.create_dataset(
        access,
        project.id,
        "Inputs",
        [DatasetRecordInput({"value": value}) for value in range(2, 7)],
    )

    class Gateway:
        calls: list[tuple[str, dict[str, object]]]

        def __init__(self, *, first_item_succeeds: bool) -> None:
            self.calls = []
            self.active_calls = 0
            self.maximum_active_calls = 0
            self.first_item_completed = False
            self.first_item_succeeds = first_item_succeeds

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
            value = cast(int, arguments["value"])
            if value != 2:
                assert self.first_item_completed
            self.active_calls += 1
            self.maximum_active_calls = max(self.maximum_active_calls, self.active_calls)
            await asyncio.sleep(0.01)
            self.active_calls -= 1
            if value == 2:
                self.first_item_completed = True
                if not self.first_item_succeeds:
                    return PluginToolResult((), None)
            return PluginToolResult((), {"doubled": value * 2})

    gateway = Gateway(first_item_succeeds=first_item_succeeds)
    functions = FunctionModule(projects, MemoryFunctionStore())
    definitions = WorkflowDefinitionModule(
        projects,
        datasets,
        functions,
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
        functions,
        cast(PluginGatewayModule, gateway),
        MemoryWorkflowRunStore(),
    )
    prepared = await workflows.prepare(
        access, project.id, definition.id, "request-1", expected_version=1
    )

    completed = await workflows.execute(access, project.id, prepared.id)

    if not first_item_succeeds:
        assert completed.status == "failed"
        assert cast(dict[str, object], completed.execution["error"])["code"] == (
            "missing_structured_output"
        )
        assert gateway.calls == [("double", {"value": 2})]
        return

    assert completed.status == "succeeded"
    assert completed.execution["outputs"] == {
        "results": [{"doubled": value * 2} for value in range(2, 7)]
    }
    node = cast(dict[str, object], cast(dict[str, object], completed.execution["nodes"])["mapped"])
    items = cast(list[dict[str, object]], node["items"])
    assert [item["itemId"] for item in items] == [record.id for record in dataset.records]
    assert gateway.calls[0] == ("double", {"value": 2})
    assert {cast(int, arguments["value"]) for _, arguments in gateway.calls} == set(range(2, 7))
    assert gateway.maximum_active_calls >= 2
    assert gateway.maximum_active_calls <= 4


@pytest.mark.asyncio
async def test_beam_workflow_maps_checks_filters_collection_then_maps_followups() -> None:
    projects = create_memory_project_module()
    access = ProjectAccess(subject="owner")
    project = await projects.create(access, "Beam workflow")
    datasets = DatasetModule(projects, MemoryDatasetStore())
    dataset = await datasets.create_dataset(
        access,
        project.id,
        "Floor beams",
        [
            DatasetRecordInput(
                {
                    "beam_ref": "B-12",
                    "span_m": 6,
                    "imposed_load_kn_m2": 3,
                    "tributary_width_m": 3,
                    "elastic_modulus_gpa": 210,
                    "inertia_mm4": 40_000_000,
                    "deflection_limit_ratio": 360,
                }
            ),
            DatasetRecordInput(
                {
                    "beam_ref": "B-13",
                    "span_m": 5,
                    "imposed_load_kn_m2": 2.5,
                    "tributary_width_m": 3,
                    "elastic_modulus_gpa": 210,
                    "inertia_mm4": 40_000_000,
                    "deflection_limit_ratio": 360,
                }
            ),
            DatasetRecordInput(
                {
                    "beam_ref": "B-14",
                    "span_m": 7,
                    "imposed_load_kn_m2": 3,
                    "tributary_width_m": 3,
                    "elastic_modulus_gpa": 210,
                    "inertia_mm4": 100_000_000,
                    "deflection_limit_ratio": 360,
                }
            ),
        ],
    )
    sizing_fields = (
        "beam_ref",
        "span_m",
        "imposed_load_kn_m2",
        "tributary_width_m",
        "elastic_modulus_gpa",
        "limit_mm",
        "trial_inertia_mm4",
        "trial_deflection_mm",
    )

    class Gateway:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        async def tool_version(self, *_: object) -> str:
            return "1.0.0"

        async def input_schema(
            self, _access: object, _project_id: str, _plugin: str, name: str
        ) -> dict[str, object]:
            fields = (
                (
                    "beam_ref",
                    "span_m",
                    "imposed_load_kn_m2",
                    "tributary_width_m",
                    "elastic_modulus_gpa",
                    "inertia_mm4",
                    "deflection_limit_ratio",
                )
                if name == "check_uniform_beam_deflection"
                else sizing_fields
                if name == "size_for_deflection"
                else (*sizing_fields, "minimum_inertia_mm4")
            )
            return {
                "type": "object",
                "properties": {field: {} for field in fields},
                "required": list(fields),
            }

        async def output_schema(
            self, *_: object, require_repeat_safe: bool = False
        ) -> dict[str, object]:
            if require_repeat_safe:
                return {"type": "object"}
            return {"type": "object"}

        async def batch_call(
            self,
            _access: object,
            _project_id: str,
            _plugin: str,
            name: str,
            arguments: dict[str, object],
        ) -> PluginToolResult:
            self.calls.append((name, arguments))
            if name == "check_uniform_beam_deflection":
                span_mm = cast(float, arguments["span_m"]) * 1000
                line_load = cast(float, arguments["imposed_load_kn_m2"]) * cast(
                    float, arguments["tributary_width_m"]
                )
                deflection = (
                    5
                    * line_load
                    * span_mm**4
                    / (
                        384
                        * cast(float, arguments["elastic_modulus_gpa"])
                        * 1000
                        * cast(float, arguments["inertia_mm4"])
                    )
                )
                limit = span_mm / cast(float, arguments["deflection_limit_ratio"])
                return PluginToolResult(
                    (),
                    {
                        **arguments,
                        "maximum_deflection_mm": deflection,
                        "limit_mm": limit,
                        "check_status": "fails" if deflection > limit else "passes",
                    },
                )
            if name == "size_for_deflection":
                return PluginToolResult(
                    (),
                    {
                        **arguments,
                        "minimum_inertia_mm4": 43_392_857.14285714,
                    },
                )
            assert name == "draft_beam_review_note"
            return PluginToolResult(
                (),
                {"beam_ref": arguments["beam_ref"], "note": "Review only"},
            )

    class BeamFunctionRunner:
        async def identity(self) -> FunctionRuntimeIdentity:
            return FunctionRuntimeIdentity("fixture", "fixture-hash")

        async def execute(
            self, source: str, inputs: dict[str, object], parameters: dict[str, object]
        ) -> tuple[object, str]:
            del parameters
            assert 'if item["check_status"] == "fails"' in source
            items = cast(list[dict[str, object]], inputs["items"])
            selected = [item for item in items if item["check_status"] == "fails"]
            return [
                {
                    "beam_ref": item["beam_ref"],
                    "span_m": item["span_m"],
                    "imposed_load_kn_m2": item["imposed_load_kn_m2"],
                    "tributary_width_m": item["tributary_width_m"],
                    "elastic_modulus_gpa": item["elastic_modulus_gpa"],
                    "limit_mm": item["limit_mm"],
                    "trial_inertia_mm4": item["inertia_mm4"],
                    "trial_deflection_mm": item["maximum_deflection_mm"],
                }
                for item in selected
            ], "fixture"

    gateway = Gateway()
    functions = FunctionModule(projects, MemoryFunctionStore(), BeamFunctionRunner())
    filtered = await functions.define(
        access,
        project.id,
        "Filter failed checks",
        """def transform(inputs, parameters):
    return [
        {
            "beam_ref": item["beam_ref"],
            "span_m": item["span_m"],
            "imposed_load_kn_m2": item["imposed_load_kn_m2"],
            "tributary_width_m": item["tributary_width_m"],
            "elastic_modulus_gpa": item["elastic_modulus_gpa"],
            "limit_mm": item["limit_mm"],
            "trial_inertia_mm4": item["inertia_mm4"],
            "trial_deflection_mm": item["maximum_deflection_mm"],
        }
        for item in inputs["items"]
        if item["check_status"] == "fails"
    ]
""",
        {
            "type": "object",
            "properties": {"items": {"type": "array", "items": {"type": "object"}}},
            "required": ["items"],
        },
        {"type": "array", "items": {"type": "object"}},
    )
    gateway_module = cast(PluginGatewayModule, gateway)
    definitions = WorkflowDefinitionModule(
        projects, datasets, functions, gateway_module, MemoryWorkflowStore()
    )
    graph = WorkflowGraph(
        (
            WorkflowNode("source", "dataset", dataset.id, dataset.version),
            WorkflowNode(
                "check",
                "mcp",
                "reference-calculation",
                "1.0.0",
                shape="map",
                tool_name="check_uniform_beam_deflection",
            ),
            WorkflowNode("filter", "python", filtered.id, filtered.revision),
            WorkflowNode(
                "size",
                "mcp",
                "reference-calculation",
                "1.0.0",
                shape="map",
                tool_name="size_for_deflection",
            ),
            WorkflowNode(
                "note",
                "mcp",
                "reference-calculation",
                "1.0.0",
                shape="map",
                tool_name="draft_beam_review_note",
            ),
        ),
        (
            WorkflowEdge("source", "records", "check", "items"),
            WorkflowEdge("check", "result", "filter", "items"),
            WorkflowEdge("filter", "result", "size", "items"),
            WorkflowEdge("size", "result", "note", "items"),
        ),
        (
            WorkflowOutput("checks", "check", "result"),
            WorkflowOutput("failed", "filter", "result"),
            WorkflowOutput("sizes", "size", "result"),
            WorkflowOutput("notes", "note", "result"),
        ),
    )
    definition = await definitions.create(access, project.id, "Beam check", graph)
    runs = WorkflowRunModule(
        definitions, datasets, functions, gateway_module, MemoryWorkflowRunStore()
    )

    prepared = await runs.prepare(
        access, project.id, definition.id, "beam-demo", expected_version=definition.version
    )
    completed = await runs.execute(access, project.id, prepared.id)

    assert completed.status == "succeeded", completed.execution
    outputs = cast(dict[str, object], completed.execution["outputs"])
    assert [item["beam_ref"] for item in cast(list[dict[str, object]], outputs["failed"])] == [
        "B-12"
    ]
    assert cast(list[dict[str, object]], outputs["sizes"])[0]["minimum_inertia_mm4"] == (
        43_392_857.14285714
    )
    assert cast(list[dict[str, object]], outputs["notes"]) == [
        {"beam_ref": "B-12", "note": "Review only"}
    ]
    assert [name for name, _ in gateway.calls].count("check_uniform_beam_deflection") == 3
    assert [name for name, _ in gateway.calls].count("size_for_deflection") == 1
    assert [name for name, _ in gateway.calls].count("draft_beam_review_note") == 1
    check_node = cast(
        dict[str, object], cast(dict[str, object], completed.execution["nodes"])["check"]
    )
    check_items = cast(list[dict[str, object]], check_node["items"])
    assert [item["itemId"] for item in check_items] == [record.id for record in dataset.records]


@pytest.mark.asyncio
async def test_mcp_map_merges_captured_project_file_input_into_each_dataset_record() -> None:
    projects = create_memory_project_module()
    access = ProjectAccess(subject="owner")
    project = await projects.create(access, "Workflow file map")
    datasets = DatasetModule(projects, MemoryDatasetStore())
    dataset = await datasets.create_dataset(
        access,
        project.id,
        "Inputs",
        [DatasetRecordInput({"load": 12}), DatasetRecordInput({"load": 18})],
    )
    project_files = create_memory_project_files(projects)
    file = await project_files.write(project.id, "/calculations/check.py", "template-v1")

    class Gateway:
        calls: list[dict[str, object]]

        def __init__(self) -> None:
            self.calls = []

        async def tool_version(self, *_: object) -> str:
            return "v1"

        async def input_schema(self, *_: object) -> dict[str, object]:
            return {
                "type": "object",
                "required": ["load", "template"],
                "properties": {
                    "load": {"type": "integer"},
                    "template": {"type": "string"},
                },
            }

        async def output_schema(
            self, *_: object, require_repeat_safe: bool = False
        ) -> dict[str, object]:
            assert require_repeat_safe
            return {"type": "object"}

        async def batch_call(
            self,
            _access: object,
            _project_id: str,
            _plugin_id: str,
            _tool_name: str,
            arguments: dict[str, object],
        ) -> PluginToolResult:
            self.calls.append(arguments)
            return PluginToolResult((), {"load": arguments["load"]})

    gateway = Gateway()
    functions = FunctionModule(projects, MemoryFunctionStore())
    definitions = WorkflowDefinitionModule(
        projects,
        datasets,
        functions,
        cast(PluginGatewayModule, gateway),
        MemoryWorkflowStore(),
        project_files=project_files,
    )
    graph = WorkflowGraph(
        (
            WorkflowNode("dataset", "dataset", dataset.id, dataset.version),
            WorkflowNode("template", "file", f"/project{file.path}", file.version),
            WorkflowNode("calculate", "mcp", "plugin", "v1", shape="map", tool_name="check"),
        ),
        (
            WorkflowEdge("dataset", "records", "calculate", "items"),
            WorkflowEdge("template", "content", "calculate", "template"),
        ),
        (WorkflowOutput("results", "calculate", "result"),),
    )
    definition = await definitions.create(access, project.id, "Check records", graph)
    runs = WorkflowRunModule(
        definitions,
        datasets,
        functions,
        cast(PluginGatewayModule, gateway),
        MemoryWorkflowRunStore(),
        project_files=project_files,
    )

    prepared = await runs.prepare(
        access, project.id, definition.id, "request-1", expected_version=1
    )
    await project_files.write(project.id, file.path, "template-v2")
    completed = await runs.execute(access, project.id, prepared.id)

    assert completed.status == "succeeded", completed.execution
    assert gateway.calls == [
        {"load": 12, "template": "template-v1"},
        {"load": 18, "template": "template-v1"},
    ]
    assert completed.execution["outputs"] == {
        "results": [{"load": 12}, {"load": 18}],
    }


@pytest.mark.asyncio
async def test_workflow_uses_captured_python_target_after_definition_changes() -> None:
    projects = create_memory_project_module()
    access = ProjectAccess(subject="owner")
    project = await projects.create(access, "Workflow execution")
    datasets = DatasetModule(projects, MemoryDatasetStore())
    dataset = await datasets.create_dataset(
        access, project.id, "Inputs", [DatasetRecordInput({"value": 1})]
    )
    runner = _Runner()
    functions = FunctionModule(projects, MemoryFunctionStore(), runner)
    function = await functions.define(
        access,
        project.id,
        "Double",
        "# double\ndef transform(inputs, parameters):\n    return {}\n",
        {"type": "object", "properties": {"record": {}}, "required": ["record"]},
        {"type": "object", "required": ["value"], "properties": {"value": {"type": "integer"}}},
    )
    definitions = WorkflowDefinitionModule(
        projects, datasets, functions, None, MemoryWorkflowStore()
    )
    graph = WorkflowGraph(
        (
            WorkflowNode("source", "dataset", dataset.id, dataset.version),
            WorkflowNode("double", "python", function.id, function.revision, shape="map"),
        ),
        (WorkflowEdge("source", "records", "double", "items"),),
        (WorkflowOutput("result", "double", "result"),),
    )
    definition = await definitions.create(access, project.id, "Double records", graph)
    workflows = WorkflowRunModule(definitions, datasets, functions, None, MemoryWorkflowRunStore())
    prepared = await workflows.prepare(
        access, project.id, definition.id, "request-1", expected_version=1
    )
    await functions.revise(
        access,
        project.id,
        function.id,
        "Double revised",
        "# double\ndef transform(inputs, parameters):\n    return {}\n",
        {"type": "object", "properties": {"record": {}}, "required": ["record"]},
        {"type": "object", "required": ["value"], "properties": {"value": {"type": "integer"}}},
    )

    completed = await workflows.execute(access, project.id, prepared.id)

    assert completed.status == "succeeded"
    assert completed.execution["outputs"] == {"result": [{"value": 2}]}
