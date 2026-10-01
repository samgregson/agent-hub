"""Project-owned Transform Definitions and their persistence boundary."""

import ast
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import uuid4

from jsonschema import Draft202012Validator, SchemaError  # type: ignore[import-untyped]
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from agent_hub_api.modules.projects import ProjectAccess, ProjectModule, ProjectNotFound
from agent_hub_api.settings import Settings


@dataclass(frozen=True, slots=True)
class TransformDefinition:
    id: str
    project_id: str
    name: str
    source: str
    input_selectors: Mapping[str, str]
    output_schema: Mapping[str, object]
    runtime: str | None
    package_hash: str | None
    source_hash: str
    revision: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class TransformPreview:
    output: object
    runtime: str
    source_hash: str


@dataclass(frozen=True, slots=True)
class TransformRuntimeIdentity:
    runtime: str
    package_hash: str


@dataclass(frozen=True, slots=True)
class TransformRun:
    id: str
    project_id: str
    definition_id: str
    status: str
    definition_snapshot: Mapping[str, object]
    inputs: Mapping[str, object]
    parameters: Mapping[str, object]
    input_hash: str
    source_hash: str
    runtime: str | None
    package_hash: str | None
    output: object | None
    output_manifest: Mapping[str, object]
    error: str | None
    initiator_subject: str
    created_at: datetime
    completed_at: datetime | None


class TransformNotFound(Exception):
    """The Transform Definition is unavailable in this Project."""


class TransformValidationError(Exception):
    """The Transform Definition does not meet its declared contract."""


