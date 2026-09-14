from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from ag_ui.core import BaseEvent, Message, RunAgentInput, RunErrorEvent, RunFinishedEvent
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from agent_hub_api.contracts import ErrorEnvelope
from agent_hub_api.settings import Settings


class AgentRunStatus(StrEnum):
    RUNNING = "running"
    INTERRUPTED = "interrupted"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class AgentRun:
    id: str
    thread_id: str
    status: AgentRunStatus
    created_at: datetime
    updated_at: datetime
    error: ErrorEnvelope | None = None


class DuplicateAgentRun(Exception):
    """The client supplied a Run ID which already belongs to a durable Run."""


class AgentRunner(Protocol):
    def run(self, input_data: RunAgentInput) -> AsyncIterator[BaseEvent]: ...

    async def load_messages(self, thread_id: str) -> tuple[Message, ...]: ...


class AgentRunStore(Protocol):
    async def create(self, run: AgentRun) -> bool: ...

    async def update(self, run: AgentRun) -> None: ...

    async def list(self, thread_id: str) -> tuple[AgentRun, ...]: ...


class AgentExecutionModule:
    """Owns durable Run lifecycle around a replaceable AG-UI event producer."""

    def __init__(self, runner: AgentRunner, store: AgentRunStore) -> None:
        self._runner = runner
        self._store = store

    async def start(
        self, input_data: RunAgentInput, *, request_id: str
    ) -> AsyncIterator[BaseEvent]:
        now = datetime.now(UTC)
        run = AgentRun(
            id=input_data.run_id,
            thread_id=input_data.thread_id,
            status=AgentRunStatus.RUNNING,
            created_at=now,
            updated_at=now,
        )
        if not await self._store.create(run):
            raise DuplicateAgentRun
        return self._stream(run, input_data, request_id)

    async def _stream(
        self, run: AgentRun, input_data: RunAgentInput, request_id: str
    ) -> AsyncIterator[BaseEvent]:
        terminal_status = AgentRunStatus.SUCCEEDED
        terminal_error: ErrorEnvelope | None = None
        try:
            async for event in self._runner.run(input_data):
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

    async def list_runs(self, thread_id: str) -> tuple[AgentRun, ...]:
        return await self._store.list(thread_id)

    async def load_messages(self, thread_id: str) -> tuple[Message, ...]:
        return await self._runner.load_messages(thread_id)


class MemoryAgentRunStore:
    def __init__(self) -> None:
        self._runs: dict[str, AgentRun] = {}

    async def create(self, run: AgentRun) -> bool:
        if run.id in self._runs:
            return False
        self._runs[run.id] = run
        return True

    async def update(self, run: AgentRun) -> None:
        self._runs[run.id] = run

    async def list(self, thread_id: str) -> tuple[AgentRun, ...]:
        runs = (run for run in self._runs.values() if run.thread_id == thread_id)
        return tuple(sorted(runs, key=lambda run: run.updated_at, reverse=True))


class PostgresAgentRunStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def _connect(self) -> AsyncConnection[dict[str, object]]:
        return await AsyncConnection.connect(
            str(self._settings.database_url),
            connect_timeout=self._settings.database_connect_timeout_seconds,
            row_factory=dict_row,
        )

    async def create(self, run: AgentRun) -> bool:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """
                INSERT INTO agent_runs
                    (id, thread_id, status, created_at, updated_at, error)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                RETURNING id
                """,
                (
                    run.id,
                    run.thread_id,
                    run.status.value,
                    run.created_at,
                    run.updated_at,
                    None if run.error is None else run.error.model_dump(mode="json", by_alias=True),
                ),
            )
            return await cursor.fetchone() is not None

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
                    None if run.error is None else run.error.model_dump(mode="json", by_alias=True),
                    run.id,
                ),
            )

    async def list(self, thread_id: str) -> tuple[AgentRun, ...]:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """
                SELECT id, thread_id, status, created_at, updated_at, error
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
                    status=AgentRunStatus(str(row["status"])),
                    created_at=row["created_at"],  # type: ignore[arg-type]
                    updated_at=row["updated_at"],  # type: ignore[arg-type]
                    error=(
                        None if row["error"] is None else ErrorEnvelope.model_validate(row["error"])
                    ),
                )
                for row in await cursor.fetchall()
            )


def create_memory_agent_execution(runner: AgentRunner) -> AgentExecutionModule:
    return AgentExecutionModule(runner, MemoryAgentRunStore())


def create_postgres_agent_execution(
    settings: Settings, runner: AgentRunner
) -> AgentExecutionModule:
    return AgentExecutionModule(runner, PostgresAgentRunStore(settings))
