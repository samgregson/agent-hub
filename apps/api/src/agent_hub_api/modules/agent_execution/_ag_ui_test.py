import pytest
from ag_ui.core import EventType, ResumeEntry, ToolCallResultEvent, ToolCallStartEvent
from ag_ui_langgraph import LangGraphAgent
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


def test_stream_approval_binds_retry_not_completed_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(LangGraphAgent, "_dispatch_event", lambda _self, event: event)
    adapter = object.__new__(AgentHubLangGraphAgent)
    adapter._visible_tool_calls = []
    for event in [
        ToolCallStartEvent(
            type=EventType.TOOL_CALL_START,
            tool_call_id="old",
            tool_call_name="foundation_protected_action",
        ),
        ToolCallResultEvent(
            type=EventType.TOOL_CALL_RESULT,
            message_id="result",
            tool_call_id="old",
            content="failed",
        ),
        ToolCallStartEvent(
            type=EventType.TOOL_CALL_START,
            tool_call_id="retry",
            tool_call_name="foundation_protected_action",
        ),
    ]:
        adapter._dispatch_event(event)

    [mapped] = adapter._interrupts_to_agui([hitl_interrupt()])
    assert mapped.tool_call_id == "retry"


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


def test_batched_hitl_actions_map_and_resume_in_action_order() -> None:
    actions = [
        {
            "name": "create_project_function",
            "args": {"name": "uppercase_text"},
        },
        {"name": "create_project_function", "args": {"name": "word_stats"}},
        {
            "name": "create_project_function",
            "args": {"name": "bullet_summary"},
        },
    ]
    interrupt = Interrupt(
        id="interrupt-batch",
        value={
            "action_requests": actions,
            "review_configs": [
                {
                    "action_name": action["name"],
                    "allowed_decisions": ["approve", "reject"],
                }
                for action in actions
            ],
        },
    )
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": f"tool-{index}",
                    "name": "create_project_function",
                    "args": action["args"],
                    "type": "tool_call",
                }
                for index, action in enumerate(actions)
            ],
        )
    ]

    mapped = map_langchain_interrupts([interrupt], messages)

    assert [item.id for item in mapped] == [
        "interrupt-batch:0",
        "interrupt-batch:1",
        "interrupt-batch:2",
    ]
    assert [item.tool_call_id for item in mapped] == ["tool-0", "tool-1", "tool-2"]
    adapter = object.__new__(AgentHubLangGraphAgent)
    command = adapter._build_command_from_agui_resume(
        [
            ResumeEntry(
                interrupt_id="interrupt-batch:0",
                status="resolved",
                payload={"approved": True},
            ),
            ResumeEntry(
                interrupt_id="interrupt-batch:1",
                status="resolved",
                payload={"approved": False, "reason": "Not now"},
            ),
            ResumeEntry(
                interrupt_id="interrupt-batch:2",
                status="resolved",
                payload={"approved": True},
            ),
        ],
        open_interrupts=mapped,
    )

    assert command.resume == {
        "decisions": [
            {"type": "approve"},
            {"type": "reject", "message": "Not now"},
            {"type": "approve"},
        ]
    }


@pytest.mark.asyncio
async def test_checkpoint_batch_resumes_without_echoed_messages() -> None:
    from typing import Any

    from ag_ui.core import RunAgentInput
    from langchain.agents import create_agent
    from langchain.agents.middleware import HumanInTheLoopMiddleware
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import HumanMessage, ToolMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langchain_core.tools import tool
    from langgraph.checkpoint.memory import InMemorySaver

    executed: list[str] = []

    @tool
    async def gated(note: str) -> str:
        """Perform a gated operation."""
        executed.append(note)
        return note

    class BatchModel(BaseChatModel):
        @property
        def _llm_type(self) -> str:
            return "approval-test"

        def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
            return self

        def _generate(self, messages: Any, **kwargs: Any) -> ChatResult:
            if any(isinstance(message, ToolMessage) for message in messages):
                message = AIMessage(content="Done")
            else:
                message = AIMessage(
                    content="",
                    tool_calls=[
                        {"id": "call-1", "name": "gated", "args": {"note": "one"}},
                        {"id": "call-2", "name": "gated", "args": {"note": "two"}},
                    ],
                )
            return ChatResult(generations=[ChatGeneration(message=message)])

        async def _agenerate(self, messages: Any, **kwargs: Any) -> ChatResult:
            return self._generate(messages, **kwargs)

    graph = create_agent(
        BatchModel(),
        tools=[gated],
        middleware=[HumanInTheLoopMiddleware(interrupt_on={"gated": True})],
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": "batch-thread"}}
    await graph.ainvoke({"messages": [HumanMessage(content="Go", id="user-1")]}, config)
    checkpoint = await graph.aget_state(config)
    mapped = map_langchain_interrupts(checkpoint.interrupts, checkpoint.values["messages"])
    assert [item.tool_call_id for item in mapped] == ["call-1", "call-2"]
    agent = AgentHubLangGraphAgent(
        name="test",
        graph=graph,
        enable_legacy_on_interrupt_event=False,
        emit_interrupt_outcome=True,
    )
    request = RunAgentInput.model_validate(
        {
            "threadId": "batch-thread",
            "runId": "resume-1",
            "messages": [],
            "tools": [],
            "context": [],
            "forwardedProps": {},
            "resume": [
                {"interruptId": mapped[1].id, "status": "resolved", "payload": {"approved": False}},
                {"interruptId": mapped[0].id, "status": "resolved", "payload": {"approved": True}},
            ],
        }
    )
    events = [event async for event in agent.run(request)]
    assert not [event for event in events if event.type == "RUN_ERROR"]
    assert executed == ["one"]
    final = await graph.aget_state(config)
    assert not final.interrupts
    assert [
        message.tool_call_id
        for message in final.values["messages"]
        if isinstance(message, ToolMessage)
    ] == ["call-2", "call-1"]
