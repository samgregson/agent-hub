from typing import cast

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from agent_hub_api.modules.datasets import DatasetModule, DatasetRecordInput, MemoryDatasetStore
from agent_hub_api.modules.functions import FunctionModule, MemoryFunctionStore
from agent_hub_api.modules.identity import create_identity_module
from agent_hub_api.modules.plugin_gateway import PluginGatewayModule, PluginToolNotAllowed
from agent_hub_api.modules.project_files import ProjectFileAccess, create_memory_project_files
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module
from agent_hub_api.modules.workflows import (
    MemoryWorkflowStore,
    WorkflowDefinitionModule,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowInput,
    WorkflowNode,
    WorkflowNotFound,
    WorkflowOutput,
    WorkflowValidationError,
    create_workflow_router,
)
from agent_hub_api.settings import Settings


class _Schemas:
    async def input_schema(self, *_: object) -> dict[str, object]:
        return {"type": "object"}


@pytest.mark.asyncio
async def test_nested_array_type_mismatch_reports_field_and_types() -> None:
    projects = create_memory_project_module()
    access = ProjectAccess(subject="owner")
    project = await projects.create(access, "Nested contracts")
    functions = FunctionModule(projects, MemoryFunctionStore())

    def item(kind: object) -> dict[str, object]:
        return {"type": "object", "properties": {"amount": {"type": kind}}, "required": ["amount"]}

    source = await functions.define(
        access,
        project.id,
        "Source",
        "def transform(inputs, parameters):\n    return {}\n",
        {"type": "object", "properties": {}},
        {
            "type": "object",
            "properties": {"records": {"type": "array", "items": item(["number", "null"])}},
        },
    )
    target = await functions.define(
        access,
        project.id,
        "Target",
        "def transform(inputs, parameters):\n    return {}\n",
        {
            "type": "object",
            "properties": {"records": {"type": "array", "items": item("number")}},
            "required": ["records"],
        },
        {"type": "object"},
    )
    workflows = WorkflowDefinitionModule(
        projects,
        DatasetModule(projects, MemoryDatasetStore()),
        functions,
        None,
        MemoryWorkflowStore(),
    )
    graph = WorkflowGraph(
        (
            WorkflowNode("source", "python", source.id, source.revision),
            WorkflowNode("target", "python", target.id, target.revision),
        ),
        (WorkflowEdge("source", "result", "target", "records", source_path="/records"),),
        (WorkflowOutput("result", "target", "result"),),
    )
    with pytest.raises(WorkflowValidationError) as error:
        await workflows.create(access, project.id, "Incompatible", graph)
    assert "/items/properties/amount" in str(error.value)
    assert "['null', 'number']" in str(error.value)
    assert "target types ['number']" in str(error.value)
    assert "Handle or reject null values" in str(error.value)
    assert "only when the source actually guarantees it" in str(error.value)
    assert await workflows.list(access, project.id) == ()


