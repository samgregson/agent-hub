from collections.abc import AsyncIterator

import pytest
from ag_ui.core import (
    BaseEvent,
    Interrupt,
    Message,
    RunAgentInput,
    RunFinishedEvent,
    RunFinishedInterruptOutcome,
    RunStartedEvent,
    TextMessageContentEvent,
)

from agent_hub_api.modules.agent_execution import (
    AgentRunStatus,
    DuplicateAgentRun,
    create_memory_agent_execution,
)


def input_for(thread_id: str, run_id: str) -> RunAgentInput:
    return RunAgentInput.model_validate(
        {
            "threadId": thread_id,
            "runId": run_id,
            "messages": [],
            "tools": [],
            "context": [],
            "forwardedProps": {},
        }
    )


class DeterministicRunner:
    async def load_messages(self, thread_id: str) -> tuple[Message, ...]:
        del thread_id
        return ()

    async def run(self, input_data: RunAgentInput) -> AsyncIterator[BaseEvent]:
        yield RunStartedEvent(thread_id=input_data.thread_id, run_id=input_data.run_id)
        yield TextMessageContentEvent(message_id="message-1", delta="Hello")
        yield RunFinishedEvent(thread_id=input_data.thread_id, run_id=input_data.run_id)


class FailingRunner:
    async def load_messages(self, thread_id: str) -> tuple[Message, ...]:
        del thread_id
        return ()

    async def run(self, input_data: RunAgentInput) -> AsyncIterator[BaseEvent]:
        yield RunStartedEvent(thread_id=input_data.thread_id, run_id=input_data.run_id)
        raise RuntimeError("provider unavailable")


class InterruptingRunner:
    async def load_messages(self, thread_id: str) -> tuple[Message, ...]:
        del thread_id
        return ()

    async def run(self, input_data: RunAgentInput) -> AsyncIterator[BaseEvent]:
        yield RunStartedEvent(thread_id=input_data.thread_id, run_id=input_data.run_id)
        yield RunFinishedEvent(
            thread_id=input_data.thread_id,
            run_id=input_data.run_id,
            outcome=RunFinishedInterruptOutcome(
                interrupts=[Interrupt(id="approval-1", reason="tool_call")]
            ),
        )


@pytest.mark.asyncio
async def test_run_lifecycle_is_durable_and_thread_scoped() -> None:
    execution = create_memory_agent_execution(DeterministicRunner())

    first_events = [event async for event in await execution.start(input_for("a", "run-1"))]
    second_events = [event async for event in await execution.start(input_for("b", "run-2"))]

    first_runs = await execution.list_runs("a")
    second_runs = await execution.list_runs("b")
    assert len(first_events) == 3
    assert len(second_events) == 3
    assert first_runs[0].status is AgentRunStatus.SUCCEEDED
    assert second_runs[0].id == "run-2"


@pytest.mark.asyncio
async def test_duplicate_run_id_is_rejected() -> None:
    execution = create_memory_agent_execution(DeterministicRunner())
    input_data = input_for("a", "same-run")

    _ = [event async for event in await execution.start(input_data)]

    with pytest.raises(DuplicateAgentRun):
        await execution.start(input_data)


@pytest.mark.asyncio
async def test_failed_stream_updates_run_status() -> None:
    execution = create_memory_agent_execution(FailingRunner())

    with pytest.raises(RuntimeError, match="provider unavailable"):
        _ = [event async for event in await execution.start(input_for("a", "run-1"))]

    run = (await execution.list_runs("a"))[0]
    assert run.status is AgentRunStatus.FAILED
    assert run.error == {"message": "provider unavailable"}


@pytest.mark.asyncio
async def test_interrupt_is_a_durable_non_failure_outcome() -> None:
    execution = create_memory_agent_execution(InterruptingRunner())

    _ = [event async for event in await execution.start(input_for("a", "run-1"))]

    run = (await execution.list_runs("a"))[0]
    assert run.status is AgentRunStatus.INTERRUPTED
    assert run.error is None
