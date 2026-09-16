from types import SimpleNamespace
from typing import cast

from deepagents.middleware._fs_interrupt import _build_interrupt_on_from_permissions
from langchain.tools.tool_node import ToolCallRequest

from agent_hub_api.modules.agent_execution._deep_agent import _project_file_permissions


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