@pytest.mark.asyncio
async def test_creation_and_revision_report_independent_binding_errors_without_saving() -> None:
    projects = create_memory_project_module()
    access = ProjectAccess(subject="owner")
    project = await projects.create(access, "Bindings")
    files = create_memory_project_files(projects)
    source = await files.write(project.id, "/input.csv", "name,value\na,2\n")
    functions = FunctionModule(projects, MemoryFunctionStore())
    fn = await functions.define(
        access,
        project.id,
        "Process",
        "def transform(inputs, parameters):\n    return {}\n",
        {
            "type": "object",
            "properties": {"rows": {"type": "array"}, "label": {"type": "string"}},
            "required": ["rows", "label"],
        },
        {"type": "object"},
    )
    workflows = WorkflowDefinitionModule(
        projects,
        DatasetModule(projects, MemoryDatasetStore()),
        functions,
        None,
        MemoryWorkflowStore(),
        project_files=files,
    )
    nodes = (
        WorkflowNode("file", "file", "/project/input.csv", source.version),
        WorkflowNode("fn", "python", fn.id, fn.revision),
    )
    outputs = (WorkflowOutput("result", "fn", "result"),)
    invalid_map = WorkflowGraph(
        (
            nodes[0],
            WorkflowNode("fn", "python", fn.id, fn.revision, shape="map", map_input="inputs"),
        ),
        (WorkflowEdge("file", "content", "fn", "items"),),
        outputs,
    )
    with pytest.raises(WorkflowValidationError) as error:
        await workflows.create(access, project.id, "Invalid map", invalid_map)
    assert "map_input 'inputs'" in str(error.value)
    assert "'rows'" in str(error.value)
    assert "declare a single object input" in str(error.value)
    bad = WorkflowGraph(
        nodes,
        (
            WorkflowEdge("file", "content", "fn", "rows"),
            WorkflowEdge("file", "missing", "fn", "label"),
        ),
        outputs,
    )
    with pytest.raises(WorkflowValidationError) as error:
        await workflows.create(access, project.id, "Invalid", bad)
    assert len(error.value.diagnostics) == 2
    assert "source type 'string'" in error.value.diagnostics[0]
    assert "target type 'array'" in error.value.diagnostics[0]
    assert "parse or transform" in error.value.diagnostics[0]
    assert "do not assume its fields" in error.value.diagnostics[0]
    assert "missing" in error.value.diagnostics[1]
    assert await workflows.list(access, project.id) == ()
    good = WorkflowGraph(
        nodes,
        (
            WorkflowEdge("file", "content", "fn", "label"),
            WorkflowEdge(source_kind="literal", literal=[], target_node="fn", target_port="rows"),
        ),
        outputs,
    )
    saved = await workflows.create(access, project.id, "Valid", good)
    with pytest.raises(WorkflowValidationError) as revision_error:
        await workflows.revise(access, project.id, saved.id, "Invalid", bad, expected_version=1)
    assert revision_error.value.diagnostics == error.value.diagnostics
    assert (await workflows.load(access, project.id, saved.id)) == saved


