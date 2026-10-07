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
from agent_hub_api.modules.batch_execution import BatchInitiation
from agent_hub_api.modules.datasets import (
    DatasetModule,
    DatasetRecordInput,
    MemoryDatasetStore,
)
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module
from agent_hub_api.modules.transforms import TransformInitiation


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
    runner._settings = cast(
        Any,
        SimpleNamespace(agent_recursion_limit=10, enable_foundation_test_tool=False),
    )
    captured: dict[str, Any] = {}

    def create_agent(**kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(nodes={})

    monkeypatch.setattr(deep_agent, "create_deep_agent", create_agent)

    await runner._agent_for(
        "project-1", thread_id="thread-1", run_id="agent-run-1", subject="sam"
    )

    names = {registered.name for registered in captured["tools"]}
    assert {"discover_project_datasets", "load_project_dataset"} <= names
    assert "create_project_dataset" in captured["interrupt_on"]
    assert "create_project_batch_definition" in captured["interrupt_on"]
    assert "start_project_batch_run" in captured["interrupt_on"]
    assert "start_project_batch_run" in names
    assert {"list_project_batch_runs", "inspect_project_batch_results"} <= names
    assert "inspect_project_batch_results" not in captured["interrupt_on"]
    assert "create_project_transform_batch_definition" in captured["interrupt_on"]
    assert "create_project_transform_batch_definition" in names
    assert {"discover_project_transforms", "load_project_transform"} <= names
    assert "create_project_transform" in captured["interrupt_on"]
    assert "update_project_transform" in captured["interrupt_on"]
    assert "delete_project_transform" in captured["interrupt_on"]
    assert "start_project_transform_run" in captured["interrupt_on"]
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

    assert result == (
        '{"id": "'
        + definition.id
        + '", "name": "Beam checks", "datasetId": "'
        + dataset.id
            + '", "pluginId": "reference-calculation", "toolName": "calculate_beam", '
            '"transformDefinitionId": null, "argumentMappings": {"length_m": "/length"}}'
    )


@pytest.mark.asyncio
async def test_agent_batch_tool_submits_and_queues_a_host_batch_run() -> None:
    class Batches:
        def __init__(self) -> None:
            self.submissions: list[tuple[str, str, str, BatchInitiation]] = []
            self.enqueued_run_id: str | None = None

        async def submit_all(
            self, _access: object, project_id: str, definition_id: str,
            idempotency_key: str, *, initiation: BatchInitiation,
        ) -> object:
            self.submissions.append((project_id, definition_id, idempotency_key, initiation))
            return SimpleNamespace(id="run-1")

        async def enqueue(self, _access: object, _project_id: str, run_id: str) -> None:
            self.enqueued_run_id = run_id

    batches = Batches()
    tool = PostgresDeepAgentRunner._batch_tools(
        cast(Any, batches), "project-1", "sam", "thread-1", "agent-run-1"
    )[0]

    call = {
        "name": "start_project_batch_run", "type": "tool_call",
        "args": {"definition_id": "definition-1"}, "id": "call-1",
    }
    result = await tool.ainvoke(call)
    await tool.ainvoke(call)
    resumed_tool = PostgresDeepAgentRunner._batch_tools(
        cast(Any, batches), "project-1", "sam", "thread-1", "agent-run-2"
    )[0]
    await resumed_tool.ainvoke(call)
    await resumed_tool.ainvoke({**call, "id": "call-2"})

    assert result.content == "Started Batch Run run-1."
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
async def test_agent_discovers_batch_runs_and_inspects_a_bounded_result_page() -> None:
    class Batches:
        async def list(self, _access: object, project_id: str, **query: object) -> object:
            assert project_id == "project-1"
            assert query["limit"] == 10
            return SimpleNamespace(
                items=(SimpleNamespace(
                    id="run-1", definition_id="definition-1", status="succeeded",
                    records=(SimpleNamespace(structured_output={"result": 6}, error=None),),
                    archived_at=None,
                ),), next_offset=None,
            )

        async def inspect_results(
            self, _access: object, project_id: str, run_id: str, **query: object
        ) -> object:
            assert (project_id, run_id) == ("project-1", "run-1")
            assert query["limit"] == 20
            return SimpleNamespace(
                items=(SimpleNamespace(
                    dataset_record_id="record-1", input={"load": 3},
                    structured_output={"result": 6}, error=None,
                ),),
                next_offset=None,
                summary=SimpleNamespace(
                    total_count=1, succeeded_count=1, failed_count=0,
                    numeric_count=1, numeric_sum=6, numeric_min=6,
                    numeric_max=6, numeric_average=6,
                ),
            )

    tools = {
        item.name: item for item in PostgresDeepAgentRunner._batch_tools(
            cast(Any, Batches()), "project-1", "sam", "thread-1", "agent-run-1"
        )
    }

    listed = json.loads(await tools["list_project_batch_runs"].ainvoke({}))
    inspected = json.loads(await tools["inspect_project_batch_results"].ainvoke({
        "run_id": "run-1", "aggregate_path": "/structuredOutput/result",
    }))

    assert listed["items"] == [{
        "id": "run-1", "definitionId": "definition-1", "status": "succeeded",
        "recordCount": 1, "succeededCount": 1, "failedCount": 0,
        "archived": False,
    }]
    assert inspected["items"] == [{
        "datasetRecordId": "record-1", "input": {"load": 3},
        "structuredOutput": {"result": 6}, "error": None,
    }]
    assert inspected["summary"]["numericSum"] == 6


@pytest.mark.asyncio
async def test_agent_can_propose_transform_batch_definition_after_approval() -> None:
    class Batches:
        async def define_transform_batch(
            self, _access: object, project_id: str, dataset_id: str,
            name: str, transform_definition_id: str,
        ) -> object:
            assert (project_id, dataset_id, name, transform_definition_id) == (
                "project-1", "dataset-1", "Double loads", "transform-1"
            )
            return SimpleNamespace(id="definition-1", name=name)

    tools = {
        item.name: item
        for item in PostgresDeepAgentRunner._batch_tools(
            cast(Any, Batches()), "project-1", "sam", "thread-1", "agent-run-1"
        )
    }
    result = await tools["create_project_transform_batch_definition"].ainvoke({
        "dataset_id": "dataset-1", "name": "Double loads",
        "transform_definition_id": "transform-1",
    })

    assert result == "Created Batch Definition Double loads (definition-1)."


@pytest.mark.asyncio
async def test_agent_transform_tools_call_the_project_module() -> None:
    class Transforms:
        def __init__(self) -> None:
            self.started: tuple[str, dict[str, object], dict[str, object]] | None = None
            self.initiation: TransformInitiation | None = None
            self.saved: tuple[str, str] | None = None

        async def start_run(
            self, _access: object, _project_id: str, definition_id: str,
            record: dict[str, object], parameters: dict[str, object],
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
    started = await tools["start_project_transform_run"].ainvoke({
        "definition_id": "definition-1", "record_json": '{"load": 3}',
        "parameters_json": '{"factor": 2}',
    })
    saved = await tools["save_project_transform_run_as_dataset"].ainvoke({
        "run_id": "run-1", "name": "Saved",
    })
    assert started == "Transform Run run-1 succeeded."
    assert transforms.started == ("definition-1", {"load": 3}, {"factor": 2})
    assert transforms.initiation == TransformInitiation(
        "agentRun", "approved", "thread-1", "agent-run-1"
    )
    assert saved == "Saved Dataset Saved (dataset-1) from Transform Run run-1."
    assert transforms.saved == ("run-1", "Saved")


@pytest.mark.asyncio
async def test_agent_artifact_save_carries_agent_run_provenance() -> None:
    class Transforms:
        async def save_run_as_artifact(
            self, access: ArtifactMutationAccess, project_id: str, run_id: str, title: str
        ) -> object:
            assert (access.subject, access.thread_id, access.run_id) == (
                "sam", "thread-1", "agent-run-1"
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
    result = await tools["save_project_transform_run_as_artifact"].ainvoke({
        "run_id": "transform-run-1", "title": "Checked"
    })

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