class TransformExecutionError(Exception):
    """The isolated Transform runner could not produce a valid output."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class TransformStore(Protocol):
    async def create(self, definition: TransformDefinition) -> TransformDefinition: ...
    async def load(self, project_id: str, definition_id: str) -> TransformDefinition | None: ...
    async def list(self, project_id: str) -> Sequence[TransformDefinition]: ...
    async def replace(self, definition: TransformDefinition) -> bool: ...
    async def delete(self, project_id: str, definition_id: str) -> bool: ...


class TransformRunner(Protocol):
    async def identity(self) -> TransformRuntimeIdentity: ...

    async def execute(
        self, source: str, inputs: dict[str, object], parameters: dict[str, object]
    ) -> tuple[object, str]: ...


class TransformRunStore(Protocol):
    async def create(self, run: TransformRun) -> TransformRun: ...
    async def complete(self, run: TransformRun) -> TransformRun: ...
    async def load(self, project_id: str, run_id: str) -> TransformRun | None: ...
    async def reconcile_running(self, now: datetime) -> int: ...


class TransformModule:
    """Own validation and authorized lifecycle of Transform Definitions."""

    def __init__(
        self, projects: ProjectModule, store: TransformStore,
        runner: TransformRunner | None = None,
        run_store: TransformRunStore | None = None,
    ) -> None:
        self._projects = projects
        self._store = store
        self._runner = runner
        self._run_store = run_store

    async def define(
        self,
        access: ProjectAccess,
        project_id: str,
        name: str,
        source: str,
        input_selectors: Mapping[str, str],
        output_schema: Mapping[str, object],
    ) -> TransformDefinition:
        await self._authorize(access, project_id)
        clean_name, clean_source, selectors, schema = _validate_definition(
            name, source, input_selectors, output_schema
        )
        identity = await self._runner.identity() if self._runner else None
        now = datetime.now(UTC)
        return await self._store.create(
            TransformDefinition(
                str(uuid4()), project_id, clean_name, clean_source, selectors, schema,
                identity.runtime if identity else None,
                identity.package_hash if identity else None,
                hashlib.sha256(clean_source.encode()).hexdigest(), 1, now, now,
            )
        )

    async def load(
        self, access: ProjectAccess, project_id: str, definition_id: str
    ) -> TransformDefinition:
        await self._authorize(access, project_id)
        definition = await self._store.load(project_id, definition_id)
        if definition is None:
            raise TransformNotFound
        return definition

    async def list(
        self, access: ProjectAccess, project_id: str
    ) -> Sequence[TransformDefinition]:
        await self._authorize(access, project_id)
        return await self._store.list(project_id)

    async def revise(
        self,
        access: ProjectAccess,
        project_id: str,
        definition_id: str,
        name: str,
        source: str,
        input_selectors: Mapping[str, str],
        output_schema: Mapping[str, object],
    ) -> TransformDefinition:
        current = await self.load(access, project_id, definition_id)
        clean_name, clean_source, selectors, schema = _validate_definition(
            name, source, input_selectors, output_schema
        )
        identity = await self._runner.identity() if self._runner else None
        revised = replace(
            current,
            name=clean_name,
            source=clean_source,
            input_selectors=selectors,
            output_schema=schema,
            runtime=identity.runtime if identity else None,
            package_hash=identity.package_hash if identity else None,
            source_hash=hashlib.sha256(clean_source.encode()).hexdigest(),
            revision=current.revision + 1,
            updated_at=datetime.now(UTC),
        )
        if not await self._store.replace(revised):
            raise TransformNotFound
        return revised

    async def delete(self, access: ProjectAccess, project_id: str, definition_id: str) -> None:
        await self._authorize(access, project_id)
        if not await self._store.delete(project_id, definition_id):
            raise TransformNotFound

    async def preview(
        self, access: ProjectAccess, project_id: str, definition_id: str,
        record: Mapping[str, object], parameters: Mapping[str, object],
    ) -> TransformPreview:
        definition = await self.load(access, project_id, definition_id)
        if self._runner is None:
            raise TransformExecutionError("runner_unavailable")
        inputs, parameter_values = _inputs(definition, record, parameters)
        output, runtime = await self._runner.execute(
            definition.source, inputs, parameter_values
        )
        if not Draft202012Validator(definition.output_schema).is_valid(output):
            raise TransformValidationError("Transform output does not match its output schema.")
        return TransformPreview(output, runtime, definition.source_hash)

    async def start_run(
        self, access: ProjectAccess, project_id: str, definition_id: str,
        record: Mapping[str, object], parameters: Mapping[str, object],
    ) -> TransformRun:
        definition = await self.load(access, project_id, definition_id)
        if self._run_store is None:
            raise TransformExecutionError("run_store_unavailable")
        if self._runner is None:
            raise TransformExecutionError("runner_unavailable")
        identity = await self._runner.identity()
        if definition.runtime and (
            definition.runtime != identity.runtime or
            definition.package_hash != identity.package_hash
        ):
            raise TransformExecutionError("runtime_mismatch")
        inputs, parameter_values = _inputs(definition, record, parameters)
        input_bytes = _canonical({"inputs": inputs, "parameters": parameter_values})
        now = datetime.now(UTC)
        run = await self._run_store.create(TransformRun(
            id=str(uuid4()), project_id=project_id, definition_id=definition_id,
            status="running", definition_snapshot={
                "name": definition.name, "source": definition.source,
                "input_selectors": dict(definition.input_selectors),
                "output_schema": dict(definition.output_schema),
                "revision": definition.revision,
                "runtime": identity.runtime,
                "package_hash": identity.package_hash,
            },
            inputs=inputs, parameters=parameter_values,
            input_hash=hashlib.sha256(input_bytes).hexdigest(),
            source_hash=definition.source_hash, runtime=identity.runtime,
            package_hash=identity.package_hash, output=None,
            output_manifest={}, error=None, initiator_subject=access.subject,
            created_at=now, completed_at=None,
        ))
        try:
            output, runtime = await self._runner.execute(
                definition.source, inputs, parameter_values
            )
            if runtime != identity.runtime:
                raise TransformExecutionError("runtime_mismatch")
            if not Draft202012Validator(definition.output_schema).is_valid(output):
                raise TransformExecutionError("output_schema")
            output_bytes = _canonical(output)
            if len(output_bytes) > 128_000:
                raise TransformExecutionError("output_limit")
            completed = replace(
                run, status="succeeded", output=output,
                output_manifest={
                    "kind": "json", "bytes": len(output_bytes),
                    "sha256": hashlib.sha256(output_bytes).hexdigest(),
                },
                completed_at=datetime.now(UTC),
            )
        except TransformExecutionError as error:
            completed = replace(
                run, status="failed", error=error.code, completed_at=datetime.now(UTC)
            )
        return await self._run_store.complete(completed)

    async def load_run(
        self, access: ProjectAccess, project_id: str, run_id: str
    ) -> TransformRun:
        await self._authorize(access, project_id)
        if self._run_store is None:
            raise TransformExecutionError("run_store_unavailable")
        run = await self._run_store.load(project_id, run_id)
        if run is None:
            raise TransformNotFound
        return run

    async def recover(self) -> int:
        if self._run_store is None:
            return 0
        return await self._run_store.reconcile_running(datetime.now(UTC))

    async def _authorize(self, access: ProjectAccess, project_id: str) -> None:
        try:
            await self._projects.load(access, project_id)
        except ProjectNotFound as error:
            raise TransformNotFound from error


def _select(record: Mapping[str, object], pointer: str) -> object:
    value: object = record
    for raw in pointer[1:].split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict) and key in value:
            value = value[key]
        elif isinstance(value, list) and key.isdecimal() and int(key) < len(value):
            value = value[int(key)]
        else:
            raise TransformValidationError("Transform input selector did not match the record.")
    return value


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _inputs(
    definition: TransformDefinition, record: Mapping[str, object],
    parameters: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    inputs = {
        name: _select(record, pointer)
        for name, pointer in definition.input_selectors.items()
    }
    parameter_values = dict(parameters)
    try:
        if len(_canonical({"inputs": inputs, "parameters": parameter_values})) > 64_000:
            raise TransformValidationError("Transform inputs exceed 64000 bytes.")
    except (TypeError, ValueError) as error:
        raise TransformValidationError("Transform inputs must be JSON values.") from error
    return inputs, parameter_values


class MemoryTransformRunStore:
    def __init__(self) -> None:
        self._runs: dict[tuple[str, str], TransformRun] = {}

    async def create(self, run: TransformRun) -> TransformRun:
        self._runs[(run.project_id, run.id)] = run
        return run

    async def complete(self, run: TransformRun) -> TransformRun:
        key = (run.project_id, run.id)
        if self._runs[key].status != "running":
            raise TransformExecutionError("run_already_completed")
        self._runs[key] = run
        return run

    async def load(self, project_id: str, run_id: str) -> TransformRun | None:
        return self._runs.get((project_id, run_id))

    async def reconcile_running(self, now: datetime) -> int:
        active = [key for key, run in self._runs.items() if run.status == "running"]
        for key in active:
            self._runs[key] = replace(
                self._runs[key], status="failed", error="interrupted", completed_at=now
            )
        return len(active)


def _validate_definition(
    name: str, source: str, input_selectors: Mapping[str, str],
    output_schema: Mapping[str, object],
) -> tuple[str, str, dict[str, str], dict[str, object]]:
    clean_name = name.strip()
    if not clean_name or len(clean_name) > 160:
        raise TransformValidationError("Transform name must contain 1 to 160 characters.")
    if not source.strip() or len(source.encode()) > 64_000:
        raise TransformValidationError("Transform source must contain 1 to 64000 bytes.")
    try:
        ast.parse(source)
    except SyntaxError as error:
        raise TransformValidationError("Transform source is not valid Python.") from error
    selectors = dict(input_selectors)
    if not selectors or len(selectors) > 32 or any(
        not key.isidentifier() or not isinstance(pointer, str) or not pointer.startswith("/")
        for key, pointer in selectors.items()
    ):
        raise TransformValidationError("Each input selector needs a name and JSON pointer.")
    schema = dict(output_schema)
    try:
        if len(json.dumps(schema, allow_nan=False).encode()) > 16_000:
            raise TransformValidationError("Transform output schema exceeds 16000 bytes.")
        Draft202012Validator.check_schema(schema)
    except (SchemaError, TypeError, ValueError) as error:
        raise TransformValidationError("Transform output schema is invalid.") from error
    return clean_name, source, selectors, schema


class MemoryTransformStore:
    def __init__(self) -> None:
        self._definitions: dict[tuple[str, str], TransformDefinition] = {}

    async def create(self, definition: TransformDefinition) -> TransformDefinition:
        self._definitions[(definition.project_id, definition.id)] = definition
        return definition

    async def load(self, project_id: str, definition_id: str) -> TransformDefinition | None:
        return self._definitions.get((project_id, definition_id))

    async def list(self, project_id: str) -> Sequence[TransformDefinition]:
        return tuple(
            item for (stored_project, _), item in self._definitions.items()
            if stored_project == project_id
        )

    async def replace(self, definition: TransformDefinition) -> bool:
        key = (definition.project_id, definition.id)
        if key not in self._definitions:
            return False
        self._definitions[key] = definition
        return True

    async def delete(self, project_id: str, definition_id: str) -> bool:
        return self._definitions.pop((project_id, definition_id), None) is not None


class PostgresTransformStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def _connect(self) -> AsyncConnection[dict[str, object]]:
        return await AsyncConnection.connect(
            str(self._settings.database_url),
            connect_timeout=self._settings.database_connect_timeout_seconds,
            row_factory=dict_row,
        )

    async def create(self, definition: TransformDefinition) -> TransformDefinition:
        connection = await self._connect()
        async with connection:
            await connection.execute(
                """INSERT INTO transform_definitions
                (project_id,transform_definition_id,name,source,input_selectors,output_schema,
                runtime,package_hash,source_hash,revision,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                _values(definition),
            )
        return definition

    async def load(self, project_id: str, definition_id: str) -> TransformDefinition | None:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """SELECT * FROM transform_definitions
                WHERE project_id=%s AND transform_definition_id=%s""",
                (project_id, definition_id),
            )
            row = await cursor.fetchone()
        return _from_row(row) if row else None

    async def list(self, project_id: str) -> Sequence[TransformDefinition]:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """SELECT * FROM transform_definitions WHERE project_id=%s
                ORDER BY created_at, transform_definition_id""",
                (project_id,),
            )
            rows = await cursor.fetchall()
        return tuple(_from_row(row) for row in rows)

    async def replace(self, definition: TransformDefinition) -> bool:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """UPDATE transform_definitions SET name=%s,source=%s,input_selectors=%s,
                output_schema=%s,runtime=%s,package_hash=%s,source_hash=%s,revision=%s,updated_at=%s
                WHERE project_id=%s AND transform_definition_id=%s AND revision=%s""",
                (
                    definition.name, definition.source, json.dumps(definition.input_selectors),
                    json.dumps(definition.output_schema), definition.runtime,
                    definition.package_hash,
                    definition.source_hash, definition.revision, definition.updated_at,
                    definition.project_id, definition.id, definition.revision - 1,
                ),
            )
            return cursor.rowcount == 1

    async def delete(self, project_id: str, definition_id: str) -> bool:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """DELETE FROM transform_definitions
                WHERE project_id=%s AND transform_definition_id=%s""",
                (project_id, definition_id),
            )
            return cursor.rowcount == 1