@pytest.mark.asyncio
async def test_unknown_binding_identifies_node_port_and_available_ports() -> None:
    projects = create_memory_project_module()
    access = ProjectAccess(subject="owner")
    project = await projects.create(access, "Port diagnostics")
    files = create_memory_project_files(projects)
    source = await files.write(project.id, "/data.txt", "test")
    functions = FunctionModule(projects, MemoryFunctionStore())
    function = await functions.define(
        access,
        project.id,
        "Read",
        "def transform(inputs, parameters):\n    return {}\n",
        {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        {"type": "object"},
    )
    workflows = WorkflowDefinitionModule(
        projects,
        DatasetModule(projects, MemoryDatasetStore()),
        functions,
        None,
        MemoryWorkflowStore(),
        project_files=files,
    )
    nodes = (
        WorkflowNode("file", "file", "/project/data.txt", source.version),
        WorkflowNode("read", "python", function.id, function.revision),
    )
    outputs = (WorkflowOutput("output", "read", "result"),)
    for edge, expected in (
        (WorkflowEdge("file", "content", "read", "inputs"), ("read", "inputs", "text")),
        (WorkflowEdge("file", "missing", "read", "text"), ("file", "missing", "content")),
    ):
        with pytest.raises(WorkflowValidationError) as error:
            await workflows.validate_graph(
                access, project.id, WorkflowGraph(nodes, (edge,), outputs)
            )
        assert all(part in str(error.value) for part in expected)


@pytest.mark.asyncio
async def test_project_can_save_and_revise_a_branching_workflow_definition() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="owner")
    project = await projects.create(owner, "Analysis")
    datasets = DatasetModule(projects, MemoryDatasetStore())
    dataset = await datasets.create_dataset(
        owner, project.id, "Inputs", [DatasetRecordInput({"value": 2})]
    )
    functions = FunctionModule(projects, MemoryFunctionStore())
    map_function = await functions.define(
        owner,
        project.id,
        "Double",
        "def transform(inputs, parameters):\n    return {}\n",
        input_schema={
            "type": "object",
            "properties": {
                "item": {
                    "type": "object",
                    "properties": {"value": {"type": "number"}},
                    "required": ["value"],
                }
            },
            "required": ["item"],
        },
        output_schema={"type": "object"},
    )
    join_function = await functions.define(
        owner,
        project.id,
        "Compare",
        "def transform(inputs, parameters):\n    return {}\n",
        {
            "type": "object",
            "properties": {"left": {}, "right": {}},
            "required": ["left", "right"],
        },
        {"type": "object"},
    )
    workflows = WorkflowDefinitionModule(projects, datasets, functions, None, MemoryWorkflowStore())
    graph = WorkflowGraph(
        nodes=(
            WorkflowNode("source", "dataset", dataset.id, dataset.version),
            WorkflowNode("a", "python", map_function.id, map_function.revision, shape="map"),
            WorkflowNode("b", "python", map_function.id, map_function.revision, shape="map"),
            WorkflowNode("join", "python", join_function.id, join_function.revision),
        ),
        edges=(
            WorkflowEdge("source", "records", "a", "items"),
            WorkflowEdge("source", "records", "b", "items"),
            WorkflowEdge("a", "result", "join", "left"),
            WorkflowEdge("b", "result", "join", "right"),
        ),
        outputs=(WorkflowOutput("comparison", "join", "result"),),
    )
    saved = await workflows.create(owner, project.id, "Compare two branches", graph)
    assert saved.version == 1
    assert (await workflows.load(owner, project.id, saved.id)).graph == graph
    assert [item.id for item in await workflows.list(owner, project.id)] == [saved.id]
    with pytest.raises(WorkflowNotFound):
        await workflows.load(ProjectAccess(subject="other"), project.id, saved.id)
    revised = await workflows.revise(
        owner, project.id, saved.id, "Comparison", graph, expected_version=1
    )
    assert revised.version == 2
    assert revised.name == "Comparison"
    with pytest.raises(WorkflowValidationError, match="version changed"):
        await workflows.revise(owner, project.id, saved.id, "Stale", graph, expected_version=1)


