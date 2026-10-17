import json
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from deepagents.middleware._fs_interrupt import _build_interrupt_on_from_permissions
from langchain.agents.middleware import ModelRequest, ModelResponse
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage

import agent_hub_api.modules.agent_execution._deep_agent as deep_agent
from agent_hub_api.modules.agent_execution._deep_agent import (
    _AGENT_SYSTEM_PROMPT,
    PostgresDeepAgentRunner,
    _project_change_notice_middleware,
    _project_file_permissions,
)
from agent_hub_api.modules.datasets import (
    DatasetModule,
    DatasetRecordInput,
    MemoryDatasetStore,
)
from agent_hub_api.modules.functions import (
    FunctionModule,
    MemoryFunctionStore,
)
from agent_hub_api.modules.project_files import (
    ProjectFileAccess,
    create_memory_project_files,
)
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module
from agent_hub_api.modules.workflows import (
    MemoryWorkflowRunStore,
    MemoryWorkflowStore,
    WorkflowDefinitionModule,
    WorkflowRunModule,
)


def test_project_file_writes_interrupt_but_scratch_writes_do_not() -> None:
    interrupt_on = _build_interrupt_on_from_permissions(_project_file_permissions())
    write_when = interrupt_on["write_file"]["when"]
    edit_when = interrupt_on["edit_file"]["when"]

    assert write_when(
        cast(
            ToolCallRequest,
            SimpleNamespace(tool_call={"args": {"file_path": "/project/check.md"}}),
        )
    )
    assert edit_when(
        cast(
            ToolCallRequest,
            SimpleNamespace(tool_call={"args": {"file_path": "/project/check.md"}}),
        )
    )
    assert not write_when(
        cast(
            ToolCallRequest,
            SimpleNamespace(tool_call={"args": {"file_path": "/scratch/notes.md"}}),
        )
    )


def test_project_file_writes_start_before_the_approval_card_is_shown() -> None:
    assert "without asking for approval in chat" in _AGENT_SYSTEM_PROMPT
    assert "approval card is shown automatically" in _AGENT_SYSTEM_PROMPT


def test_agent_instructions_treat_datasets_as_registered_project_files() -> None:
    assert "Datasets are registered Project Files" in _AGENT_SYSTEM_PROMPT
    assert "Use Dataset tools for" in _AGENT_SYSTEM_PROMPT


def test_agent_instructions_describe_function_preview_and_workflow_execution() -> None:
    assert "Python Functions are authored as" in _AGENT_SYSTEM_PROMPT
    assert "transform(inputs, parameters)" in _AGENT_SYSTEM_PROMPT
    assert "input_schema_json" in _AGENT_SYSTEM_PROMPT
    assert "input_selectors" not in _AGENT_SYSTEM_PROMPT
    assert "preview" in _AGENT_SYSTEM_PROMPT
    assert "durable execution" in _AGENT_SYSTEM_PROMPT


