import asyncio
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
from agent_hub_api.modules.artifacts import ArtifactMutationAccess
from agent_hub_api.modules.batch_execution import BatchInitiation, BatchRunStatus
from agent_hub_api.modules.datasets import (
    DatasetModule,
    DatasetRecordInput,
    MemoryDatasetStore,
)
from agent_hub_api.modules.project_files import (
    ProjectFileAccess,
    create_memory_project_files,
)
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module
from agent_hub_api.modules.transform_inputs import ArtifactSelection, ResultSetSelection
from agent_hub_api.modules.transforms import (
    MemoryTransformStore,
    OutputSelection,
    TransformInitiation,
    TransformModule,
)
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
    assert (
        "Start the Project file write without asking for approval in chat first."
        in _AGENT_SYSTEM_PROMPT
    )
    assert "The approval card is shown automatically after the tool call." in _AGENT_SYSTEM_PROMPT


def test_agent_instructions_treat_datasets_as_registered_project_files() -> None:
    assert "Datasets are registered, typed Project Files" in _AGENT_SYSTEM_PROMPT
    assert "Use the Project Dataset tools for Dataset mutations" in _AGENT_SYSTEM_PROMPT


def test_agent_instructions_describe_transform_language_and_selectors() -> None:
    assert "Transform source is Python" in _AGENT_SYSTEM_PROMPT
    assert "transform(inputs, parameters)" in _AGENT_SYSTEM_PROMPT
    assert '{"record":""}' in _AGENT_SYSTEM_PROMPT
    assert "null output during that state" in _AGENT_SYSTEM_PROMPT