@pytest.mark.asyncio
async def test_workflow_preflight_validates_without_saving_and_lists_file_sources() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="owner")
    project = await projects.create(owner, "Analysis")
    datasets = DatasetModule(projects, MemoryDatasetStore())
    functions = FunctionModule(projects, MemoryFunctionStore())
    files = create_memory_project_files(projects)
    saved_file = await files.create_visible(
        # The agent can inspect ordinary durable files before proposing a Workflow.
        ProjectFileAccess(subject="owner"),
        project.id,
        "/demo.txt",
        "sample",
    )
    workflows = WorkflowDefinitionModule(
        projects,
        datasets,
        functions,
        None,
        MemoryWorkflowStore(),
        project_files=files,
    )
    graph = WorkflowGraph(
        (WorkflowNode("source", "file", "/project/demo.txt", saved_file.version),),
        (),
        (WorkflowOutput("content", "source", "content"),),
    )

    await workflows.validate_graph(owner, project.id, graph)
    sources = await workflows.list_file_sources(owner, project.id)
    assert [(source.path, source.version) for source in sources] == [
        ("/project/demo.txt", saved_file.version)
    ]
    assert await workflows.list(owner, project.id) == ()

    invalid = WorkflowGraph(
        (WorkflowNode("missing", "python", "does-not-exist", 1),),
        (),
        (WorkflowOutput("result", "missing", "result"),),
    )
    with pytest.raises(WorkflowValidationError, match="does-not-exist"):
        await workflows.validate_graph(owner, project.id, invalid)

    function = await functions.define(
        owner,
        project.id,
        "summarize_text",
        "def transform(inputs, parameters):\n    return {'result': '', 'word_count': 0}\n",
        {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        {
            "type": "object",
            "properties": {"result": {"type": "string"}, "word_count": {"type": "integer"}},
        },
    )
    invalid_output = WorkflowGraph(
        (
            WorkflowNode("source", "file", "/project/demo.txt", saved_file.version),
            WorkflowNode("summarize", "python", function.id, function.revision),
        ),
        (WorkflowEdge("source", "content", "summarize", "text"),),
        (WorkflowOutput("word_count", "summarize", "word_count"),),
    )
    with pytest.raises(WorkflowValidationError, match="available ports: result"):
        await workflows.validate_graph(owner, project.id, invalid_output)

    invalid_input = WorkflowGraph(
        (
            WorkflowNode("source", "file", "/project/demo.txt", saved_file.version),
            WorkflowNode("summarize", "python", function.id, function.revision),
        ),
        (WorkflowEdge("source", "content", "summarize", "text"),),
        (WorkflowOutput("result", "summarize", "result"),),
    )
    incompatible_function = await functions.define(
        owner,
        project.id,
        "summarize_number",
        "def transform(inputs, parameters):\n    return {'result': str(inputs['text'])}\n",
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "integer"}},
            "required": ["text"],
            "additionalProperties": False,
        },
        output_schema={"type": "object", "properties": {"result": {"type": "string"}}},
    )
    invalid_input = WorkflowGraph(
        invalid_input.nodes[:1]
        + (WorkflowNode("summarize", "python", incompatible_function.id, 1),),
        invalid_input.edges,
        invalid_input.outputs,
    )
    with pytest.raises(WorkflowValidationError, match="incompatible.*text"):
        await workflows.validate_graph(owner, project.id, invalid_input)


@pytest.mark.asyncio
async def test_workflow_rejects_cycles_missing_ports_and_stale_targets() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="owner")
    project = await projects.create(owner, "Analysis")
    datasets = DatasetModule(projects, MemoryDatasetStore())
    functions = FunctionModule(projects, MemoryFunctionStore())
    function = await functions.define(
        owner,
        project.id,
        "Pass",
        "def transform(inputs, parameters):\n    return {}\n",
        {"type": "object", "properties": {"item": {}}, "required": ["item"]},
        {"type": "object"},
    )
    workflows = WorkflowDefinitionModule(projects, datasets, functions, None, MemoryWorkflowStore())
    node = WorkflowNode("a", "python", function.id, function.revision)
    with pytest.raises(WorkflowValidationError, match="cycle"):
        await workflows.create(
            owner,
            project.id,
            "Cycle",
            WorkflowGraph(
                (node,),
                (WorkflowEdge("a", "result", "a", "item"),),
                (WorkflowOutput("result", "a", "result"),),
            ),
        )
    with pytest.raises(WorkflowValidationError, match="required input"):
        await workflows.create(
            owner,
            project.id,
            "Unbound",
            WorkflowGraph((node,), (), (WorkflowOutput("result", "a", "result"),)),
        )
    with pytest.raises(WorkflowValidationError, match="version changed"):
        await workflows.create(
            owner,
            project.id,
            "Stale",
            WorkflowGraph(
                (WorkflowNode("a", "python", function.id, 99),),
                (),
                (WorkflowOutput("result", "a", "result"),),
            ),
        )