def test_agent_instructions_document_the_workflow_graph_json_shape() -> None:
    assert "edges, outputs, and optional inputs arrays" in _AGENT_SYSTEM_PROMPT
    assert "target_node and target_port" in _AGENT_SYSTEM_PROMPT
    assert "source_kind='workflowInput'" in _AGENT_SYSTEM_PROMPT
    assert "RFC 6901 JSON Pointers" in _AGENT_SYSTEM_PROMPT
    assert "workflow_inputs_json" in _AGENT_SYSTEM_PROMPT
    assert "name, node, and port" in _AGENT_SYSTEM_PROMPT
    assert "Do not use a node map, from/to edge keys, or an outputs map" in _AGENT_SYSTEM_PROMPT
    assert "saved Function UUID as ref_id" in _AGENT_SYSTEM_PROMPT
    assert "Their input ports are declared input names" in _AGENT_SYSTEM_PROMPT
    assert "Never put a Function name in ref_id" in _AGENT_SYSTEM_PROMPT
    assert "call validate_project_workflow" in _AGENT_SYSTEM_PROMPT
    assert "discover_project_file_sources" in _AGENT_SYSTEM_PROMPT
    assert "does not unwrap object properties" in _AGENT_SYSTEM_PROMPT
    assert "Workflow output schema properties are inside the result value" in _AGENT_SYSTEM_PROMPT
    assert "A single Function may accept a named array input" in _AGENT_SYSTEM_PROMPT
    assert "Never map a collection filter" in _AGENT_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_agent_workflow_edits_are_approval_gated_and_readable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="sam")
    project = await projects.create(owner, "Workflow tools")

    class Schemas:
        async def input_schema(self, *_: object) -> dict[str, object]:
            return {"type": "object"}

    datasets = DatasetModule(projects, MemoryDatasetStore())
    files = create_memory_project_files(projects)
    file = await files.create_visible(
        ProjectFileAccess(subject="sam"), project.id, "/demo.txt", "sample"
    )
    dataset = await datasets.create_dataset(
        owner, project.id, "Inputs", [DatasetRecordInput({"value": 2})]
    )
    functions = FunctionModule(projects, MemoryFunctionStore())
    workflows = WorkflowDefinitionModule(
        projects,
        datasets,
        functions,
        None,
        MemoryWorkflowStore(),
        project_files=files,
    )
    workflow_runs = WorkflowRunModule(
        workflows, datasets, functions, None, MemoryWorkflowRunStore()
    )
    runner = object.__new__(PostgresDeepAgentRunner)
    runner._checkpointer = cast(Any, object())
    runner._model = cast(Any, object())
    runner._project_files = files
    runner._plugin_gateway = None
    runner._functions = functions
    runner._workflows = workflows
    runner._workflow_runs = workflow_runs
    runner._settings = cast(
        Any, SimpleNamespace(agent_recursion_limit=10, enable_foundation_test_tool=False)
    )
    captured: dict[str, Any] = {}

    def create_agent(**kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(nodes={})

    monkeypatch.setattr(deep_agent, "create_deep_agent", create_agent)
    await runner._agent_for(project.id, subject="sam")
    assert captured["interrupt_on"]["create_project_workflow"]["allowed_decisions"] == [
        "approve",
        "reject",
    ]
    assert captured["interrupt_on"]["revise_project_workflow"]["allowed_decisions"] == [
        "approve",
        "reject",
    ]
    assert captured["interrupt_on"]["prepare_project_workflow_run"]["allowed_decisions"] == [
        "approve",
        "reject",
    ]
    assert captured["interrupt_on"]["execute_project_workflow_run"]["allowed_decisions"] == [
        "approve",
        "reject",
    ]
    assert (
        captured["interrupt_on"]["create_project_function"]["description"]
        == "Create the proposed Python Function?"
    )
    tools = {registered.name: registered for registered in captured["tools"]}
    file_sources = json.loads(await tools["discover_project_file_sources"].ainvoke({}))
    assert file_sources == [{"path": "/project/demo.txt", "version": file.version}]
    graph_json = json.dumps(
        {
            "nodes": [{"id": "source", "kind": "dataset", "ref_id": dataset.id, "version": 1}],
            "edges": [],
            "outputs": [{"name": "records", "node": "source", "port": "records"}],
        }
    )
    preflight = await tools["validate_project_workflow"].ainvoke(
        {"graph_json": json.loads(graph_json)}
    )
    assert "structurally valid" in preflight
    assert "Python code was not run" in preflight
    assert "has not been saved" in preflight
    function = await functions.define(
        owner,
        project.id,
        "normalize_text",
        "def transform(inputs, parameters):\n    return {'result': inputs['text'].strip()}\n",
        {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        {"type": "object", "properties": {"result": {"type": "string"}}},
    )
    saved_functions = json.loads(await tools["discover_project_functions"].ainvoke({}))
    assert saved_functions == [
        {"id": function.id, "name": "normalize_text", "revision": function.revision}
    ]
    function_graph = json.dumps(
        {
            "nodes": [
                {
                    "id": "source",
                    "kind": "file",
                    "ref_id": f"/project{file.path}",
                    "version": file.version,
                },
                {
                    "id": "normalize",
                    "kind": "python",
                    "ref_id": function.id,
                    "version": function.revision,
                },
            ],
            "edges": [
                {
                    "source_node": "source",
                    "source_port": "content",
                    "target_node": "normalize",
                    "target_port": "text",
                }
            ],
            "outputs": [{"name": "normalized", "node": "normalize", "port": "result"}],
        }
    )
    function_preflight = await tools["validate_project_workflow"].ainvoke(
        {"graph_json": json.loads(function_graph)}
    )
    assert "structurally valid" in function_preflight
    input_workflow_graph = json.dumps(
        {
            "nodes": [
                {
                    "id": "normalize",
                    "kind": "python",
                    "ref_id": function.id,
                    "version": function.revision,
                }
            ],
            "edges": [
                {
                    "source_kind": "workflowInput",
                    "source_input": "request",
                    "target_node": "normalize",
                    "target_port": "text",
                }
            ],
            "inputs": [{"name": "request", "schema": {"type": "string"}, "required": True}],
            "outputs": [{"name": "normalized", "node": "normalize", "port": "result"}],
        }
    )
    input_workflow = json.loads(
        await tools["create_project_workflow"].ainvoke(
            {"name": "Normalize input", "graph_json": json.loads(input_workflow_graph)}
        )
    )
    input_run = json.loads(
        await tools["prepare_project_workflow_run"].ainvoke(
            {
                "workflow_id": input_workflow["id"],
                "expected_version": 1,
                "idempotency_key": "runtime-input-run",
                "workflow_inputs_json": '{"request":"  sample  "}',
            }
        )
    )
    input_run_snapshot = json.loads(
        await tools["load_project_workflow_run"].ainvoke({"run_id": input_run["id"]})
    )["snapshot"]
    assert input_run_snapshot["workflowInputs"] == {"request": "  sample  "}
    bad_function_graph = function_graph.replace(function.id, "normalize_text")
    function_error = await tools["validate_project_workflow"].ainvoke(
        {"graph_json": json.loads(bad_function_graph)}
    )
    assert "use the ID returned by discover_project_functions" in function_error
    invalid = await tools["create_project_workflow"].ainvoke(
        {
            "name": "Invalid demo",
            "graph_json": {
                "nodes": {"input": {"type": "input"}},
                "edges": [],
                "outputs": {"result": "input"},
            },
        }
    )
    assert "Workflow graph is invalid" in invalid

    created = json.loads(
        await tools["create_project_workflow"].ainvoke(
            {
                "name": "Inspect",
                "graph_json": json.loads(graph_json),
            }
        )
    )
    assert created["version"] == 1
    invalid_revision = await tools["revise_project_workflow"].ainvoke(
        {
            "workflow_id": created["id"],
            "name": "Invalid revision",
            "expected_version": 1,
            "graph_json": {
                "nodes": {"input": {"type": "input"}},
                "edges": [],
                "outputs": {"result": "input"},
            },
        }
    )
    assert "Workflow graph is invalid" in invalid_revision

    loaded = json.loads(
        await tools["load_project_workflow"].ainvoke(
            {
                "workflow_id": created["id"],
            }
        )
    )
    assert loaded["graph"]["outputs"][0]["name"] == "records"
    prepared = json.loads(
        await tools["prepare_project_workflow_run"].ainvoke(
            {
                "workflow_id": created["id"],
                "expected_version": 1,
                "idempotency_key": "agent-request-1",
            }
        )
    )
    assert prepared["status"] == "prepared"
    inspected = json.loads(
        await tools["load_project_workflow_run"].ainvoke({"run_id": prepared["id"]})
    )
    assert inspected["snapshot"]["sources"]["source"]["records"][0]["value"] == {"value": 2}


@pytest.mark.asyncio
async def test_project_change_notice_is_transient_and_identifies_its_origin() -> None:
    original: list[AnyMessage] = [HumanMessage(content="Please review the project.")]
    request = ModelRequest(model=cast(Any, object()), messages=original)
    received: list[AnyMessage] = []

    async def handler(overridden: ModelRequest) -> ModelResponse:
        received.extend(overridden.messages)
        return ModelResponse(result=[AIMessage(content="I will review it.")])

    response = await _project_change_notice_middleware(
        "Bridge design (artifact-1, v2)"
    ).awrap_model_call(request, handler)

    assert isinstance(response, ModelResponse)
    assert response.result == [AIMessage(content="I will review it.")]
    assert request.messages == original
    assert received[-1] == HumanMessage(
        content="[System Notification]: Bridge design (artifact-1, v2)"
    )


@pytest.mark.asyncio
async def test_agent_uses_structured_interrupt_outcomes_without_legacy_custom_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = object.__new__(PostgresDeepAgentRunner)
    runner._checkpointer = cast(Any, object())
    runner._model = cast(Any, object())
    runner._project_files = cast(Any, object())
    runner._plugin_gateway = None
    runner._settings = cast(
        Any,
        SimpleNamespace(
            agent_recursion_limit=10,
            enable_foundation_test_tool=False,
        ),
    )

    monkeypatch.setattr(
        deep_agent,
        "create_deep_agent",
        lambda **_kwargs: SimpleNamespace(nodes={}),
    )

    agent = await runner._agent_for("project-1")

    assert agent.emit_interrupt_outcome is True
    assert agent.enable_legacy_on_interrupt_event is False
    assert agent.clone().enable_legacy_on_interrupt_event is False


@pytest.mark.asyncio
async def test_agent_can_discover_and_load_project_artifacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ArtifactContext:
        async def discover(self, *_: object) -> tuple[object, ...]:
            return ()

    runner = object.__new__(PostgresDeepAgentRunner)
    runner._checkpointer = cast(Any, object())
    runner._model = cast(Any, object())
    runner._project_files = cast(Any, object())
    runner._plugin_gateway = None
    runner._artifacts = cast(Any, ArtifactContext())
    runner._settings = cast(
        Any,
        SimpleNamespace(agent_recursion_limit=10, enable_foundation_test_tool=False),
    )
    captured: dict[str, Any] = {}

    def create_agent(**kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(nodes={})

    monkeypatch.setattr(deep_agent, "create_deep_agent", create_agent)

    await runner._agent_for("project-1", thread_id="thread-1", run_id="run-1", subject="sam")

    names = {registered.name for registered in captured["tools"]}
    assert {"discover_project_artifacts", "load_project_artifact"} <= names
    assert "create_foundation_status_artifact" not in names
    assert "set_foundation_status_artifact_status" not in names


@pytest.mark.asyncio
async def test_agent_exposes_authoring_and_workflow_tools_without_standalone_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = object.__new__(PostgresDeepAgentRunner)
    runner._checkpointer = cast(Any, object())
    runner._model = cast(Any, object())
    runner._project_files = cast(Any, object())
    runner._plugin_gateway = None
    runner._datasets = cast(Any, object())
    runner._functions = cast(Any, object())
    runner._workflows = cast(Any, object())
    runner._workflow_runs = cast(Any, object())
    runner._settings = cast(
        Any,
        SimpleNamespace(agent_recursion_limit=10, enable_foundation_test_tool=False),
    )
    captured: dict[str, Any] = {}

    def create_agent(**kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(nodes={})

    monkeypatch.setattr(deep_agent, "create_deep_agent", create_agent)

    await runner._agent_for("project-1", thread_id="thread-1", run_id="agent-run-1", subject="sam")

    names = {registered.name for registered in captured["tools"]}
    assert {"discover_project_datasets", "load_project_dataset"} <= names
    assert "create_project_dataset" in captured["interrupt_on"]
    assert "create_project_batch_definition" not in names
    assert {
        "discover_project_functions",
        "load_project_function",
        "preview_project_function",
    } <= names
    assert "create_project_function" in captured["interrupt_on"]
    assert "update_project_function" in captured["interrupt_on"]
    assert "delete_project_function" in captured["interrupt_on"]
    assert {"list_project_workflows", "validate_project_workflow"} <= names
    assert {"prepare_project_workflow_run", "execute_project_workflow_run"} <= names
    assert not any(
        "batch_run" in name
        or "batch_map" in name
        or "transform_run" in name
        or "function_call" in name
        or "selection_run" in name
        for name in names
    )
    assert not any(
        "batch_run" in name
        or "batch_map" in name
        or "transform_run" in name
        or "function_call" in name
        or "selection_run" in name
        for name in captured["interrupt_on"]
    )


@pytest.mark.asyncio
async def test_invalid_approved_function_proposal_returns_actionable_tool_error() -> None:
    projects = create_memory_project_module()
    access = ProjectAccess(subject="sam")
    project = await projects.create(access, "Function proposal")
    functions = FunctionModule(projects, MemoryFunctionStore())
    tools = {
        item.name: item
        for item in PostgresDeepAgentRunner._function_tools(functions, project.id, access.subject)
    }
    input_schema_json = json.dumps(
        {
            "type": "object",
            "properties": {"record": {"type": "object"}},
            "required": ["record"],
            "additionalProperties": False,
        }
    )

    invalid_source = await tools["create_project_function"].ainvoke(
        {
            "name": "Copy dataset records",
            "source": "export default function transform(record, parameters) { return record; }",
            "input_schema_json": input_schema_json,
            "output_schema_json": '{"type":"object"}',
        }
    )
    assert "Function source is not valid Python" in invalid_source

    invalid_source = await tools["create_project_function"].ainvoke(
        {
            "name": "Copy dataset records",
            "source": "export default function transform(record, parameters) { return record; }",
            "input_schema_json": input_schema_json,
            "output_schema_json": '{"type":"object"}',
        }
    )
    assert "Function source is not valid Python" in invalid_source
    assert await functions.list(access, project.id) == ()

    created = await tools["create_project_function"].ainvoke(
        {
            "name": "Copy dataset records",
            "source": "def transform(inputs, parameters):\n    return dict(inputs['record'])\n",
            "input_schema_json": input_schema_json,
            "output_schema_json": '{"type":"object"}',
        }
    )
    created_function = json.loads(created)
    assert created_function["created"] == "python_function"
    definition = (await functions.list(access, project.id))[0]
    assert created_function["id"] == definition.id
    assert created_function["revision"] == definition.revision
    invalid_revision = await tools["update_project_function"].ainvoke(
        {
            "function_id": definition.id,
            "name": "Copy dataset records",
            "source": "export default function transform(record) { return record; }",
            "input_schema_json": input_schema_json,
            "output_schema_json": '{"type":"object"}',
        }
    )
    assert "Function source is not valid Python" in invalid_revision
    assert (await functions.load(access, project.id, definition.id)).revision == 1


@pytest.mark.asyncio
async def test_unavailable_function_preview_returns_actionable_tool_error() -> None:
    projects = create_memory_project_module()
    access = ProjectAccess(subject="sam")
    project = await projects.create(access, "Function preview")
    functions = FunctionModule(projects, MemoryFunctionStore())
    definition = await functions.define(
        access,
        project.id,
        "Copy",
        "def transform(inputs, parameters):\n    return inputs\n",
        {"type": "object", "properties": {"value": {}}, "required": ["value"]},
        {"type": "object"},
    )
    tools = {
        item.name: item
        for item in PostgresDeepAgentRunner._function_tools(functions, project.id, access.subject)
    }

    result = await tools["preview_project_function"].ainvoke(
        {"function_id": definition.id, "inputs_json": '{"value":1}'}
    )

    assert "Function preview failed" in result
    assert "runner_unavailable" in result


@pytest.mark.asyncio
async def test_scratch_preview_reads_the_state_backend_route_relative_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CompositeBackend removes ``/scratch/`` before StateBackend persists a file."""
    runner = object.__new__(PostgresDeepAgentRunner)
    agent = SimpleNamespace(
        graph=SimpleNamespace(
            aget_state=AsyncMock(
                return_value=SimpleNamespace(
                    values={"files": {"/dummy.md": {"content": "# Dummy\n"}}}
                )
            )
        )
    )

    async def open_runner() -> None:
        return None

    monkeypatch.setattr(runner, "open", open_runner)
    monkeypatch.setattr(runner, "_agent_for", AsyncMock(return_value=agent))

    file = await runner.load_scratch_file(
        "thread-1", project_id="project-1", path="/scratch/dummy.md"
    )

    assert file.path == "/scratch/dummy.md"
    assert file.content == "# Dummy\n"