def test_agent_instructions_document_the_workflow_graph_json_shape() -> None:
    assert "nodes, edges, and outputs arrays" in _AGENT_SYSTEM_PROMPT
    assert "source_node, source_port, target_node, and target_port" in _AGENT_SYSTEM_PROMPT
    assert "name, node, and port" in _AGENT_SYSTEM_PROMPT
    assert "Do not use a node map, from/to edge keys, or an outputs map" in _AGENT_SYSTEM_PROMPT
    assert "saved Function ID as ref_id" in _AGENT_SYSTEM_PROMPT
    assert "Function's declared input names" in _AGENT_SYSTEM_PROMPT
    assert "same saved object, not separate entities" in _AGENT_SYSTEM_PROMPT
    assert "Never put a Function name in ref_id" in _AGENT_SYSTEM_PROMPT
    assert "call validate_project_workflow" in _AGENT_SYSTEM_PROMPT
    assert "discover_project_file_sources" in _AGENT_SYSTEM_PROMPT
    assert "passes the entire value matching" in _AGENT_SYSTEM_PROMPT
    assert "Workflow input selectors are not applied" in _AGENT_SYSTEM_PROMPT
    assert "Workflow output schema properties are inside the result value" in _AGENT_SYSTEM_PROMPT


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

    datasets = DatasetModule(projects, MemoryDatasetStore(), Schemas())
    files = create_memory_project_files(projects)
    file = await files.create_visible(
        ProjectFileAccess(subject="sam"), project.id, "/demo.txt", "sample"
    )
    dataset = await datasets.create_dataset(
        owner, project.id, "Inputs", [DatasetRecordInput({"value": 2})]
    )
    transforms = TransformModule(projects, MemoryTransformStore())
    workflows = WorkflowDefinitionModule(
        projects,
        datasets,
        transforms,
        None,
        MemoryWorkflowStore(),
        project_files=files,
    )
    workflow_runs = WorkflowRunModule(
        workflows, datasets, transforms, None, MemoryWorkflowRunStore()
    )
    runner = object.__new__(PostgresDeepAgentRunner)
    runner._checkpointer = cast(Any, object())
    runner._model = cast(Any, object())
    runner._project_files = files
    runner._plugin_gateway = None
    runner._transforms = transforms
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
        captured["interrupt_on"]["create_project_transform"]["description"]
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
    preflight = await tools["validate_project_workflow"].ainvoke({"graph_json": graph_json})
    assert "structurally valid" in preflight
    assert "Python code was not run" in preflight
    assert "has not been saved" in preflight
    function = await transforms.define(
        owner,
        project.id,
        "normalize_text",
        "def transform(inputs, parameters):\n    return {'result': inputs['text'].strip()}\n",
        {"text": ""},
        {"type": "object", "properties": {"result": {"type": "string"}}},
    )
    saved_functions = json.loads(await tools["discover_project_transforms"].ainvoke({}))
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
        {"graph_json": function_graph}
    )
    assert "structurally valid" in function_preflight
    bad_function_graph = function_graph.replace(function.id, "normalize_text")
    function_error = await tools["validate_project_workflow"].ainvoke(
        {"graph_json": bad_function_graph}
    )
    assert "use the ID returned by discover_project_transforms" in function_error
    invalid = await tools["create_project_workflow"].ainvoke(
        {
            "name": "Invalid demo",
            "graph_json": json.dumps(
                {
                    "nodes": {"input": {"type": "input"}},
                    "edges": [],
                    "outputs": {"result": "input"},
                }
            ),
        }
    )
    assert "Workflow graph is invalid" in invalid

    created = json.loads(
        await tools["create_project_workflow"].ainvoke(
            {
                "name": "Inspect",
                "graph_json": graph_json,
            }
        )
    )
    assert created["version"] == 1
    invalid_revision = await tools["revise_project_workflow"].ainvoke(
        {
            "workflow_id": created["id"],
            "name": "Invalid revision",
            "expected_version": 1,
            "graph_json": json.dumps(
                {
                    "nodes": {"input": {"type": "input"}},
                    "edges": [],
                    "outputs": {"result": "input"},
                }
            ),
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
async def test_agent_exposes_dataset_tools_and_interrupts_mutations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = object.__new__(PostgresDeepAgentRunner)
    runner._checkpointer = cast(Any, object())
    runner._model = cast(Any, object())
    runner._project_files = cast(Any, object())
    runner._plugin_gateway = None
    runner._datasets = cast(Any, object())
    runner._batches = cast(Any, object())
    runner._transforms = cast(Any, object())
    runner._transform_inputs = cast(Any, object())
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
    assert "create_project_batch_definition" in captured["interrupt_on"]
    assert "start_project_batch_run" in captured["interrupt_on"]
    assert "start_project_batch_run" in names
    assert "plan_project_mcp_map" in names
    assert "plan_project_mcp_map" not in captured["interrupt_on"]
    assert "start_project_mcp_map" in names
    assert "start_project_mcp_map" in captured["interrupt_on"]
    assert "plan_project_mcp_call" in names
    assert "plan_project_mcp_call" not in captured["interrupt_on"]
    assert "start_project_mcp_call" in captured["interrupt_on"]
    assert "plan_project_python_map" in names
    assert "plan_project_python_map" not in captured["interrupt_on"]
    assert "start_project_python_map" in captured["interrupt_on"]
    assert {"list_project_batch_runs", "inspect_project_batch_results"} <= names
    assert "inspect_project_batch_results" not in captured["interrupt_on"]
    assert {"discover_project_transforms", "load_project_transform"} <= names
    assert "create_project_transform" in captured["interrupt_on"]
    assert "update_project_transform" in captured["interrupt_on"]
    assert "delete_project_transform" in captured["interrupt_on"]
    assert "start_project_transform_run" in captured["interrupt_on"]
    assert "start_project_dataset_transform_run" in captured["interrupt_on"]
    assert "start_project_transform_output_selection_run" in captured["interrupt_on"]
    assert "start_project_transform_result_set_selection_run" in captured["interrupt_on"]
    assert "start_project_transform_artifact_selection_run" in captured["interrupt_on"]
    assert "plan_project_dataset_transform_run" in names
    assert "plan_project_transform_selection" not in names
    assert "create_project_transform_batch_definition" not in names
    assert "plan_project_transform_output_selection" in names
    assert "plan_project_transform_result_set_selection" in names
    assert "plan_project_transform_artifact_selection" in names
    assert "plan_project_dataset_transform_run" not in captured["interrupt_on"]
    assert "plan_project_transform_output_selection" not in captured["interrupt_on"]
    assert "plan_project_transform_result_set_selection" not in captured["interrupt_on"]
    assert "plan_project_transform_artifact_selection" not in captured["interrupt_on"]
    assert "save_project_transform_run_as_dataset" in captured["interrupt_on"]


@pytest.mark.asyncio
async def test_agent_loads_a_batch_definition_on_demand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ToolSchemas:
        async def input_schema(self, *_: object) -> dict[str, object]:
            return {
                "type": "object",
                "required": ["length_m"],
                "properties": {"length_m": {"type": "number"}},
            }

    projects = create_memory_project_module()
    access = ProjectAccess(subject="sam")
    project = await projects.create(access, "Bridge")
    datasets = DatasetModule(projects, MemoryDatasetStore(), ToolSchemas())
    dataset = await datasets.create_dataset(
        access, project.id, "Load cases", [DatasetRecordInput({"length": 2.5})]
    )
    definition = await datasets.create_definition(
        access,
        project.id,
        dataset.id,
        "Beam checks",
        "reference-calculation",
        "calculate_beam",
        {"length_m": "/length"},
    )
    runner = object.__new__(PostgresDeepAgentRunner)
    runner._checkpointer = cast(Any, object())
    runner._model = cast(Any, object())
    runner._project_files = cast(Any, object())
    runner._plugin_gateway = None
    runner._datasets = datasets
    runner._settings = cast(
        Any,
        SimpleNamespace(agent_recursion_limit=10, enable_foundation_test_tool=False),
    )
    captured: dict[str, Any] = {}

    def create_agent(**kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(nodes={})

    monkeypatch.setattr(deep_agent, "create_deep_agent", create_agent)

    await runner._agent_for(project.id, subject=access.subject)

    tools = {registered.name: registered for registered in captured["tools"]}
    result = await tools["load_project_batch_definition"].ainvoke({"definition_id": definition.id})

    assert json.loads(result) == {
        "id": definition.id,
        "name": "Beam checks",
        "datasetId": dataset.id,
        "pluginId": "reference-calculation",
        "toolName": "calculate_beam",
        "transformDefinitionId": None,
        "argumentMappings": {"length_m": "/length"},
    }


@pytest.mark.asyncio
async def test_agent_batch_tool_submits_and_queues_a_host_batch_run() -> None:
    class Batches:
        def __init__(self) -> None:
            self.submissions: list[tuple[str, str, str, BatchInitiation]] = []
            self.enqueued_run_id: str | None = None

        async def submit_all(
            self,
            _access: object,
            project_id: str,
            definition_id: str,
            idempotency_key: str,
            *,
            initiation: BatchInitiation,
        ) -> object:
            self.submissions.append((project_id, definition_id, idempotency_key, initiation))
            return SimpleNamespace(id="run-1")

        async def enqueue(
            self, _access: object, _project_id: str, run_id: str
        ) -> asyncio.Task[object]:
            self.enqueued_run_id = run_id

            async def complete() -> object:
                return SimpleNamespace(
                    id=run_id,
                    status=BatchRunStatus.succeeded,
                    records=(SimpleNamespace(structured_output={"value": 1}, error=None),),
                )

            return asyncio.create_task(complete())

    batches = Batches()
    tool = PostgresDeepAgentRunner._batch_tools(
        cast(Any, batches), "project-1", "sam", "thread-1", "agent-run-1"
    )[0]

    call = {
        "name": "start_project_batch_run",
        "type": "tool_call",
        "args": {"definition_id": "definition-1"},
        "id": "call-1",
    }
    result = await tool.ainvoke(call)
    await tool.ainvoke(call)
    resumed_tool = PostgresDeepAgentRunner._batch_tools(
        cast(Any, batches), "project-1", "sam", "thread-1", "agent-run-2"
    )[0]
    await resumed_tool.ainvoke(call)
    await resumed_tool.ainvoke({**call, "id": "call-2"})

    assert result.content == "Batch Run run-1 succeeded: 1 of 1 records produced outputs; 0 failed."
    assert len(batches.submissions) == 4
    assert batches.submissions[0][0:2] == ("project-1", "definition-1")
    assert batches.submissions[0][2] == batches.submissions[1][2]
    assert batches.submissions[0][2] == batches.submissions[2][2]
    assert batches.submissions[0][2] != batches.submissions[3][2]
    assert batches.submissions[0][3] == batches.submissions[1][3]
    assert batches.submissions[0][3].agent_run_id == "agent-run-1"
    assert batches.submissions[0][3].tool_call_id == "call-1"
    assert batches.enqueued_run_id == "run-1"


@pytest.mark.asyncio
async def test_agent_does_not_read_pending_batch_outputs_as_failures() -> None:
    completion = asyncio.Event()

    class Batches:
        async def submit_all(self, *_: object, **__: object) -> object:
            return SimpleNamespace(id="run-1")

        async def enqueue(self, *_: object) -> asyncio.Task[object]:
            async def finish() -> object:
                await completion.wait()
                return SimpleNamespace(
                    id="run-1",
                    status=BatchRunStatus.succeeded,
                    records=(SimpleNamespace(structured_output={"copied": True}, error=None),),
                )

            return asyncio.create_task(finish())

        async def load(self, *_: object) -> object:
            return SimpleNamespace(status=BatchRunStatus.running)

        async def inspect_results(self, *_: object, **__: object) -> object:
            pytest.fail("Pending results must not be presented as completed outputs")

    tools = {
        item.name: item
        for item in PostgresDeepAgentRunner._batch_tools(
            cast(Any, Batches()), "project-1", "sam", "thread-1", "agent-run-1"
        )
    }
    call = {
        "name": "start_project_batch_run",
        "type": "tool_call",
        "args": {"definition_id": "definition-1"},
        "id": "call-1",
    }
    started = asyncio.create_task(tools["start_project_batch_run"].ainvoke(call))
    await asyncio.sleep(0)
    assert not started.done()
    pending = json.loads(await tools["inspect_project_batch_results"].ainvoke({"run_id": "run-1"}))
    assert pending == {"runId": "run-1", "status": "running", "resultsReady": False}
    completion.set()
    assert (await started).content == (
        "Batch Run run-1 succeeded: 1 of 1 records produced outputs; 0 failed."
    )


@pytest.mark.asyncio
async def test_agent_reports_long_batch_as_pending_without_cancelling_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completion = asyncio.Event()
    background: asyncio.Task[object] | None = None
    monkeypatch.setattr(deep_agent, "_AGENT_BATCH_WAIT_SECONDS", 0.01)

    class Batches:
        async def submit_all(self, *_: object, **__: object) -> object:
            return SimpleNamespace(id="run-1")

        async def enqueue(self, *_: object) -> asyncio.Task[object]:
            nonlocal background

            async def finish() -> object:
                await completion.wait()
                return SimpleNamespace(status=BatchRunStatus.succeeded, records=())

            background = asyncio.create_task(finish())
            return background

    tool = PostgresDeepAgentRunner._batch_tools(
        cast(Any, Batches()), "project-1", "sam", "thread-1", "agent-run-1"
    )[0]
    response = await tool.ainvoke(
        {
            "name": "start_project_batch_run",
            "type": "tool_call",
            "args": {"definition_id": "definition-1"},
            "id": "call-1",
        }
    )
    assert "outputs are pending" in response.content.lower()
    assert background is not None and not background.cancelled()
    completion.set()
    await background


@pytest.mark.asyncio
async def test_agent_discovers_batch_runs_and_inspects_a_bounded_result_page() -> None:
    class Batches:
        async def load(self, _access: object, _project_id: str, _run_id: str) -> object:
            return SimpleNamespace(status=BatchRunStatus.succeeded)

        async def list(self, _access: object, project_id: str, **query: object) -> object:
            assert project_id == "project-1"
            assert query["limit"] == 10
            return SimpleNamespace(
                items=(
                    SimpleNamespace(
                        id="run-1",
                        definition_id="definition-1",
                        status="succeeded",
                        records=(SimpleNamespace(structured_output={"result": 6}, error=None),),
                        archived_at=None,
                    ),
                ),
                next_offset=None,
            )

        async def inspect_results(
            self, _access: object, project_id: str, run_id: str, **query: object
        ) -> object:
            assert (project_id, run_id) == ("project-1", "run-1")
            assert query["limit"] == 20
            return SimpleNamespace(
                items=(
                    SimpleNamespace(
                        dataset_record_id="record-1",
                        input={"load": 3},
                        structured_output={"result": 6},
                        error=None,
                    ),
                ),
                next_offset=None,
                summary=SimpleNamespace(
                    total_count=1,
                    succeeded_count=1,
                    failed_count=0,
                    numeric_count=1,
                    numeric_sum=6,
                    numeric_min=6,
                    numeric_max=6,
                    numeric_average=6,
                ),
            )

    tools = {
        item.name: item
        for item in PostgresDeepAgentRunner._batch_tools(
            cast(Any, Batches()), "project-1", "sam", "thread-1", "agent-run-1"
        )
    }

    listed = json.loads(await tools["list_project_batch_runs"].ainvoke({}))
    inspected = json.loads(
        await tools["inspect_project_batch_results"].ainvoke(
            {
                "run_id": "run-1",
                "aggregate_path": "/structuredOutput/result",
            }
        )
    )

    assert listed["items"] == [
        {
            "id": "run-1",
            "definitionId": "definition-1",
            "status": "succeeded",
            "recordCount": 1,
            "succeededCount": 1,
            "failedCount": 0,
            "archived": False,
        }
    ]
    assert inspected["items"] == [
        {
            "datasetRecordId": "record-1",
            "input": {"load": 3},
            "structuredOutput": {"result": 6},
            "error": None,
        }
    ]
    assert inspected["summary"]["numericSum"] == 6


@pytest.mark.asyncio
async def test_agent_reviews_and_starts_single_mcp_call_with_provenance() -> None:
    class Batches:
        initiation: BatchInitiation | None = None

        async def plan_mcp_call(self, *_: object) -> object:
            return SimpleNamespace(snapshot=lambda: {"pluginVersion": "1.0", "inputs": {"load": 3}})

        async def submit_mcp_call(self, *args: object, **kwargs: object) -> object:
            self.initiation = cast(BatchInitiation, kwargs["initiation"])
            assert args[4] == {"load": 3}
            assert args[5] == "1.0"
            return SimpleNamespace(id="run-1")

        async def enqueue(self, *_: object) -> asyncio.Task[object]:
            async def complete() -> object:
                return SimpleNamespace(
                    status=BatchRunStatus.succeeded,
                    records=(SimpleNamespace(structured_output={"result": 6}, error=None),),
                )

            return asyncio.create_task(complete())

    batches = Batches()
    tools = {
        item.name: item
        for item in PostgresDeepAgentRunner._batch_tools(
            cast(Any, batches), "project-1", "sam", "thread-1", "agent-run-1"
        )
    }
    plan = await tools["plan_project_mcp_call"].ainvoke(
        {"plugin_id": "fixture", "tool_name": "double", "arguments_json": '{"load":3}'}
    )
    started = await tools["start_project_mcp_call"].ainvoke(
        {
            "name": "start_project_mcp_call",
            "type": "tool_call",
            "id": "call-1",
            "args": {
                "plugin_id": "fixture",
                "tool_name": "double",
                "arguments_json": '{"load":3}',
                "expected_plugin_version": "1.0",
            },
        }
    )
    assert json.loads(plan)["inputs"] == {"load": 3}
    assert "MCP Call run-1 succeeded" in started.content
    assert batches.initiation == BatchInitiation(
        "agentRun", "approved", "thread-1", "agent-run-1", "call-1"
    )


@pytest.mark.asyncio
async def test_agent_reviews_and_starts_mcp_map_with_plugin_version() -> None:
    class Batches:
        initiation: BatchInitiation | None = None

        async def plan_mcp_dataset(self, *_: object) -> object:
            return SimpleNamespace(
                snapshot=lambda: {"datasetVersion": 2, "pluginVersion": "1.0", "invocationCount": 2}
            )

        async def submit_mcp_dataset(self, *args: object, **kwargs: object) -> object:
            assert args[5:7] == (2, "1.0")
            self.initiation = cast(BatchInitiation, kwargs["initiation"])
            return SimpleNamespace(id="run-1")

        async def enqueue(self, *_: object) -> asyncio.Task[object]:
            async def complete() -> object:
                return SimpleNamespace(
                    status=BatchRunStatus.partial,
                    records=(
                        SimpleNamespace(structured_output={"result": 4}, error=None),
                        SimpleNamespace(structured_output=None, error="failed"),
                    ),
                )

            return asyncio.create_task(complete())

    batches = Batches()
    tools = {
        item.name: item
        for item in PostgresDeepAgentRunner._batch_tools(
            cast(Any, batches), "project-1", "sam", "thread-1", "agent-run-1"
        )
    }
    plan = await tools["plan_project_mcp_map"].ainvoke(
        {"plugin_id": "fixture", "tool_name": "double", "dataset_id": "dataset-1"}
    )
    started = await tools["start_project_mcp_map"].ainvoke(
        {
            "name": "start_project_mcp_map",
            "type": "tool_call",
            "id": "call-1",
            "args": {
                "plugin_id": "fixture",
                "tool_name": "double",
                "dataset_id": "dataset-1",
                "expected_dataset_version": 2,
                "expected_plugin_version": "1.0",
            },
        }
    )
    assert json.loads(plan)["pluginVersion"] == "1.0"
    assert "1 of 2 records produced outputs; 1 failed" in started.content
    assert batches.initiation == BatchInitiation(
        "agentRun", "approved", "thread-1", "agent-run-1", "call-1"
    )


@pytest.mark.asyncio
async def test_agent_reviews_and_starts_python_function_map_with_provenance() -> None:
    class Batches:
        initiation: BatchInitiation | None = None

        async def plan_python_dataset_map(self, *_: object) -> object:
            return SimpleNamespace(snapshot=lambda: {"itemInputName": "item", "invocationCount": 2})

        async def submit_python_dataset_map(self, *args: object, **kwargs: object) -> object:
            assert args[4:6] == (2, 3)
            self.initiation = cast(BatchInitiation, kwargs["initiation"])
            return SimpleNamespace(id="run-1")

        async def enqueue(self, *_: object) -> asyncio.Task[object]:
            async def complete() -> object:
                return SimpleNamespace(
                    status=BatchRunStatus.partial,
                    records=(
                        SimpleNamespace(structured_output={"result": 4}, error=None),
                        SimpleNamespace(structured_output=None, error="failed"),
                    ),
                )

            return asyncio.create_task(complete())

    batches = Batches()
    tools = {
        item.name: item
        for item in PostgresDeepAgentRunner._batch_tools(
            cast(Any, batches), "project-1", "sam", "thread-1", "agent-run-1"
        )
    }
    plan = await tools["plan_project_python_map"].ainvoke(
        {"definition_id": "function-1", "dataset_id": "dataset-1"}
    )
    started = await tools["start_project_python_map"].ainvoke(
        {
            "name": "start_project_python_map",
            "type": "tool_call",
            "id": "call-1",
            "args": {
                "definition_id": "function-1",
                "dataset_id": "dataset-1",
                "expected_dataset_version": 2,
                "expected_definition_revision": 3,
            },
        }
    )
    assert json.loads(plan) == {"itemInputName": "item", "invocationCount": 2}
    assert "1 of 2 Records produced outputs; 1 failed" in started.content
    assert batches.initiation == BatchInitiation(
        "agentRun", "approved", "thread-1", "agent-run-1", "call-1"
    )


@pytest.mark.asyncio
async def test_agent_transform_tools_call_the_project_module() -> None:
    class Transforms:
        def __init__(self) -> None:
            self.started: tuple[str, dict[str, object], dict[str, object]] | None = None
            self.initiation: TransformInitiation | None = None
            self.saved: tuple[str, str] | None = None

        async def start_run(
            self,
            _access: object,
            _project_id: str,
            definition_id: str,
            record: dict[str, object],
            parameters: dict[str, object],
            initiation: TransformInitiation,
        ) -> object:
            self.started = definition_id, record, parameters
            self.initiation = initiation
            return SimpleNamespace(id="run-1", status="succeeded")

        async def save_run_as_dataset(
            self, _access: object, _project_id: str, run_id: str, name: str
        ) -> object:
            self.saved = run_id, name
            return SimpleNamespace(id="dataset-1", name=name)

    transforms = Transforms()
    tools = {
        item.name: item
        for item in PostgresDeepAgentRunner._transform_tools(
            cast(Any, transforms), "project-1", "sam", "thread-1", "agent-run-1"
        )
    }
    started = await tools["start_project_transform_run"].ainvoke(
        {
            "definition_id": "definition-1",
            "record_json": '{"load": 3}',
            "parameters_json": '{"factor": 2}',
        }
    )
    saved = await tools["save_project_transform_run_as_dataset"].ainvoke(
        {
            "run_id": "run-1",
            "name": "Saved",
        }
    )
    assert started == "Transform Run run-1 succeeded."
    assert transforms.started == ("definition-1", {"load": 3}, {"factor": 2})
    assert transforms.initiation == TransformInitiation(
        "agentRun", "approved", "thread-1", "agent-run-1"
    )
    assert saved == "Saved Dataset Saved (dataset-1) from Transform Run run-1."
    assert transforms.saved == ("run-1", "Saved")


@pytest.mark.asyncio
async def test_agent_reviews_named_python_function_inputs_before_approved_run() -> None:
    class Transforms:
        started: tuple[dict[str, object], int, TransformInitiation] | None = None

        async def plan_function_call(
            self,
            _access: object,
            _project_id: str,
            _definition_id: str,
            inputs: dict[str, object],
            parameters: dict[str, object],
        ) -> object:
            assert inputs == {"values": [3, 1, 2]}
            assert parameters == {}
            return SimpleNamespace(snapshot=lambda: {"definitionRevision": 2, "inputs": inputs})

        async def start_function_call(
            self,
            _access: object,
            _project_id: str,
            _definition_id: str,
            inputs: dict[str, object],
            _parameters: dict[str, object],
            *,
            expected_revision: int,
            initiation: TransformInitiation,
        ) -> object:
            self.started = inputs, expected_revision, initiation
            return SimpleNamespace(id="run-2", status="succeeded")

    transforms = Transforms()
    tools = {
        item.name: item
        for item in PostgresDeepAgentRunner._transform_tools(
            cast(Any, transforms), "project-1", "sam", "thread-1", "agent-run-1"
        )
    }
    plan = await tools["plan_project_function_call"].ainvoke(
        {"definition_id": "definition-1", "inputs_json": '{"values":[3,1,2]}'}
    )
    run = await tools["start_project_function_call"].ainvoke(
        {
            "definition_id": "definition-1",
            "inputs_json": '{"values":[3,1,2]}',
            "expected_revision": 2,
        }
    )
    assert json.loads(plan) == {"definitionRevision": 2, "inputs": {"values": [3, 1, 2]}}
    assert run == "Transform Run run-2 succeeded."
    assert transforms.started == (
        {"values": [3, 1, 2]},
        2,
        TransformInitiation("agentRun", "approved", "thread-1", "agent-run-1"),
    )


@pytest.mark.asyncio
async def test_invalid_approved_transform_proposal_returns_actionable_tool_error() -> None:
    projects = create_memory_project_module()
    access = ProjectAccess(subject="sam")
    project = await projects.create(access, "Transform proposal")
    transforms = TransformModule(projects, MemoryTransformStore())
    tools = {
        item.name: item
        for item in PostgresDeepAgentRunner._transform_tools(
            transforms, project.id, access.subject, "thread-1", "run-1"
        )
    }
    input_schema_json = json.dumps(
        {
            "type": "object",
            "properties": {"record": {"type": "object"}},
            "required": ["record"],
            "additionalProperties": False,
        }
    )

    invalid_selectors = await tools["create_project_transform"].ainvoke(
        {
            "name": "Copy dataset records",
            "source": "export default function transform(record, parameters) { return record; }",
            "input_selectors_json": '[{"path":"$"}]',
            "input_schema_json": input_schema_json,
            "output_schema_json": '{"type":"object"}',
        }
    )
    assert "input_selectors_json must be a JSON object" in invalid_selectors

    invalid_source = await tools["create_project_transform"].ainvoke(
        {
            "name": "Copy dataset records",
            "source": "export default function transform(record, parameters) { return record; }",
            "input_selectors_json": '{"record":""}',
            "input_schema_json": input_schema_json,
            "output_schema_json": '{"type":"object"}',
        }
    )
    assert "Transform source is not valid Python" in invalid_source
    assert await transforms.list(access, project.id) == ()

    created = await tools["create_project_transform"].ainvoke(
        {
            "name": "Copy dataset records",
            "source": "def transform(inputs, parameters):\n    return dict(inputs['record'])\n",
            "input_selectors_json": '{"record":""}',
            "input_schema_json": input_schema_json,
            "output_schema_json": '{"type":"object"}',
        }
    )
    created_function = json.loads(created)
    assert created_function["created"] == "python_function"
    definition = (await transforms.list(access, project.id))[0]
    assert created_function["id"] == definition.id
    assert created_function["revision"] == definition.revision
    invalid_revision = await tools["update_project_transform"].ainvoke(
        {
            "definition_id": definition.id,
            "name": "Copy dataset records",
            "source": "export default function transform(record) { return record; }",
            "input_selectors_json": '{"record":""}',
            "input_schema_json": input_schema_json,
            "output_schema_json": '{"type":"object"}',
        }
    )
    assert "Transform source is not valid Python" in invalid_revision
    assert (await transforms.load(access, project.id, definition.id)).revision == 1


@pytest.mark.asyncio
async def test_agent_has_one_approved_dataset_transform_action_for_both_modes() -> None:
    class Inputs:
        started: list[object] = []

        async def plan_dataset_run(self, *_: object) -> object:
            return SimpleNamespace(snapshot=lambda: {"mode": "dataset", "invocationCount": 1})

        async def start_dataset_run(self, *args: object, **kwargs: object) -> object:
            self.started.append((args, kwargs))
            return SimpleNamespace(id="run-1", status="succeeded", records=None)

    inputs = Inputs()
    tools = {
        item.name: item
        for item in PostgresDeepAgentRunner._transform_input_tools(
            cast(Any, inputs), "project-1", "sam", "thread-1", "agent-run-1"
        )
    }
    plan = await tools["plan_project_dataset_transform_run"].ainvoke(
        {"definition_id": "transform-1", "dataset_id": "dataset-1", "mode": "dataset"}
    )
    result = await tools["start_project_dataset_transform_run"].ainvoke(
        {
            "name": "start_project_dataset_transform_run",
            "type": "tool_call",
            "args": {
                "definition_id": "transform-1",
                "dataset_id": "dataset-1",
                "mode": "dataset",
                "expected_dataset_version": 2,
                "expected_transform_revision": 3,
            },
            "id": "call-1",
        }
    )
    assert json.loads(plan) == {"mode": "dataset", "invocationCount": 1}
    assert result.content == "Transform Run run-1 succeeded."
    assert len(inputs.started) == 1


@pytest.mark.asyncio
async def test_agent_reviews_and_starts_a_retained_transform_output_selection() -> None:
    class Transforms:
        def __init__(self) -> None:
            self.started: tuple[OutputSelection, TransformInitiation] | None = None

        async def plan_output_selection(
            self,
            _access: object,
            _project_id: str,
            _definition_id: str,
            selection: OutputSelection,
            _parameters: dict[str, object],
        ) -> object:
            assert selection.source_run_id == "source-run-1"
            return SimpleNamespace(snapshot=lambda: {"positions": [1]})

        async def start_output_selected_run(
            self,
            _access: object,
            _project_id: str,
            _definition_id: str,
            selection: OutputSelection,
            _parameters: dict[str, object],
            initiation: TransformInitiation,
        ) -> object:
            self.started = (selection, initiation)
            return SimpleNamespace(id="run-3", status="succeeded")

    transforms = Transforms()
    tools = {
        item.name: item
        for item in PostgresDeepAgentRunner._transform_tools(
            cast(Any, transforms), "project-1", "sam", "thread-1", "agent-run-1"
        )
    }
    choice = json.dumps(
        {
            "source_run_id": "source-run-1",
            "output_path": "/items",
            "expected_definition_revision": 3,
            "sort_path": "/score",
            "limit": 1,
        }
    )
    plan = await tools["plan_project_transform_output_selection"].ainvoke(
        {"definition_id": "transform-1", "selection_json": choice}
    )
    started = await tools["start_project_transform_output_selection_run"].ainvoke(
        {"definition_id": "transform-1", "selection_json": choice}
    )
    assert json.loads(plan) == {"positions": [1]}
    assert started == "Transform Run run-3 succeeded."
    assert transforms.started == (
        OutputSelection("source-run-1", "/items", 3, sort_path="/score", limit=1),
        TransformInitiation("agentRun", "approved", "thread-1", "agent-run-1"),
    )


@pytest.mark.asyncio
async def test_agent_reviews_and_starts_a_result_set_selection() -> None:
    class Inputs:
        def __init__(self) -> None:
            self.started: tuple[object, TransformInitiation] | None = None

        async def plan_result_set_selection(
            self,
            _access: object,
            _project_id: str,
            _definition_id: str,
            selection: object,
            _parameters: dict[str, object],
        ) -> object:
            assert selection == ResultSetSelection("batch-run-1", "/score", 3, limit=2)
            return SimpleNamespace(snapshot=lambda: {"selectedCount": 2})

        async def start_result_set_run(
            self,
            _access: object,
            _project_id: str,
            _definition_id: str,
            selection: object,
            _parameters: dict[str, object],
            initiation: TransformInitiation,
        ) -> object:
            self.started = (selection, initiation)
            return SimpleNamespace(id="run-4", status="succeeded")

    inputs = Inputs()
    tools = {
        item.name: item
        for item in PostgresDeepAgentRunner._transform_input_tools(
            cast(Any, inputs), "project-1", "sam", "thread-1", "agent-run-1"
        )
    }
    choice = json.dumps(
        {
            "source_run_id": "batch-run-1",
            "output_path": "/score",
            "expected_definition_revision": 3,
            "limit": 2,
        }
    )
    plan = await tools["plan_project_transform_result_set_selection"].ainvoke(
        {"definition_id": "transform-1", "selection_json": choice}
    )
    started = await tools["start_project_transform_result_set_selection_run"].ainvoke(
        {"definition_id": "transform-1", "selection_json": choice}
    )
    assert json.loads(plan) == {"selectedCount": 2}
    assert started == "Transform Run run-4 succeeded."
    assert inputs.started == (
        ResultSetSelection("batch-run-1", "/score", 3, limit=2),
        TransformInitiation("agentRun", "approved", "thread-1", "agent-run-1"),
    )


@pytest.mark.asyncio
async def test_agent_reviews_and_starts_retained_mcp_output_selection() -> None:
    class Inputs:
        def __init__(self) -> None:
            self.started: tuple[object, TransformInitiation] | None = None

        async def plan_artifact_selection(
            self,
            _access: object,
            _project_id: str,
            _definition_id: str,
            selection: object,
            _parameters: dict[str, object],
        ) -> object:
            assert selection == ArtifactSelection("artifact-1", 2, "/items", 3, limit=2)
            return SimpleNamespace(snapshot=lambda: {"selectedCount": 2})

        async def start_artifact_run(
            self,
            _access: object,
            _project_id: str,
            _definition_id: str,
            selection: object,
            _parameters: dict[str, object],
            initiation: TransformInitiation,
        ) -> object:
            self.started = (selection, initiation)
            return SimpleNamespace(id="run-5", status="succeeded")

    inputs = Inputs()
    tools = {
        item.name: item
        for item in PostgresDeepAgentRunner._transform_input_tools(
            cast(Any, inputs), "project-1", "sam", "thread-1", "agent-run-1"
        )
    }
    choice = json.dumps(
        {
            "artifact_id": "artifact-1",
            "expected_artifact_version": 2,
            "output_path": "/items",
            "expected_definition_revision": 3,
            "limit": 2,
        }
    )
    plan = await tools["plan_project_transform_artifact_selection"].ainvoke(
        {"definition_id": "transform-1", "selection_json": choice}
    )
    started = await tools["start_project_transform_artifact_selection_run"].ainvoke(
        {"definition_id": "transform-1", "selection_json": choice}
    )
    assert json.loads(plan) == {"selectedCount": 2}
    assert started == "Transform Run run-5 succeeded."
    assert inputs.started == (
        ArtifactSelection("artifact-1", 2, "/items", 3, limit=2),
        TransformInitiation("agentRun", "approved", "thread-1", "agent-run-1"),
    )


@pytest.mark.asyncio
async def test_agent_artifact_save_carries_agent_run_provenance() -> None:
    class Transforms:
        async def save_run_as_artifact(
            self, access: ArtifactMutationAccess, project_id: str, run_id: str, title: str
        ) -> object:
            assert (access.subject, access.thread_id, access.run_id) == (
                "sam",
                "thread-1",
                "agent-run-1",
            )
            assert (project_id, run_id, title) == ("project-1", "transform-run-1", "Checked")
            return SimpleNamespace(
                artifact=SimpleNamespace(title=title, id=SimpleNamespace(root="artifact-1"))
            )

    tools = {
        item.name: item
        for item in PostgresDeepAgentRunner._transform_tools(
            cast(Any, Transforms()), "project-1", "sam", "thread-1", "agent-run-1"
        )
    }
    result = await tools["save_project_transform_run_as_artifact"].ainvoke(
        {"run_id": "transform-run-1", "title": "Checked"}
    )

    assert result == "Saved Artifact Checked (artifact-1) from Transform Run transform-run-1."


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
