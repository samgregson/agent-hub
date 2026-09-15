import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from typing import cast

import pytest
from ag_ui.core import (
    BaseEvent,
    Interrupt,
    ResumeEntry,
    RunAgentInput,
    RunErrorEvent,
    RunFinishedEvent,
    RunFinishedInterruptOutcome,
    RunStartedEvent,
    TextMessageContentEvent,
)

from agent_hub_api.modules.agent_execution import (
    AgentRunAlreadyActive,
    AgentRunStatus,
    AgentThreadState,
    DuplicateAgentRun,
    InvalidAgentRunResume,
    ScratchFile,
    ScratchFileNotFound,
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


class ScratchlessRunner:
    async def load_scratch_file(self, thread_id: str, *, project_id: str, path: str) -> ScratchFile:
        del thread_id, project_id, path
        raise ScratchFileNotFound


class DeterministicRunner(ScratchlessRunner):
    async def load_thread_state(self, thread_id: str, *, project_id: str) -> AgentThreadState:
        del thread_id, project_id
        return AgentThreadState(messages=(), interrupts=())

    async def run(self, input_data: RunAgentInput, *, project_id: str) -> AsyncIterator[BaseEvent]:
        del project_id
        yield RunStartedEvent(thread_id=input_data.thread_id, run_id=input_data.run_id)
        yield TextMessageContentEvent(message_id="message-1", delta="Hello")
        yield RunFinishedEvent(thread_id=input_data.thread_id, run_id=input_data.run_id)


class FailingRunner(ScratchlessRunner):
    async def load_thread_state(self, thread_id: str, *, project_id: str) -> AgentThreadState:
        del thread_id, project_id
        return AgentThreadState(messages=(), interrupts=())

    async def run(self, input_data: RunAgentInput, *, project_id: str) -> AsyncIterator[BaseEvent]:
        del project_id
        yield RunStartedEvent(thread_id=input_data.thread_id, run_id=input_data.run_id)
        raise RuntimeError("provider unavailable")


class InterruptingRunner(ScratchlessRunner):
    async def load_thread_state(self, thread_id: str, *, project_id: str) -> AgentThreadState:
        del thread_id, project_id
        return AgentThreadState(messages=(), interrupts=())

    async def run(self, input_data: RunAgentInput, *, project_id: str) -> AsyncIterator[BaseEvent]:
        del project_id
        yield RunStartedEvent(thread_id=input_data.thread_id, run_id=input_data.run_id)
        yield RunFinishedEvent(
            thread_id=input_data.thread_id,
            run_id=input_data.run_id,
            outcome=RunFinishedInterruptOutcome(
                interrupts=[Interrupt(id="approval-1", reason="tool_call")]
            ),
        )


class ErrorEventRunner(ScratchlessRunner):
    async def load_thread_state(self, thread_id: str, *, project_id: str) -> AgentThreadState:
        del thread_id, project_id
        return AgentThreadState(messages=(), interrupts=())

    async def run(self, input_data: RunAgentInput, *, project_id: str) -> AsyncIterator[BaseEvent]:
        del project_id
        yield RunStartedEvent(thread_id=input_data.thread_id, run_id=input_data.run_id)
        yield RunErrorEvent(message="model overloaded", code="MODEL_OVERLOADED")


class CancelledRunner(ScratchlessRunner):
    async def load_thread_state(self, thread_id: str, *, project_id: str) -> AgentThreadState:
        del thread_id, project_id
        return AgentThreadState(messages=(), interrupts=())

    async def run(self, input_data: RunAgentInput, *, project_id: str) -> AsyncIterator[BaseEvent]:
        del project_id
        yield RunStartedEvent(thread_id=input_data.thread_id, run_id=input_data.run_id)
        raise asyncio.CancelledError


class HangingRunner(ScratchlessRunner):
    async def load_thread_state(self, thread_id: str, *, project_id: str) -> AgentThreadState:
        del thread_id, project_id
        return AgentThreadState(messages=(), interrupts=())

    async def run(self, input_data: RunAgentInput, *, project_id: str) -> AsyncIterator[BaseEvent]:
        del project_id
        yield RunStartedEvent(thread_id=input_data.thread_id, run_id=input_data.run_id)
        await asyncio.Event().wait()


class ResumableRunner(ScratchlessRunner):
    def __init__(self) -> None:
        self.pending = True
        self.run_count = 0

    async def load_thread_state(self, thread_id: str, *, project_id: str) -> AgentThreadState:
        del thread_id, project_id
        return AgentThreadState(
            messages=(),
            interrupts=((Interrupt(id="approval-1", reason="tool_call"),) if self.pending else ()),
        )

    async def run(self, input_data: RunAgentInput, *, project_id: str) -> AsyncIterator[BaseEvent]:
        del project_id
        self.run_count += 1
        self.pending = False
        yield RunStartedEvent(thread_id=input_data.thread_id, run_id=input_data.run_id)
        yield RunFinishedEvent(thread_id=input_data.thread_id, run_id=input_data.run_id)


@pytest.mark.asyncio
async def test_run_lifecycle_is_durable_and_thread_scoped() -> None:
    execution = create_memory_agent_execution(DeterministicRunner())

    first_events = [
        event
        async for event in await execution.start(
            input_for("a", "run-1"), project_id="project", request_id="request-1"
        )
    ]
    second_events = [
        event
        async for event in await execution.start(
            input_for("b", "run-2"), project_id="project", request_id="request-2"
        )
    ]

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

    _ = [
        event
        async for event in await execution.start(
            input_data, project_id="project", request_id="request-1"
        )
    ]

    with pytest.raises(DuplicateAgentRun):
        await execution.start(input_data, project_id="project", request_id="request-2")


@pytest.mark.asyncio
async def test_only_one_run_can_be_active_for_a_thread() -> None:
    execution = create_memory_agent_execution(DeterministicRunner())

    _ = await execution.start(input_for("a", "run-1"), project_id="project", request_id="request-1")

    with pytest.raises(AgentRunAlreadyActive):
        await execution.start(input_for("a", "run-2"), project_id="project", request_id="request-2")


@pytest.mark.asyncio
async def test_failed_stream_updates_run_status() -> None:
    execution = create_memory_agent_execution(FailingRunner())

    with pytest.raises(RuntimeError, match="provider unavailable"):
        _ = [
            event
            async for event in await execution.start(
                input_for("a", "run-1"),
                project_id="project",
                request_id="request-1",
            )
        ]

    run = (await execution.list_runs("a"))[0]
    assert run.status is AgentRunStatus.FAILED
    assert run.error is not None
    assert run.error.code == "AGENT_RUN_FAILED"
    assert run.error.message == "provider unavailable"
    assert run.error.request_id.root == "request-1"
    assert run.error.retryable is True


@pytest.mark.asyncio
async def test_interrupt_is_a_durable_non_failure_outcome() -> None:
    execution = create_memory_agent_execution(InterruptingRunner())

    _ = [
        event
        async for event in await execution.start(
            input_for("a", "run-1"), project_id="project", request_id="request-1"
        )
    ]

    run = (await execution.list_runs("a"))[0]
    assert run.status is AgentRunStatus.INTERRUPTED
    assert run.error is None


@pytest.mark.asyncio
async def test_error_event_persists_the_shared_error_contract() -> None:
    execution = create_memory_agent_execution(ErrorEventRunner())

    _ = [
        event
        async for event in await execution.start(
            input_for("a", "run-1"), project_id="project", request_id="request-1"
        )
    ]

    run = (await execution.list_runs("a"))[0]
    assert run.status is AgentRunStatus.FAILED
    assert run.error is not None
    assert run.error.model_dump(mode="json", by_alias=True) == {
        "code": "MODEL_OVERLOADED",
        "message": "model overloaded",
        "requestId": "request-1",
        "retryable": True,
        "details": None,
    }


@pytest.mark.asyncio
async def test_cancelled_stream_updates_run_status() -> None:
    execution = create_memory_agent_execution(CancelledRunner())

    with pytest.raises(asyncio.CancelledError):
        _ = [
            event
            async for event in await execution.start(
                input_for("a", "run-1"),
                project_id="project",
                request_id="request-1",
            )
        ]

    run = (await execution.list_runs("a"))[0]
    assert run.status is AgentRunStatus.CANCELLED
    assert run.error is None


@pytest.mark.asyncio
async def test_closing_a_dropped_stream_updates_run_status() -> None:
    execution = create_memory_agent_execution(HangingRunner())
    stream = cast(
        AsyncGenerator[BaseEvent, None],
        await execution.start(
            input_for("a", "run-1"), project_id="project", request_id="request-1"
        ),
    )

    _ = await anext(stream)
    await stream.aclose()

    run = (await execution.list_runs("a"))[0]
    assert run.status is AgentRunStatus.CANCELLED


@pytest.mark.asyncio
async def test_resume_must_answer_current_interrupts_and_cannot_be_replayed() -> None:
    runner = ResumableRunner()
    execution = create_memory_agent_execution(runner)
    resume = [
        ResumeEntry(
            interrupt_id="approval-1",
            status="resolved",
            payload={"approved": True},
        )
    ]
    first_input = input_for("a", "resume-1").model_copy(update={"resume": resume})

    _ = [
        event
        async for event in await execution.start(
            first_input, project_id="project", request_id="request-1"
        )
    ]

    replay_input = input_for("a", "resume-2").model_copy(update={"resume": resume})
    with pytest.raises(InvalidAgentRunResume):
        await execution.start(replay_input, project_id="project", request_id="request-2")
    assert runner.run_count == 1


@pytest.mark.asyncio
async def test_restart_reconciles_non_terminal_runs_but_preserves_interrupts() -> None:
    running_execution = create_memory_agent_execution(DeterministicRunner())
    _ = await running_execution.start(
        input_for("a", "running-run"),
        project_id="project",
        request_id="running-request",
    )

    assert await running_execution.reconcile_non_terminal() == 1

    reconciled = (await running_execution.list_runs("a"))[0]
    assert reconciled.status is AgentRunStatus.FAILED
    assert reconciled.error is not None
    assert reconciled.error.code == "RUN_ABANDONED_ON_RESTART"
    assert reconciled.error.request_id.root == "running-request"

    interrupted_execution = create_memory_agent_execution(InterruptingRunner())
    _ = [
        event
        async for event in await interrupted_execution.start(
            input_for("b", "interrupted-run"),
            project_id="project",
            request_id="interrupted-request",
        )
    ]

    assert await interrupted_execution.reconcile_non_terminal() == 0
    interrupted = (await interrupted_execution.list_runs("b"))[0]
    assert interrupted.status is AgentRunStatus.INTERRUPTED
