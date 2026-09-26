import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import uuid4

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from agent_hub_api.modules.datasets import BatchDefinition, DatasetModule
from agent_hub_api.modules.plugin_gateway import PluginGatewayModule
from agent_hub_api.modules.projects import ProjectAccess, ProjectModule, ProjectNotFound
from agent_hub_api.settings import Settings


class BatchRunStatus(StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    partial = "partial"


class BatchRunOrder(StrEnum):
    newest = "newest"
    oldest = "oldest"


@dataclass(frozen=True, slots=True)
class ResultRecord:
    dataset_record_id: str
    input: Mapping[str, object]
    structured_output: Mapping[str, object] | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class BatchRun:
    id: str
    project_id: str
    definition_id: str
    status: BatchRunStatus
    definition_snapshot: Mapping[str, object]
    records: tuple[ResultRecord, ...]
    created_at: datetime
    updated_at: datetime
    idempotency_key: str | None = None
    initiator_subject: str | None = None


@dataclass(frozen=True, slots=True)
class BatchRunPage:
    items: tuple[BatchRun, ...]
    next_offset: int | None


class BatchRunNotFound(Exception):
    pass


class BatchRunStore(Protocol):
    async def create_or_load(self, run: BatchRun) -> tuple[BatchRun, bool]: ...
    async def load(self, project_id: str, run_id: str) -> BatchRun | None: ...
    async def delete(self, project_id: str, run_id: str) -> bool: ...
    async def list(
        self,
        project_id: str,
        definition_id: str | None = None,
        status: BatchRunStatus | None = None,
        order: BatchRunOrder = BatchRunOrder.newest,
        limit: int = 10,
        offset: int = 0,
    ) -> BatchRunPage: ...
    async def replace(self, run: BatchRun) -> BatchRun | None: ...
    async def reconcile_non_terminal(self, now: datetime) -> int: ...


class BatchExecutionModule:
    """Own one-record Batch Run persistence and repeat-safe MCP execution."""

    def __init__(
        self,
        projects: ProjectModule,
        datasets: DatasetModule,
        gateway: PluginGatewayModule,
        store: BatchRunStore,
        max_concurrency: int = 4,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least one")
        self._projects, self._datasets, self._gateway, self._store = (
            projects,
            datasets,
            gateway,
            store,
        )
        self._max_concurrency = max_concurrency

    async def start_one(
        self,
        access: ProjectAccess,
        project_id: str,
        definition_id: str,
        record_id: str,
        idempotency_key: str | None = None,
    ) -> BatchRun:
        await self._authorize(access, project_id)
        definition = await self._datasets.load_definition(access, project_id, definition_id)
        dataset = await self._datasets.load_dataset(access, project_id, definition.dataset_id)
        record = next((item for item in dataset.records if item.id == record_id), None)
        if record is None:
            raise BatchRunNotFound
        arguments = {
            name: _select(record.value, pointer)
            for name, pointer in definition.argument_mappings.items()
        }
        now = datetime.now(UTC)
        run = BatchRun(
            str(uuid4()),
            project_id,
            definition.id,
            BatchRunStatus.queued,
            _snapshot(definition),
            (ResultRecord(record.id, arguments),),
            now,
            now,
            idempotency_key,
            access.subject,
        )
        run, created = await self._store.create_or_load(run)
        if not created:
            return run
        running = replace(run, status=BatchRunStatus.running, updated_at=datetime.now(UTC))
        await self._store.replace(running)
        try:
            result = await self._gateway.batch_call(
                access, project_id, definition.plugin_id, definition.tool_name, arguments
            )
            if result.structured_content is None:
                raise ValueError("The tool returned no structured output.")
            completed = replace(
                running,
                status=BatchRunStatus.succeeded,
                records=(ResultRecord(record.id, arguments, result.structured_content),),
                updated_at=datetime.now(UTC),
            )
        except Exception as error:
            completed = replace(
                running,
                status=BatchRunStatus.failed,
                records=(ResultRecord(record.id, arguments, error=str(error)),),
                updated_at=datetime.now(UTC),
            )
        return await self._store.replace(completed) or completed

    async def start_all(
        self,
        access: ProjectAccess,
        project_id: str,
        definition_id: str,
        idempotency_key: str | None = None,
    ) -> BatchRun:
        """Execute a captured Dataset after its first record succeeds."""
        await self._authorize(access, project_id)
        definition = await self._datasets.load_definition(access, project_id, definition_id)
        dataset = await self._datasets.load_dataset(access, project_id, definition.dataset_id)
        if not dataset.records:
            raise BatchRunNotFound
        now = datetime.now(UTC)
        captured = tuple(
            (record.id, _arguments(record.value, definition)) for record in dataset.records
        )
        run = BatchRun(
            str(uuid4()),
            project_id,
            definition.id,
            BatchRunStatus.queued,
            {
                **_snapshot(definition),
                "maxConcurrency": self._max_concurrency,
                "recordIds": [record_id for record_id, _ in captured],
            },
            tuple(ResultRecord(record_id, arguments) for record_id, arguments in captured),
            now,
            now,
            idempotency_key,
            access.subject,
        )
        run, created = await self._store.create_or_load(run)
        if not created:
            return run
        running = replace(run, status=BatchRunStatus.running, updated_at=datetime.now(UTC))
        await self._store.replace(running)
        first_id, first_arguments = captured[0]
        first = await self._execute(access, project_id, definition, first_id, first_arguments)
        progress = replace(
            running,
            records=(first, *running.records[1:]),
            updated_at=datetime.now(UTC),
        )
        await self._store.replace(progress)
        if first.error:
            failed = replace(progress, status=BatchRunStatus.failed, updated_at=datetime.now(UTC))
            return await self._store.replace(failed) or failed
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def execute_bounded(
            record_id: str, arguments: Mapping[str, object]
        ) -> ResultRecord:
            async with semaphore:
                return await self._execute(
                    access, project_id, definition, record_id, arguments
                )

        remaining = await asyncio.gather(
            *(execute_bounded(record_id, arguments) for record_id, arguments in captured[1:])
        )
        completed = replace(
            progress,
            status=(
                BatchRunStatus.partial
                if any(record.error for record in remaining)
                else BatchRunStatus.succeeded
            ),
            records=(first, *remaining),
            updated_at=datetime.now(UTC),
        )
        return await self._store.replace(completed) or completed

    async def _execute(
        self,
        access: ProjectAccess,
        project_id: str,
        definition: BatchDefinition,
        record_id: str,
        arguments: Mapping[str, object],
    ) -> ResultRecord:
        try:
            result = await self._gateway.batch_call(
                access, project_id, definition.plugin_id, definition.tool_name, arguments
            )
            if result.structured_content is None:
                raise ValueError("The tool returned no structured output.")
            return ResultRecord(record_id, arguments, result.structured_content)
        except Exception as error:
            return ResultRecord(record_id, arguments, error=str(error))

    async def load(self, access: ProjectAccess, project_id: str, run_id: str) -> BatchRun:
        await self._authorize(access, project_id)
        run = await self._store.load(project_id, run_id)
        if run is None:
            raise BatchRunNotFound
        return run

    async def delete(self, access: ProjectAccess, project_id: str, run_id: str) -> None:
        await self._authorize(access, project_id)
        if not await self._store.delete(project_id, run_id):
            raise BatchRunNotFound

    async def list(
        self,
        access: ProjectAccess,
        project_id: str,
        definition_id: str | None = None,
        status: BatchRunStatus | None = None,
        order: BatchRunOrder = BatchRunOrder.newest,
        limit: int = 10,
        offset: int = 0,
    ) -> BatchRunPage:
        await self._authorize(access, project_id)
        return await self._store.list(
            project_id, definition_id, status, order, limit, offset
        )

    async def reconcile_non_terminal(self) -> int:
        """Make interrupted in-process work visible and safely retryable."""
        return await self._store.reconcile_non_terminal(datetime.now(UTC))

    async def _authorize(self, access: ProjectAccess, project_id: str) -> None:
        try:
            await self._projects.load(access, project_id)
        except ProjectNotFound as error:
            raise BatchRunNotFound from error


class MemoryBatchRunStore:
    def __init__(self) -> None:
        self._runs: dict[tuple[str, str], BatchRun] = {}
        self._idempotency_keys: dict[tuple[str, str], str] = {}

    async def create_or_load(self, run: BatchRun) -> tuple[BatchRun, bool]:
        if run.idempotency_key is not None:
            existing_id = self._idempotency_keys.get((run.project_id, run.idempotency_key))
            if existing_id is not None:
                return self._runs[(run.project_id, existing_id)], False
        self._runs[(run.project_id, run.id)] = run
        if run.idempotency_key is not None:
            self._idempotency_keys[(run.project_id, run.idempotency_key)] = run.id
        return run, True

    async def load(self, project_id: str, run_id: str) -> BatchRun | None:
        return self._runs.get((project_id, run_id))

    async def delete(self, project_id: str, run_id: str) -> bool:
        run = self._runs.pop((project_id, run_id), None)
        if run is None:
            return False
        if run.idempotency_key is not None:
            self._idempotency_keys.pop((project_id, run.idempotency_key), None)
        return True

    async def list(
        self,
        project_id: str,
        definition_id: str | None = None,
        status: BatchRunStatus | None = None,
        order: BatchRunOrder = BatchRunOrder.newest,
        limit: int = 10,
        offset: int = 0,
    ) -> BatchRunPage:
        runs = sorted(
            (
                run
                for (stored_project_id, _), run in self._runs.items()
                if stored_project_id == project_id
                and (definition_id is None or run.definition_id == definition_id)
                and (status is None or run.status is status)
            ),
            key=lambda run: run.updated_at,
            reverse=order is BatchRunOrder.newest,
        )
        items = tuple(runs[offset : offset + limit])
        next_offset = offset + len(items) if offset + len(items) < len(runs) else None
        return BatchRunPage(items, next_offset)

    async def replace(self, run: BatchRun) -> BatchRun | None:
        if (run.project_id, run.id) not in self._runs:
            return None
        self._runs[(run.project_id, run.id)] = run
        return run

    async def reconcile_non_terminal(self, now: datetime) -> int:
        runs = tuple(self._runs.items())
        reconciled = 0
        for key, run in runs:
            if run.status in {BatchRunStatus.queued, BatchRunStatus.running}:
                self._runs[key] = replace(
                    run, status=BatchRunStatus.failed, updated_at=now
                )
                reconciled += 1
        return reconciled


class PostgresBatchRunStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def _connect(self) -> AsyncConnection[dict[str, object]]:
        return await AsyncConnection.connect(
            str(self._settings.database_url),
            connect_timeout=self._settings.database_connect_timeout_seconds,
            row_factory=dict_row,
        )

    async def create_or_load(self, run: BatchRun) -> tuple[BatchRun, bool]:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """INSERT INTO batch_runs
                (project_id,batch_run_id,batch_definition_id,status,definition_snapshot,created_at,updated_at,idempotency_key,initiator_subject)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (project_id,idempotency_key)
                WHERE idempotency_key IS NOT NULL DO NOTHING
                RETURNING batch_run_id""",
                (
                    run.project_id,
                    run.id,
                    run.definition_id,
                    run.status.value,
                    json.dumps(run.definition_snapshot),
                    run.created_at,
                    run.updated_at,
                    run.idempotency_key,
                    run.initiator_subject,
                ),
            )
            if await cursor.fetchone() is not None:
                return run, True
            if run.idempotency_key is not None:
                cursor = await connection.execute(
                    """SELECT batch_run_id FROM batch_runs
                    WHERE project_id=%s AND idempotency_key=%s""",
                    (run.project_id, run.idempotency_key),
                )
                row = await cursor.fetchone()
                if row is not None:
                    existing = await _load(connection, run.project_id, str(row["batch_run_id"]))
                    if existing is not None:
                        return existing, False
            raise RuntimeError("Batch Run could not be created")

    async def load(self, project_id: str, run_id: str) -> BatchRun | None:
        connection = await self._connect()
        async with connection:
            return await _load(connection, project_id, run_id)

    async def delete(self, project_id: str, run_id: str) -> bool:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """DELETE FROM batch_runs WHERE project_id=%s AND batch_run_id=%s
                RETURNING batch_run_id""",
                (project_id, run_id),
            )
            return await cursor.fetchone() is not None

    async def list(
        self,
        project_id: str,
        definition_id: str | None = None,
        status: BatchRunStatus | None = None,
        order: BatchRunOrder = BatchRunOrder.newest,
        limit: int = 10,
        offset: int = 0,
    ) -> BatchRunPage:
        connection = await self._connect()
        async with connection:
            clauses = ["project_id=%s"]
            parameters: list[object] = [project_id]
            if definition_id is not None:
                clauses.append("batch_definition_id=%s")
                parameters.append(definition_id)
            if status is not None:
                clauses.append("status=%s")
                parameters.append(status.value)
            direction = "DESC" if order is BatchRunOrder.newest else "ASC"
            cursor = await connection.execute(
                f"""SELECT batch_run_id FROM batch_runs WHERE {' AND '.join(clauses)}
                ORDER BY updated_at {direction} LIMIT %s OFFSET %s""",
                (*parameters, limit + 1, offset),
            )
            rows = await cursor.fetchall()
            runs: list[BatchRun] = []
            for row in rows[:limit]:
                run = await _load(connection, project_id, str(row["batch_run_id"]))
                if run is not None:
                    runs.append(run)
            return BatchRunPage(
                tuple(runs), offset + limit if len(rows) > limit else None
            )

    async def replace(self, run: BatchRun) -> BatchRun | None:
        connection = await self._connect()
        async with connection:
            if await _load(connection, run.project_id, run.id) is None:
                return None
            await _save(connection, run, True)
        return run

    async def reconcile_non_terminal(self, now: datetime) -> int:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """UPDATE batch_runs SET status='failed', updated_at=%s
                WHERE status IN ('queued', 'running')""",
                (now,),
            )
            return cursor.rowcount


