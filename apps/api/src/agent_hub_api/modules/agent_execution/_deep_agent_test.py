from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from deepagents.middleware._fs_interrupt import _build_interrupt_on_from_permissions
from langchain.tools.tool_node import ToolCallRequest

import agent_hub_api.modules.agent_execution._deep_agent as deep_agent
from agent_hub_api.modules.agent_execution._deep_agent import (
    _AGENT_SYSTEM_PROMPT,
    PostgresDeepAgentRunner,
    _project_file_permissions,
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


@pytest.mark.asyncio
async def test_agent_uses_structured_interrupt_outcomes_without_legacy_custom_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = object.__new__(PostgresDeepAgentRunner)
    runner._checkpointer = cast(Any, object())
    runner._model = cast(Any, object())
    runner._project_files = cast(Any, object())
    runner._plugin_gateway = None
    runner._settings = cast(Any, SimpleNamespace(
        agent_recursion_limit=10,
        enable_foundation_test_tool=False,
    ))

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
