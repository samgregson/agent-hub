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
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module


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


def test_datasets_are_not_project_files_in_the_agent_instructions() -> None:
    assert "Datasets and Batch Definitions are durable Project records" in _AGENT_SYSTEM_PROMPT
    assert "Do not write a Dataset as a JSON file under /project." in _AGENT_SYSTEM_PROMPT


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

    await runner._agent_for("project-1", subject="sam")

    names = {registered.name for registered in captured["tools"]}
    assert {"discover_project_datasets", "load_project_dataset"} <= names
    assert "create_project_dataset" in captured["interrupt_on"]
    assert "create_project_batch_definition" in captured["interrupt_on"]
    assert "start_project_batch_run" in captured["interrupt_on"]
    assert "start_project_batch_run" in names
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
            self.submission: tuple[str, str] | None = None
            self.enqueued_run_id: str | None = None

        async def submit_all(self, _access: object, project_id: str, definition_id: str) -> object:
            self.submission = (project_id, definition_id)
            return SimpleNamespace(id="run-1")

        async def enqueue(self, _access: object, _project_id: str, run_id: str) -> None:
            self.enqueued_run_id = run_id

    batches = Batches()
    tool = PostgresDeepAgentRunner._batch_tools(cast(Any, batches), "project-1", "sam")[0]

    result = await tool.ainvoke({"definition_id": "definition-1"})

    assert result == "Started Batch Run run-1."
    assert batches.submission == ("project-1", "definition-1")
    assert batches.enqueued_run_id == "run-1"


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
        for item in PostgresDeepAgentRunner._batch_tools(cast(Any, Batches()), "project-1", "sam")
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
            self.saved: tuple[str, str] | None = None

        async def start_run(
            self, _access: object, _project_id: str, definition_id: str,
            record: dict[str, object], parameters: dict[str, object],
        ) -> object:
            self.started = definition_id, record, parameters
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
            cast(Any, transforms), "project-1", "sam"
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
    assert saved == "Saved Dataset Saved (dataset-1) from Transform Run run-1."
    assert transforms.saved == ("run-1", "Saved")


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