@pytest.mark.asyncio
async def test_workflow_accepts_field_bindings_from_inputs_and_literals() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="owner")
    project = await projects.create(owner, "Bindings")
    datasets = DatasetModule(projects, MemoryDatasetStore())
    functions = FunctionModule(projects, MemoryFunctionStore())
    target = await functions.define(
        owner,
        project.id,
        "Build payload",
        "def transform(inputs, parameters):\n    return inputs['payload']\n",
        {
            "type": "object",
            "properties": {
                "payload": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "retry_count": {"type": "integer"},
                    },
                    "required": ["label", "retry_count"],
                    "additionalProperties": False,
                }
            },
            "required": ["payload"],
        },
        {"type": "object"},
    )
    workflows = WorkflowDefinitionModule(projects, datasets, functions, None, MemoryWorkflowStore())
    graph = WorkflowGraph(
        nodes=(WorkflowNode("target", "python", target.id, target.revision),),
        edges=(
            WorkflowEdge(
                None,
                None,
                "target",
                "payload",
                source_kind="workflowInput",
                source_input="request",
                source_path="/displayName",
                target_path="/label",
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
                    "properties": {"displayName": {"type": "string"}},
                    "required": ["displayName"],
                },
            ),
        ),
    )

    saved = await workflows.create(owner, project.id, "Assemble payload", graph)

    assert saved.graph == graph

    unknown_source_field = WorkflowGraph(
        graph.nodes,
        (
            WorkflowEdge(
                None,
                None,
                "target",
                "payload",
                source_kind="workflowInput",
                source_input="request",
                source_path="/missing",
                target_path="/label",
            ),
            graph.edges[1],
        ),
        graph.outputs,
        graph.inputs,
    )
    with pytest.raises(WorkflowValidationError, match="unknown field"):
        await workflows.validate_graph(owner, project.id, unknown_source_field)

    overlapping = WorkflowGraph(
        graph.nodes,
        graph.edges
        + (
            WorkflowEdge(
                None,
                None,
                "target",
                "payload",
                source_kind="literal",
                literal="other label",
                target_path="/label",
            ),
        ),
        graph.outputs,
        graph.inputs,
    )
    with pytest.raises(WorkflowValidationError, match="conflicting bindings"):
        await workflows.validate_graph(owner, project.id, overlapping)


