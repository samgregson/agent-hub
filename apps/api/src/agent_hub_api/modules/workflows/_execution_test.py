from typing import cast

import pytest

from agent_hub_api.modules.datasets import DatasetModule, DatasetRecordInput, MemoryDatasetStore
from agent_hub_api.modules.plugin_gateway import PluginGatewayModule
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module
from agent_hub_api.modules.transforms import (
    MemoryTransformRunStore,
    MemoryTransformStore,
    TransformModule,
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
    WorkflowRunConflict,
    WorkflowRunModule,
)


class _Schemas:
    async def input_schema(self, *_: object) -> dict[str, object]:
        return {"type": "object"}


class _Runner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def identity(self) -> TransformRuntimeIdentity:
        return TransformRuntimeIdentity("fixture", "fixture-hash")

    async def execute(
        self, source: str, inputs: dict[str, object], parameters: dict[str, object]
    ) -> tuple[object, str]:
        del parameters
        self.calls.append((source, inputs))
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
        raise AssertionError("Unexpected transform source")


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
    assert await workflows.execute(access, project.id, prepared.id) == completed
    assert len(runner.calls) == 5


@pytest.mark.asyncio
async def test_mcp_workflow_is_rejected_before_run_enters_execution() -> None:
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

    with pytest.raises(WorkflowRunConflict, match="MCP Workflow execution is not available"):
        await workflows.execute(access, project.id, prepared.id)
    assert (await workflows.load(access, project.id, prepared.id)).status == "prepared"


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