async def _save(
    connection: AsyncConnection[dict[str, object]], run: BatchRun, replace_run: bool
) -> None:
    if replace_run:
        await connection.execute(
            """UPDATE batch_runs SET status=%s, definition_snapshot=%s, updated_at=%s
            WHERE project_id=%s AND batch_run_id=%s""",
            (
                run.status.value,
                json.dumps(run.definition_snapshot),
                run.updated_at,
                run.project_id,
                run.id,
            ),
        )
        await connection.execute(
            "DELETE FROM batch_result_records WHERE project_id=%s AND batch_run_id=%s",
            (run.project_id, run.id),
        )
    else:
        await connection.execute(
            """INSERT INTO batch_runs
            (project_id,batch_run_id,batch_definition_id,status,definition_snapshot,created_at,updated_at,idempotency_key,initiator_subject)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                run.project_id,
                run.id,
                run.definition_id,
                run.status.value,
                json.dumps(run.definition_snapshot),
                run.created_at,
                run.updated_at,
                run.idempotency_key,
                run.initiator_subject,
            ),
        )
    for record in run.records:
        await connection.execute(
            """INSERT INTO batch_result_records
            (project_id,batch_run_id,dataset_record_id,input,structured_output,error)
            VALUES (%s,%s,%s,%s,%s,%s)""",
            (
                run.project_id,
                run.id,
                record.dataset_record_id,
                json.dumps(record.input),
                json.dumps(record.structured_output) if record.structured_output else None,
                record.error,
            ),
        )


async def _load(
    connection: AsyncConnection[dict[str, object]], project_id: str, run_id: str
) -> BatchRun | None:
    cursor = await connection.execute(
        "SELECT * FROM batch_runs WHERE project_id=%s AND batch_run_id=%s", (project_id, run_id)
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    cursor = await connection.execute(
        "SELECT * FROM batch_result_records WHERE project_id=%s AND batch_run_id=%s",
        (project_id, run_id),
    )
    records = tuple(
        ResultRecord(
            str(item["dataset_record_id"]),
            _obj(item["input"]),
            _obj(item["structured_output"]) if item["structured_output"] is not None else None,
            str(item["error"]) if item["error"] else None,
        )
        for item in await cursor.fetchall()
    )
    return BatchRun(
        str(row["batch_run_id"]),
        project_id,
        str(row["batch_definition_id"]),
        BatchRunStatus(str(row["status"])),
        _obj(row["definition_snapshot"]),
        records,
        row["created_at"],
        row["updated_at"],
        str(row["idempotency_key"]) if row["idempotency_key"] is not None else None,
        str(row["initiator_subject"]) if row["initiator_subject"] is not None else None,
    )


def _obj(value: object) -> Mapping[str, object]:
    return json.loads(value) if isinstance(value, str) else dict(value)  # type: ignore[arg-type]


def _select(value: Mapping[str, object], pointer: str) -> object:
    current: object = value
    for token in pointer[1:].split("/"):
        if not isinstance(current, Mapping):
            raise ValueError("Mapping no longer identifies a value.")
        current = current[token.replace("~1", "/").replace("~0", "~")]
    return current


def _arguments(value: Mapping[str, object], definition: BatchDefinition) -> Mapping[str, object]:
    return {name: _select(value, pointer) for name, pointer in definition.argument_mappings.items()}


def _snapshot(definition: BatchDefinition) -> Mapping[str, object]:
    return {
        "datasetId": definition.dataset_id,
        "pluginId": definition.plugin_id,
        "toolName": definition.tool_name,
        "argumentMappings": definition.argument_mappings,
        "inputSchema": definition.input_schema,
    }


def create_postgres_batch_execution_module(
    settings: Settings,
    projects: ProjectModule,
    datasets: DatasetModule,
    gateway: PluginGatewayModule,
) -> BatchExecutionModule:
    return BatchExecutionModule(projects, datasets, gateway, PostgresBatchRunStore(settings))