def _values(definition: TransformDefinition) -> tuple[object, ...]:
    return (
        definition.project_id, definition.id, definition.name, definition.source,
        json.dumps(definition.input_selectors), json.dumps(definition.output_schema),
        definition.runtime, definition.package_hash, definition.source_hash, definition.revision,
        definition.created_at, definition.updated_at,
    )


def _from_row(row: Mapping[str, object]) -> TransformDefinition:
    selectors = row["input_selectors"]
    schema = row["output_schema"]
    return TransformDefinition(
        id=str(row["transform_definition_id"]),
        project_id=str(row["project_id"]),
        name=str(row["name"]),
        source=str(row["source"]),
        input_selectors=(
            json.loads(selectors) if isinstance(selectors, str)
            else dict(cast(Mapping[str, str], selectors))
        ),
        output_schema=(
            json.loads(schema) if isinstance(schema, str)
            else dict(cast(Mapping[str, object], schema))
        ),
        runtime=str(row["runtime"]) if row["runtime"] is not None else None,
        package_hash=str(row["package_hash"]) if row["package_hash"] is not None else None,
        source_hash=str(row["source_hash"]),
        revision=cast(int, row["revision"]),
        created_at=cast(datetime, row["created_at"]),
        updated_at=cast(datetime, row["updated_at"]),
    )


def create_postgres_transform_module(
    settings: Settings, projects: ProjectModule,
    runner: TransformRunner | None = None,
) -> TransformModule:
    from agent_hub_api.modules.transforms._run_store import PostgresTransformRunStore
    from agent_hub_api.modules.transforms._runner import DenoTransformRunner

    resolved_runner = runner or (
        DenoTransformRunner(settings.transform_runner_url)
        if settings.transform_runner_url else None
    )
    return TransformModule(
        projects, PostgresTransformStore(settings), resolved_runner,
        PostgresTransformRunStore(settings),
    )
