import pytest
from ag_ui.core import ResumeEntry
from langchain_core.messages import AIMessage
from langgraph.types import Interrupt

from agent_hub_api.modules.agent_execution._ag_ui import (
    AgentHubLangGraphAgent,
    map_langchain_interrupts,
)


def hitl_interrupt() -> Interrupt:
    return Interrupt(
        id="interrupt-1",
        value={
            "action_requests": [
                {
                    "name": "foundation_protected_action",
                    "args": {"note": "test"},
                    "description": "Approve the test action?",
                }
            ],
            "review_configs": [
                {
                    "action_name": "foundation_protected_action",
                    "allowed_decisions": ["approve", "reject"],
                }
            ],
        },
    )


def test_langchain_hitl_interrupt_maps_to_a_bound_ag_ui_tool_gate() -> None:
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "tool-1",
                    "name": "foundation_protected_action",
                    "args": {"note": "test"},
                    "type": "tool_call",
                }
            ],
        )
    ]

    [mapped] = map_langchain_interrupts([hitl_interrupt()], messages)

    assert mapped.id == "interrupt-1"
    assert mapped.reason == "tool_call"
    assert mapped.tool_call_id == "tool-1"
    assert mapped.message == "Approve the test action?"


def test_stream_fallback_resumes_with_langchain_hitl_decisions() -> None:
    adapter = object.__new__(AgentHubLangGraphAgent)
    adapter._visible_tool_calls = []

    [mapped] = adapter._interrupts_to_agui([hitl_interrupt()])
    command = adapter._build_command_from_agui_resume(
        [
            ResumeEntry(
                interrupt_id=mapped.id,
                status="resolved",
                payload={"approved": True},
            )
        ],
        open_interrupts=[mapped],
    )

    assert mapped.metadata is not None
    assert mapped.metadata["agentHubLangChainHITL"]["rawInterruptId"] == "interrupt-1"
    assert command.resume == {"decisions": [{"type": "approve"}]}


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"approved": True}, {"decisions": [{"type": "approve"}]}),
        (
            {"approved": False, "reason": "Not now"},
            {"decisions": [{"type": "reject", "message": "Not now"}]},
        ),
    ],
)
def test_ag_ui_tool_gate_response_maps_back_to_langchain_decision(
    payload: dict[str, object], expected: dict[str, object]
) -> None:
    [mapped] = map_langchain_interrupts(
        [hitl_interrupt()],
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tool-1",
                        "name": "foundation_protected_action",
                        "args": {"note": "test"},
                        "type": "tool_call",
                    }
                ],
            )
        ],
    )
    adapter = object.__new__(AgentHubLangGraphAgent)

    command = adapter._build_command_from_agui_resume(
        [ResumeEntry(interrupt_id=mapped.id, status="resolved", payload=payload)],
        open_interrupts=[mapped],
    )

    assert command.resume == expected
