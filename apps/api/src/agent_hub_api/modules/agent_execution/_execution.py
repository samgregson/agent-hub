import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from ag_ui.core import BaseEvent, Interrupt, Message, RunAgentInput, RunErrorEvent, RunFinishedEvent
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from agent_hub_api.contracts import ErrorEnvelope
from agent_hub_api.settings import Settings


class AgentRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    INTERRUPTED = "interrupted"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class AgentRun:
    id: str
    thread_id: str
    request_id: str
    status: AgentRunStatus
    created_at: datetime
    updated_at: datetime
    error: ErrorEnvelope | None = None


@dataclass(frozen=True, slots=True)
class AgentThreadState:
    messages: tuple[Message, ...]
    interrupts: tuple[Interrupt, ...]


@dataclass(frozen=True, slots=True)
class ScratchFile:
    """A Thread-local Deep Agents file safe to present back to its owner."""

    path: str
    content: str


class ScratchFileNotFound(Exception):
    """The requested Thread-local scratch file is unavailable."""


class DuplicateAgentRun(Exception):
    """The client supplied a Run ID which already belongs to a durable Run."""


class AgentRunAlreadyActive(Exception):
    """Another Run is already active for the Thread."""


class InvalidAgentRunResume(Exception):
    """Resume entries do not exactly answer the Thread's pending interrupts."""


class CreateAgentRunResult(StrEnum):
    CREATED = "created"
    DUPLICATE = "duplicate"
    THREAD_ACTIVE = "thread_active"


class AgentRunner(Protocol):
    def run(
        self, input_data: RunAgentInput, *, project_id: str, subject: str | None = None
    ) -> AsyncIterator[BaseEvent]: ...

    async def load_thread_state(self, thread_id: str, *, project_id: str) -> AgentThreadState: ...

    async def load_scratch_file(
        self, thread_id: str, *, project_id: str, path: str
    ) -> ScratchFile: ...


class AgentRunStore(Protocol):
    async def create(self, run: AgentRun) -> CreateAgentRunResult: ...

    async def update(self, run: AgentRun) -> None: ...

    async def list(self, thread_id: str) -> tuple[AgentRun, ...]: ...

    async def reconcile_non_terminal(self, *, now: datetime) -> int: ...


