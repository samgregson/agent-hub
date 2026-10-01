import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import uuid4

from jsonschema import Draft202012Validator
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
    archived_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class BatchRunPage:
    items: tuple[BatchRun, ...]
    next_offset: int | None


@dataclass(frozen=True, slots=True)
class ResultRecordPage:
    items: tuple[ResultRecord, ...]
    next_offset: int | None
    summary: "ResultSummary"


@dataclass(frozen=True, slots=True)
class ResultSummary:
    total_count: int
    succeeded_count: int
    failed_count: int
    numeric_count: int = 0
    numeric_sum: float | None = None
    numeric_min: float | None = None
    numeric_max: float | None = None
    numeric_average: float | None = None


class BatchRunNotFound(Exception):
    pass


class BatchRunNotArchivable(Exception):
    """A non-terminal Batch Run cannot be archived."""


class BatchRunStore(Protocol):
    async def create_or_load(self, run: BatchRun) -> tuple[BatchRun, bool]: ...
    async def load(self, project_id: str, run_id: str) -> BatchRun | None: ...
    async def list(
        self,
        project_id: str,
        definition_id: str | None = None,
        status: BatchRunStatus | None = None,
        order: BatchRunOrder = BatchRunOrder.newest,
        limit: int = 10,
        offset: int = 0,
        include_archived: bool = False,
    ) -> BatchRunPage: ...
    async def replace(self, run: BatchRun) -> BatchRun | None: ...
    async def reconcile_non_terminal(self, now: datetime) -> int: ...
    async def non_terminal(self) -> tuple[BatchRun, ...]: ...


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
        self._tasks: dict[tuple[str, str], asyncio.Task[BatchRun]] = {}

    async def start_one(
        self,
        access: ProjectAccess,
        project_id: str,
        definition_id: str,
        record_id: str,
        idempotency_key: str | None = None,
    ) -> BatchRun:
        run = await self.submit_one(access, project_id, definition_id, record_id, idempotency_key)
        return await self.execute(access, project_id, run.id)

    async def submit_one(
        self,
        access: ProjectAccess,
        project_id: str,
        definition_id: str,
        record_id: str,
        idempotency_key: str | None = None,
    ) -> BatchRun:
        await self._authorize(access, project_id)
        definition = await self._datasets.load_definition(access, project_id, definition_id)
        output_schema = await self._gateway.output_schema(
            access, project_id, definition.plugin_id, definition.tool_name
        )
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
            _snapshot(definition, output_schema),
            (ResultRecord(record.id, arguments),),
            now,
            now,
            idempotency_key,
            access.subject,
        )
        run, created = await self._store.create_or_load(run)
        return run

    async def start_all(
        self,
        access: ProjectAccess,
        project_id: str,
        definition_id: str,
        idempotency_key: str | None = None,
    ) -> BatchRun:
        run = await self.submit_all(access, project_id, definition_id, idempotency_key)
        return await self.execute(access, project_id, run.id)

    async def submit_all(
        self,
        access: ProjectAccess,
        project_id: str,
        definition_id: str,
        idempotency_key: str | None = None,
    ) -> BatchRun:
        """Execute a captured Dataset after its first record succeeds."""
        await self._authorize(access, project_id)
        definition = await self._datasets.load_definition(access, project_id, definition_id)
        output_schema = await self._gateway.output_schema(
            access, project_id, definition.plugin_id, definition.tool_name
        )
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
                **_snapshot(definition, output_schema),
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
        return run

    async def execute(self, access: ProjectAccess, project_id: str, run_id: str) -> BatchRun:
        run = await self.load(access, project_id, run_id)
        if run.status not in {BatchRunStatus.queued, BatchRunStatus.running}:
            return run
        running = replace(run, status=BatchRunStatus.running, updated_at=datetime.now(UTC))
        await self._store.replace(running)
        first = running.records[0]
        if first.structured_output is None and first.error is None:
            first = await self._execute_snapshot(access, project_id, running, first)
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

        async def execute_bounded(record: ResultRecord) -> ResultRecord:
            async with semaphore:
                return await self._execute_snapshot(access, project_id, running, record)

        pending = tuple(
            record
            for record in running.records[1:]
            if record.structured_output is None and record.error is None
        )
        executed = await asyncio.gather(*(execute_bounded(record) for record in pending))
        completed_records = {record.dataset_record_id: record for record in executed}
        remaining = tuple(
            completed_records.get(record.dataset_record_id, record)
            for record in running.records[1:]
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

    async def enqueue(
        self, access: ProjectAccess, project_id: str, run_id: str
    ) -> asyncio.Task[BatchRun]:
        """Schedule one durable Batch Run once within this host process."""
        await self.load(access, project_id, run_id)
        key = (project_id, run_id)
        task = self._tasks.get(key)
        if task is not None and not task.done():
            return task
        task = asyncio.create_task(self.execute(access, project_id, run_id))
        self._tasks[key] = task
        task.add_done_callback(lambda _: self._tasks.pop(key, None))
        return task

    async def _execute_snapshot(
        self, access: ProjectAccess, project_id: str, run: BatchRun, record: ResultRecord
    ) -> ResultRecord:
        try:
            result = await self._gateway.batch_call(
                access,
                project_id,
                str(run.definition_snapshot["pluginId"]),
                str(run.definition_snapshot["toolName"]),
                record.input,
            )
            if result.structured_content is None:
                raise ValueError("The tool returned no structured output.")
            output_schema = run.definition_snapshot.get("outputSchema")
            if not isinstance(output_schema, Mapping):
                raise ValueError("The Batch Run has no declared MCP output schema.")
            Draft202012Validator(output_schema).validate(result.structured_content)
            return ResultRecord(record.dataset_record_id, record.input, result.structured_content)
        except Exception as error:
            return ResultRecord(record.dataset_record_id, record.input, error=str(error))

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

    async def archive(self, access: ProjectAccess, project_id: str, run_id: str) -> BatchRun:
        """Hide one completed Batch Run without erasing its Result Set."""
        run = await self.load(access, project_id, run_id)
        if run.status in {BatchRunStatus.queued, BatchRunStatus.running}:
            raise BatchRunNotArchivable
        if run.archived_at is not None:
            return run
        archived = replace(run, archived_at=datetime.now(UTC))
        return await self._store.replace(archived) or archived

    async def inspect_results(
        self,
        access: ProjectAccess,
        project_id: str,
        run_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
        filter_path: str | None = None,
        equals: str | int | float | bool | None = None,
        minimum: int | float | None = None,
        maximum: int | float | None = None,
        sort_path: str | None = None,
        descending: bool = False,
        aggregate_path: str | None = None,
    ) -> ResultRecordPage:
        """Read one bounded page from a durable Result Set."""
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError(
                "Result Set pagination requires a limit from 1 to 100 and an offset >= 0."
            )
        run = await self.load(access, project_id, run_id)
        if (equals is not None or minimum is not None or maximum is not None) and not filter_path:
            raise ValueError("A filter path is required for scalar comparisons.")
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValueError("Minimum cannot exceed maximum.")
        if filter_path is not None:
            _validate_result_path(filter_path)
        if sort_path is not None:
            _validate_result_path(sort_path)
        if aggregate_path is not None:
            _validate_result_path(aggregate_path)
        records = [
            record for record in run.records
            if filter_path is None or _matches_result(record, filter_path, equals, minimum, maximum)
        ]
        if sort_path is not None:
            records.sort(
                key=lambda record: _sort_value(_result_value(record, sort_path)),
                reverse=descending,
            )
            records.sort(key=lambda record: _result_value(record, sort_path) is None)
        items = tuple(records[offset : offset + limit])
        next_offset = offset + len(items) if offset + len(items) < len(records) else None
        values = [
            value for record in records
            if aggregate_path is not None
            if (value := _result_value(record, aggregate_path)) is not None
            and not isinstance(value, bool) and isinstance(value, (int, float))
        ]
        total = sum(values) if values else None
        return ResultRecordPage(
            items, next_offset,
            ResultSummary(
                total_count=len(records),
                succeeded_count=sum(record.structured_output is not None for record in records),
                failed_count=sum(record.error is not None for record in records),
                numeric_count=len(values),
                numeric_sum=total,
                numeric_min=min(values) if values else None,
                numeric_max=max(values) if values else None,
                numeric_average=total / len(values) if total is not None else None,
            ),
        )

    async def list(
        self,
        access: ProjectAccess,
        project_id: str,
        definition_id: str | None = None,
        status: BatchRunStatus | None = None,
        order: BatchRunOrder = BatchRunOrder.newest,
        limit: int = 10,
        offset: int = 0,
        include_archived: bool = False,
    ) -> BatchRunPage:
        await self._authorize(access, project_id)
        return await self._store.list(
            project_id, definition_id, status, order, limit, offset, include_archived
        )

    async def reconcile_non_terminal(self) -> int:
        """Make interrupted in-process work visible and safely retryable."""
        return await self._store.reconcile_non_terminal(datetime.now(UTC))

    async def recoverable(self) -> tuple[BatchRun, ...]:
        """Return durable work that a new process can safely reclaim."""
        return tuple(
            run for run in await self._store.non_terminal() if run.initiator_subject is not None
        )

    async def recover(self) -> tuple[asyncio.Task[BatchRun], ...]:
        """Schedule durable non-terminal runs after a host restart."""
        tasks: list[asyncio.Task[BatchRun]] = []
        for run in await self.recoverable():
            assert run.initiator_subject is not None
            tasks.append(
                await self.enqueue(
                    ProjectAccess(subject=run.initiator_subject), run.project_id, run.id
                )
            )
        return tuple(tasks)

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

    async def list(
        self,
        project_id: str,
        definition_id: str | None = None,
        status: BatchRunStatus | None = None,
        order: BatchRunOrder = BatchRunOrder.newest,
        limit: int = 10,
        offset: int = 0,
        include_archived: bool = False,
    ) -> BatchRunPage:
        runs = sorted(
            (
                run
                for (stored_project_id, _), run in self._runs.items()
                if stored_project_id == project_id
                and (definition_id is None or run.definition_id == definition_id)
                and (status is None or run.status is status)
                and (include_archived or run.archived_at is None)
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

    async def non_terminal(self) -> tuple[BatchRun, ...]:
        return tuple(
            run
            for run in self._runs.values()
            if run.status in {BatchRunStatus.queued, BatchRunStatus.running}
        )


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
                await _insert_result_records(connection, run)
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

    async def list(
        self,
        project_id: str,
        definition_id: str | None = None,
        status: BatchRunStatus | None = None,
        order: BatchRunOrder = BatchRunOrder.newest,
        limit: int = 10,
        offset: int = 0,
        include_archived: bool = False,
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
            if not include_archived:
                clauses.append("archived_at IS NULL")
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

    async def non_terminal(self) -> tuple[BatchRun, ...]:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """SELECT project_id, batch_run_id FROM batch_runs
                WHERE status IN ('queued', 'running')"""
            )
            runs: list[BatchRun] = []
            for row in await cursor.fetchall():
                run = await _load(connection, str(row["project_id"]), str(row["batch_run_id"]))
                if run is not None:
                    runs.append(run)
            return tuple(runs)


async def _save(
    connection: AsyncConnection[dict[str, object]], run: BatchRun, replace_run: bool
) -> None:
    if replace_run:
        await connection.execute(
            """UPDATE batch_runs
            SET status=%s, definition_snapshot=%s, updated_at=%s, archived_at=%s
            WHERE project_id=%s AND batch_run_id=%s""",
            (
                run.status.value,
                json.dumps(run.definition_snapshot),
                run.updated_at,
                run.archived_at,
                run.project_id,
                run.id,
            ),
        )
        for record in run.records:
            await connection.execute(
                """UPDATE batch_result_records
                SET structured_output=%s, error=%s
                WHERE project_id=%s AND batch_run_id=%s AND dataset_record_id=%s""",
                (
                    json.dumps(record.structured_output) if record.structured_output else None,
                    record.error,
                    run.project_id,
                    run.id,
                    record.dataset_record_id,
                ),
            )
    else:
        await connection.execute(
            """INSERT INTO batch_runs
            (project_id,batch_run_id,batch_definition_id,status,definition_snapshot,created_at,updated_at,idempotency_key,initiator_subject,archived_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
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
                run.archived_at,
            ),
        )
        await _insert_result_records(connection, run)


async def _insert_result_records(
    connection: AsyncConnection[dict[str, object]], run: BatchRun
) -> None:
    for position, record in enumerate(run.records):
        await connection.execute(
            """INSERT INTO batch_result_records
            (project_id,batch_run_id,dataset_record_id,position,input,structured_output,error)
            VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (
                run.project_id,
                run.id,
                record.dataset_record_id,
                position,
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
        """SELECT * FROM batch_result_records WHERE project_id=%s AND batch_run_id=%s
        ORDER BY position, dataset_record_id""",
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
        row["archived_at"],  # type: ignore[arg-type]
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


def _validate_result_path(path: str) -> None:
    if not (path.startswith(("/input/", "/structuredOutput/")) or path == "/error"):
        raise ValueError("Result paths must select input, structuredOutput, or error.")


def _result_value(record: ResultRecord, path: str) -> object | None:
    parts = path[1:].split("/")
    value: object = {
        "input": record.input,
        "structuredOutput": record.structured_output,
        "error": record.error,
    }[parts[0]]
    for part in parts[1:]:
        if not isinstance(value, Mapping):
            return None
        value = value.get(part.replace("~1", "/").replace("~0", "~"))
    return value if isinstance(value, (str, int, float, bool)) else None


def _matches_result(
    record: ResultRecord,
    path: str,
    equals: str | int | float | bool | None,
    minimum: int | float | None,
    maximum: int | float | None,
) -> bool:
    value = _result_value(record, path)
    if value is None:
        return False
    same_numeric_type = (
        not isinstance(value, bool) and not isinstance(equals, bool)
        and isinstance(value, (int, float)) and isinstance(equals, (int, float))
    )
    if equals is not None and not (same_numeric_type or type(value) is type(equals)):
        return False
    if equals is not None and value != equals:
        return False
    if minimum is not None or maximum is not None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        if minimum is not None and value < minimum:
            return False
        if maximum is not None and value > maximum:
            return False
    return True


def _sort_value(value: object | None) -> tuple[int, object]:
    if isinstance(value, bool):
        return (0, int(value))
    if isinstance(value, (int, float)):
        return (1, value)
    if isinstance(value, str):
        return (2, value)
    return (3, "")


def _snapshot(
    definition: BatchDefinition, output_schema: Mapping[str, object]
) -> Mapping[str, object]:
    return {
        "datasetId": definition.dataset_id,
        "pluginId": definition.plugin_id,
        "toolName": definition.tool_name,
        "argumentMappings": definition.argument_mappings,
        "inputSchema": definition.input_schema,
        "outputSchema": dict(output_schema),
    }


def create_postgres_batch_execution_module(
    settings: Settings,
    projects: ProjectModule,
    datasets: DatasetModule,
    gateway: PluginGatewayModule,
) -> BatchExecutionModule:
    return BatchExecutionModule(projects, datasets, gateway, PostgresBatchRunStore(settings))