@pytest.mark.asyncio
async def test_project_workflow_route_saves_reads_and_rejects_stale_edits() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="owner")
    project = await projects.create(owner, "Analysis")
    datasets = DatasetModule(projects, MemoryDatasetStore())
    dataset = await datasets.create_dataset(
        owner, project.id, "Inputs", [DatasetRecordInput({"value": 2})]
    )
    workflows = WorkflowDefinitionModule(
        projects,
        datasets,
        FunctionModule(projects, MemoryFunctionStore()),
        None,
        MemoryWorkflowStore(),
    )
    app = FastAPI()
    app.include_router(
        create_workflow_router(
            create_identity_module(Settings(environment="test", fixed_identity_subject="owner")),
            workflows,
        ),
        prefix="/api",
    )
    body = {
        "name": "Inspection",
        "graph": {
            "nodes": [{"id": "source", "kind": "dataset", "refId": dataset.id, "version": 1}],
            "edges": [],
            "outputs": [{"name": "records", "node": "source", "port": "records"}],
        },
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        base = f"/api/projects/{project.id}/workflows"
        created = await client.post(base, json=body)
        assert created.status_code == 201
        workflow_id = created.json()["id"]
        assert (await client.get(base)).json()[0]["id"] == workflow_id
        assert (await client.get(f"{base}/{workflow_id}")).json()["graph"] == body["graph"]
        revised = await client.put(
            f"{base}/{workflow_id}", json={**body, "name": "Revised", "expectedVersion": 1}
        )
        assert revised.status_code == 200
        assert revised.json()["version"] == 2
        stale = await client.put(f"{base}/{workflow_id}", json={**body, "expectedVersion": 1})
        assert stale.status_code == 409


@pytest.mark.asyncio
async def test_workflow_wires_permitted_mcp_ports_and_rejects_incompatible_inputs() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="owner")
    project = await projects.create(owner, "Analysis")
    datasets = DatasetModule(projects, MemoryDatasetStore())
    dataset = await datasets.create_dataset(
        owner, project.id, "Inputs", [DatasetRecordInput({"value": 2})]
    )

    class Gateway:
        async def tool_version(self, *_: object) -> str:
            return "v1"

        async def input_schema(self, *_: object) -> dict[str, object]:
            return {
                "type": "object",
                "required": ["payload"],
                "properties": {"payload": {"type": "object"}},
            }

        async def output_schema(
            self, *_: object, require_repeat_safe: bool = False
        ) -> dict[str, object]:
            if require_repeat_safe:
                raise PluginToolNotAllowed
            return {"type": "object"}

    functions = FunctionModule(projects, MemoryFunctionStore())
    function = await functions.define(
        owner,
        project.id,
        "Collect",
        "def transform(inputs, parameters):\n    return {}\n",
        {"type": "object", "properties": {"items": {"type": "array"}}, "required": ["items"]},
        {"type": "object"},
    )
    workflows = WorkflowDefinitionModule(
        projects,
        datasets,
        functions,
        cast(PluginGatewayModule, Gateway()),
        MemoryWorkflowStore(),
    )
    source = WorkflowNode("source", "dataset", dataset.id, dataset.version)
    call = WorkflowNode("calculate", "mcp", "calculator", "v1", tool_name="evaluate")
    valid = await workflows.create(
        owner,
        project.id,
        "Calculation",
        WorkflowGraph(
            (source, WorkflowNode("collect", "python", function.id, function.revision), call),
            (
                WorkflowEdge("source", "records", "collect", "items"),
                WorkflowEdge("collect", "result", "calculate", "payload"),
            ),
            (WorkflowOutput("answer", "calculate", "result"),),
        ),
    )
    assert valid.graph.outputs[0].node == "calculate"
    with pytest.raises(WorkflowValidationError, match="incompatible"):
        await workflows.create(
            owner,
            project.id,
            "Wrong shape",
            WorkflowGraph(
                (source, call),
                (WorkflowEdge("source", "records", "calculate", "payload"),),
                (WorkflowOutput("answer", "calculate", "result"),),
            ),
        )
    with pytest.raises(WorkflowValidationError, match="unavailable"):
        await workflows.create(
            owner,
            project.id,
            "No repeat permission",
            WorkflowGraph(
                (
                    source,
                    WorkflowNode(
                        "calculate", "mcp", "calculator", "v1", shape="map", tool_name="evaluate"
                    ),
                ),
                (WorkflowEdge("source", "records", "calculate", "items"),),
                (WorkflowOutput("answer", "calculate", "result"),),
            ),
        )

    class RepeatGateway(Gateway):
        async def output_schema(
            self, *_: object, require_repeat_safe: bool = False
        ) -> dict[str, object]:
            return {"type": "object"}

    repeat_workflows = WorkflowDefinitionModule(
        projects,
        datasets,
        functions,
        cast(PluginGatewayModule, RepeatGateway()),
        MemoryWorkflowStore(),
    )
    with pytest.raises(WorkflowValidationError, match="cannot use map_input"):
        await repeat_workflows.create(
            owner,
            project.id,
            "Wrong map syntax",
            WorkflowGraph(
                (
                    source,
                    WorkflowNode(
                        "calculate",
                        "mcp",
                        "calculator",
                        "v1",
                        shape="map",
                        tool_name="evaluate",
                        map_input="payload",
                    ),
                ),
                (WorkflowEdge("source", "records", "calculate", "items"),),
                (WorkflowOutput("answer", "calculate", "result"),),
            ),
        )
    with pytest.raises(WorkflowValidationError, match="Record 1"):
        await repeat_workflows.create(
            owner,
            project.id,
            "Invalid arguments",
            WorkflowGraph(
                (
                    source,
                    WorkflowNode(
                        "calculate", "mcp", "calculator", "v1", shape="map", tool_name="evaluate"
                    ),
                ),
                (WorkflowEdge("source", "records", "calculate", "items"),),
                (WorkflowOutput("answer", "calculate", "result"),),
            ),
        )
