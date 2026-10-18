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
    assert "array of the original row values" in _AGENT_SYSTEM_PROMPT
    assert "does not include the id/sourceKey/value wrappers" in _AGENT_SYSTEM_PROMPT
    assert "Function input schema that matches those row values" in _AGENT_SYSTEM_PROMPT


def test_agent_instructions_describe_function_preview_and_workflow_execution() -> None:
    assert "Python Functions are authored as" in _AGENT_SYSTEM_PROMPT
    assert "transform(inputs, parameters)" in _AGENT_SYSTEM_PROMPT
    assert "input_schema and output_schema as JSON Schema objects" in _AGENT_SYSTEM_PROMPT
    assert "input_selectors" not in _AGENT_SYSTEM_PROMPT
    assert "preview" in _AGENT_SYSTEM_PROMPT
    assert "durable execution" in _AGENT_SYSTEM_PROMPT


def test_agent_instructions_document_the_workflow_graph_json_shape() -> None:
    assert "edges, outputs, and optional inputs" in _AGENT_SYSTEM_PROMPT
    assert "target_node and target_port" in _AGENT_SYSTEM_PROMPT
    assert "source_kind='workflowInput'" in _AGENT_SYSTEM_PROMPT
    assert "RFC 6901 JSON Pointers" in _AGENT_SYSTEM_PROMPT
    assert "workflow_inputs" in _AGENT_SYSTEM_PROMPT
    assert "name, node, and port" in _AGENT_SYSTEM_PROMPT
    assert "Do not use a node map, from/to edge keys, or an outputs map" in _AGENT_SYSTEM_PROMPT
    assert "saved Function UUID as ref_id" in _AGENT_SYSTEM_PROMPT
    assert "target_port names a Function input" in _AGENT_SYSTEM_PROMPT
    assert "never put a Function name in ref_id" in _AGENT_SYSTEM_PROMPT
    assert "Create or revise a Workflow directly" in _AGENT_SYSTEM_PROMPT
    assert "those authoring tools validate automatically" in _AGENT_SYSTEM_PROMPT
    assert "discover_project_file_sources" in _AGENT_SYSTEM_PROMPT
    assert "Workflow output schema properties are inside the result value" in _AGENT_SYSTEM_PROMPT
    assert "when its Function accepts a collection" in _AGENT_SYSTEM_PROMPT
    assert "Never map a collection filter" in _AGENT_SYSTEM_PROMPT
    assert "Workflow IDs and Workflow Run IDs are different" in _AGENT_SYSTEM_PROMPT
    assert "treat it as a recoverable tool result" in _AGENT_SYSTEM_PROMPT


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
    runner._datasets = datasets
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
    discovered_datasets = json.loads(await tools["discover_project_datasets"].ainvoke({}))
    assert discovered_datasets == [
        {
            "id": dataset.id,
            "name": "Inputs",
            "recordCount": 1,
            "version": 1,
            "sampleRecords": [{"value": 2}],
        }
    ]
    image_error = await tools["view_image"].ainvoke(
        {"run_id": "missing-run", "output_name": "chart"}
    )
    image_error_payload = json.loads(image_error[0]["text"])
    assert image_error_payload["error"]["code"] == "workflow_run_not_found"
    assert "Use the Run ID" in image_error_payload["nextStep"]
    file_sources = json.loads(await tools["discover_project_file_sources"].ainvoke({}))
    assert file_sources == [{"path": "/project/demo.txt", "version": file.version}]
    graph_json = json.dumps(
        {
            "nodes": [{"id": "source", "kind": "dataset", "ref_id": dataset.id, "version": 1}],
            "edges": [],
            "outputs": [{"name": "records", "node": "source", "port": "records"}],
        }
    )
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
        {
            "id": function.id,
            "name": "normalize_text",
            "revision": function.revision,
            "inputSchema": function.input_schema,
            "outputSchema": function.output_schema,
        }
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
                "workflow_id": input_workflow["workflowId"],
                "expected_version": 1,
                "idempotency_key": "runtime-input-run",
                "workflow_inputs": {"request": "  sample  "},
            }
        )
    )
    input_run_snapshot = json.loads(
        await tools["load_project_workflow_run"].ainvoke({"run_id": input_run["runId"]})
    )["snapshot"]
    assert input_run_snapshot["workflowInputs"] == {"request": "  sample  "}
    bad_function_graph = function_graph.replace(function.id, "normalize_text")
    function_error = await tools["create_project_workflow"].ainvoke(
        {"name": "Invalid Function reference", "graph_json": json.loads(bad_function_graph)}
    )
    assert json.loads(function_error) == {
        "ok": False,
        "error": {
            "code": "workflow_validation",
            "message": (
                "Python Function ID 'normalize_text' is unavailable; use the ID returned by "
                "discover_project_functions, not the Function name."
            ),
        },
        "nextStep": (
            "Correct graph_json using the named node, reference, schema, or binding, then "
            "retry once."
        ),
    }
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
    assert json.loads(invalid)["error"]["code"] == "workflow_validation"
    assert "Correct graph_json" in json.loads(invalid)["nextStep"]

    created = json.loads(
        await tools["create_project_workflow"].ainvoke(
            {
                "name": "Inspect",
                "graph_json": json.loads(graph_json),
            }
        )
    )
    assert created["version"] == 1
    workflow_listing = json.loads(await tools["list_project_workflows"].ainvoke({}))
    assert any(item["workflowId"] == created["workflowId"] for item in workflow_listing)
    invalid_revision = await tools["revise_project_workflow"].ainvoke(
        {
            "workflow_id": created["workflowId"],
            "name": "Invalid revision",
            "expected_version": 1,
            "graph_json": {
                "nodes": {"input": {"type": "input"}},
                "edges": [],
                "outputs": {"result": "input"},
            },
        }
    )
    assert json.loads(invalid_revision)["error"]["code"] == "workflow_validation"
    missing_revision = json.loads(
        await tools["revise_project_workflow"].ainvoke(
            {
                "workflow_id": "missing-workflow",
                "name": "Missing workflow",
                "expected_version": 1,
                "graph_json": json.loads(graph_json),
            }
        )
    )
    assert missing_revision["error"]["code"] == "workflow_not_found"

    loaded = json.loads(
        await tools["load_project_workflow"].ainvoke(
            {
                "workflow_id": created["workflowId"],
            }
        )
    )
    assert loaded["workflowId"] == created["workflowId"]
    assert loaded["graph"]["outputs"][0]["name"] == "records"
    missing_workflow = json.loads(
        await tools["load_project_workflow"].ainvoke({"workflow_id": "missing-workflow"})
    )
    assert missing_workflow["error"]["code"] == "workflow_not_found"
    assert "list_project_workflows" in missing_workflow["nextStep"]
    missing_prepare = json.loads(
        await tools["prepare_project_workflow_run"].ainvoke(
            {
                "workflow_id": "missing-workflow",
                "expected_version": 1,
                "idempotency_key": "missing-workflow-run",
            }
        )
    )
    assert missing_prepare["error"]["code"] == "workflow_not_found"

    prepared = json.loads(
        await tools["prepare_project_workflow_run"].ainvoke(
            {
                "workflow_id": created["workflowId"],
                "expected_version": 1,
                "idempotency_key": "agent-request-1",
            }
        )
    )
    assert prepared["status"] == "prepared"
    assert prepared["workflowId"] == created["workflowId"]
    inspected = json.loads(
        await tools["load_project_workflow_run"].ainvoke({"run_id": prepared["runId"]})
    )
    assert inspected["runId"] == prepared["runId"]
    assert inspected["workflowId"] == created["workflowId"]
    assert inspected["snapshot"]["sources"]["source"]["records"][0]["value"] == {"value": 2}

    wrong_resource_id = await tools["load_project_workflow_run"].ainvoke(
        {"run_id": created["workflowId"]}
    )
    assert json.loads(wrong_resource_id) == {
        "ok": False,
        "error": {
            "code": "workflow_run_not_found",
            "message": (
                f"Workflow Run '{created['workflowId']}' is unavailable in this Project. "
                "This may be a Workflow ID rather than a Run ID."
            ),
        },
        "nextStep": (
            "Use the Run ID returned by prepare_project_workflow_run or "
            "execute_project_workflow_run. If you meant a saved Workflow, call "
            "list_project_workflows and use its ID with load_project_workflow; prepare a new "
            "Run if no Run ID is available."
        ),
    }
    missing_run = json.loads(
        await tools["execute_project_workflow_run"].ainvoke({"run_id": "missing-run"})
    )
    assert missing_run["error"]["code"] == "workflow_run_not_found"
    assert "prepare a fresh Run" in missing_run["nextStep"]


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
    assert "list_project_workflows" in names
    assert "validate_project_workflow" not in names
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
    input_schema = {
        "type": "object",
        "properties": {"record": {"type": "object"}},
        "required": ["record"],
        "additionalProperties": False,
    }

    invalid_source = await tools["create_project_function"].ainvoke(
        {
            "name": "Copy dataset records",
            "source": "export default function transform(record, parameters) { return record; }",
            "input_schema": input_schema,
            "output_schema": {"type": "object"},
        }
    )
    assert json.loads(invalid_source)["error"]["code"] == "function_validation"
    assert "Function source is not valid Python" in json.loads(invalid_source)["error"]["message"]

    invalid_source = await tools["create_project_function"].ainvoke(
        {
            "name": "Copy dataset records",
            "source": "export default function transform(record, parameters) { return record; }",
            "input_schema": input_schema,
            "output_schema": {"type": "object"},
        }
    )
    assert json.loads(invalid_source)["error"]["code"] == "function_validation"
    assert await functions.list(access, project.id) == ()

    created = await tools["create_project_function"].ainvoke(
        {
            "name": "Copy dataset records",
            "source": "def transform(inputs, parameters):\n    return dict(inputs['record'])\n",
            "input_schema": input_schema,
            "output_schema": {"type": "object"},
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
            "input_schema": input_schema,
            "output_schema": {"type": "object"},
        }
    )
    assert json.loads(invalid_revision)["error"]["code"] == "function_validation"
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
        {"function_id": definition.id, "inputs": {"value": 1}}
    )

    preview_error = json.loads(result)
    assert preview_error["error"]["code"] == "function_preview_failed"
    assert "runner_unavailable" in preview_error["error"]["message"]
    assert "fix the Function source or input shape" in preview_error["nextStep"]


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