class AgentExecutionModule:
    """Owns durable Run lifecycle around a replaceable AG-UI event producer."""

    def __init__(self, runner: AgentRunner, store: AgentRunStore) -> None:
        self._runner = runner
        self._store = store

    async def start(
        self,
        input_data: RunAgentInput,
        *,
        project_id: str,
        request_id: str,
        subject: str | None = None,
    ) -> AsyncIterator[BaseEvent]:
        if input_data.resume:
            thread_state = await self._runner.load_thread_state(
                input_data.thread_id, project_id=project_id
            )
            expected = {interrupt.id for interrupt in thread_state.interrupts}
            supplied = [entry.interrupt_id for entry in input_data.resume]
            if len(supplied) != len(set(supplied)) or set(supplied) != expected:
                raise InvalidAgentRunResume
        now = datetime.now(UTC)
        run = AgentRun(
            id=input_data.run_id,
            thread_id=input_data.thread_id,
            request_id=request_id,
            status=AgentRunStatus.RUNNING,
            created_at=now,
            updated_at=now,
        )
        create_result = await self._store.create(run)
        if create_result is CreateAgentRunResult.DUPLICATE:
            raise DuplicateAgentRun
        if create_result is CreateAgentRunResult.THREAD_ACTIVE:
            raise AgentRunAlreadyActive
        return self._stream(run, input_data, project_id, request_id, subject)

    async def _stream(
        self,
        run: AgentRun,
        input_data: RunAgentInput,
        project_id: str,
        request_id: str,
        subject: str | None,
    ) -> AsyncIterator[BaseEvent]:
        terminal_status = AgentRunStatus.SUCCEEDED
        terminal_error: ErrorEnvelope | None = None
        try:
            events = self._runner.run(input_data, project_id=project_id)
            if subject is not None:
                events = self._runner.run(input_data, project_id=project_id, subject=subject)
            async for event in events:
                if isinstance(event, RunErrorEvent):
                    terminal_status = AgentRunStatus.FAILED
                    terminal_error = ErrorEnvelope.model_validate(
                        {
                            "code": event.code or "AGENT_RUN_FAILED",
                            "message": event.message,
                            "requestId": request_id,
                            "retryable": True,
                        }
                    )
                elif isinstance(event, RunFinishedEvent) and event.outcome is not None:
                    outcome = event.outcome
                    if getattr(outcome, "type", None) == "interrupt":
                        terminal_status = AgentRunStatus.INTERRUPTED
                yield event
        except (asyncio.CancelledError, GeneratorExit):
            await self._persist_cancelled(run)
            raise
        except Exception as error:
            failed = replace(
                run,
                status=AgentRunStatus.FAILED,
                updated_at=datetime.now(UTC),
                error=ErrorEnvelope.model_validate(
                    {
                        "code": "AGENT_RUN_FAILED",
                        "message": str(error) or error.__class__.__name__,
                        "requestId": request_id,
                        "retryable": True,
                    }
                ),
            )
            await self._store.update(failed)
            raise
        else:
            await self._store.update(
                replace(
                    run,
                    status=terminal_status,
                    updated_at=datetime.now(UTC),
                    error=terminal_error,
                )
            )

    async def _persist_cancelled(self, run: AgentRun) -> None:
        update = asyncio.create_task(
            self._store.update(
                replace(
                    run,
                    status=AgentRunStatus.CANCELLED,
                    updated_at=datetime.now(UTC),
                )
            )
        )
        try:
            await asyncio.shield(update)
        except asyncio.CancelledError:
            await update

    async def reconcile_non_terminal(self) -> int:
        return await self._store.reconcile_non_terminal(now=datetime.now(UTC))

    async def list_runs(self, thread_id: str) -> tuple[AgentRun, ...]:
        return await self._store.list(thread_id)

    async def load_thread_state(self, thread_id: str, *, project_id: str) -> AgentThreadState:
        return await self._runner.load_thread_state(thread_id, project_id=project_id)

    async def load_scratch_file(self, thread_id: str, *, project_id: str, path: str) -> ScratchFile:
        return await self._runner.load_scratch_file(thread_id, project_id=project_id, path=path)


class MemoryAgentRunStore:
    def __init__(self) -> None:
        self._runs: dict[str, AgentRun] = {}

    async def create(self, run: AgentRun) -> CreateAgentRunResult:
        if run.id in self._runs:
            return CreateAgentRunResult.DUPLICATE
        if any(
            existing.thread_id == run.thread_id
            and existing.status
            in {AgentRunStatus.QUEUED, AgentRunStatus.RUNNING, AgentRunStatus.CANCELLING}
            for existing in self._runs.values()
        ):
            return CreateAgentRunResult.THREAD_ACTIVE
        self._runs[run.id] = run
        return CreateAgentRunResult.CREATED

    async def update(self, run: AgentRun) -> None:
        self._runs[run.id] = run

    async def list(self, thread_id: str) -> tuple[AgentRun, ...]:
        runs = (run for run in self._runs.values() if run.thread_id == thread_id)
        return tuple(sorted(runs, key=lambda run: run.updated_at, reverse=True))

    async def reconcile_non_terminal(self, *, now: datetime) -> int:
        count = 0
        for run_id, run in tuple(self._runs.items()):
            if run.status is AgentRunStatus.CANCELLING:
                self._runs[run_id] = replace(run, status=AgentRunStatus.CANCELLED, updated_at=now)
                count += 1
            elif run.status in {AgentRunStatus.QUEUED, AgentRunStatus.RUNNING}:
                self._runs[run_id] = replace(
                    run,
                    status=AgentRunStatus.FAILED,
                    updated_at=now,
                    error=_restart_error(run),
                )
                count += 1
        return count


class PostgresAgentRunStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def _connect(self) -> AsyncConnection[dict[str, object]]:
        return await AsyncConnection.connect(
            str(self._settings.database_url),
            connect_timeout=self._settings.database_connect_timeout_seconds,
            row_factory=dict_row,
        )

    @staticmethod
    def _serialized_error(error: ErrorEnvelope | None) -> Jsonb | None:
        if error is None:
            return None
        return Jsonb(error.model_dump(mode="json", by_alias=True))

    async def create(self, run: AgentRun) -> CreateAgentRunResult:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """
                INSERT INTO agent_runs
                    (id, thread_id, request_id, status, created_at, updated_at, error)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING id
                """,
                (
                    run.id,
                    run.thread_id,
                    run.request_id,
                    run.status.value,
                    run.created_at,
                    run.updated_at,
                    self._serialized_error(run.error),
                ),
            )
            if await cursor.fetchone() is not None:
                return CreateAgentRunResult.CREATED
            duplicate = await connection.execute(
                "SELECT 1 FROM agent_runs WHERE id = %s",
                (run.id,),
            )
            if await duplicate.fetchone() is not None:
                return CreateAgentRunResult.DUPLICATE
            return CreateAgentRunResult.THREAD_ACTIVE

    async def update(self, run: AgentRun) -> None:
        connection = await self._connect()
        async with connection:
            await connection.execute(
                """
                UPDATE agent_runs
                SET status = %s, updated_at = %s, error = %s
                WHERE id = %s
                """,
                (
                    run.status.value,
                    run.updated_at,
                    self._serialized_error(run.error),
                    run.id,
                ),
            )

    async def list(self, thread_id: str) -> tuple[AgentRun, ...]:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """
                SELECT id, thread_id, request_id, status, created_at, updated_at, error
                FROM agent_runs
                WHERE thread_id = %s
                ORDER BY updated_at DESC, id
                """,
                (thread_id,),
            )
            return tuple(
                AgentRun(
                    id=str(row["id"]),
                    thread_id=str(row["thread_id"]),
                    request_id=str(row["request_id"]),
                    status=AgentRunStatus(str(row["status"])),
                    created_at=row["created_at"],  # type: ignore[arg-type]
                    updated_at=row["updated_at"],  # type: ignore[arg-type]
                    error=(
                        None if row["error"] is None else ErrorEnvelope.model_validate(row["error"])
                    ),
                )
                for row in await cursor.fetchall()
            )

    async def reconcile_non_terminal(self, *, now: datetime) -> int:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """
                UPDATE agent_runs
                SET status = CASE
                        WHEN status = 'cancelling' THEN 'cancelled'
                        ELSE 'failed'
                    END,
                    updated_at = %s,
                    error = CASE
                        WHEN status = 'cancelling' THEN NULL
                        ELSE json_build_object(
                            'code', 'RUN_ABANDONED_ON_RESTART',
                            'message', 'The API restarted before the Run reached a terminal state.',
                            'requestId', request_id,
                            'retryable', true,
                            'details', NULL
                        )
                    END
                WHERE status IN ('queued', 'running', 'cancelling')
                """,
                (now,),
            )
            return cursor.rowcount


def _restart_error(run: AgentRun) -> ErrorEnvelope:
    return ErrorEnvelope.model_validate(
        {
            "code": "RUN_ABANDONED_ON_RESTART",
            "message": "The API restarted before the Run reached a terminal state.",
            "requestId": run.request_id,
            "retryable": True,
        }
    )


def create_memory_agent_execution(runner: AgentRunner) -> AgentExecutionModule:
    return AgentExecutionModule(runner, MemoryAgentRunStore())


def create_postgres_agent_execution(
    settings: Settings, runner: AgentRunner
) -> AgentExecutionModule:
    return AgentExecutionModule(runner, PostgresAgentRunStore(settings))
