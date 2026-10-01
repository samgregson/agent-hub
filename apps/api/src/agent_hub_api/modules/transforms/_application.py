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
    source_hash: str
    revision: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class TransformPreview:
    output: object
    runtime: str
    source_hash: str


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
    async def execute(
        self, source: str, inputs: dict[str, object], parameters: dict[str, object]
    ) -> tuple[object, str]: ...


class TransformModule:
    """Own validation and authorized lifecycle of Transform Definitions."""

    def __init__(
        self, projects: ProjectModule, store: TransformStore,
        runner: TransformRunner | None = None,
    ) -> None:
        self._projects = projects
        self._store = store
        self._runner = runner

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
        now = datetime.now(UTC)
        return await self._store.create(
            TransformDefinition(
                str(uuid4()), project_id, clean_name, clean_source, selectors, schema,
                None, hashlib.sha256(clean_source.encode()).hexdigest(), 1, now, now,
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
        revised = replace(
            current,
            name=clean_name,
            source=clean_source,
            input_selectors=selectors,
            output_schema=schema,
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
        inputs = {
            name: _select(record, pointer)
            for name, pointer in definition.input_selectors.items()
        }
        parameter_values = dict(parameters)
        try:
            if len(json.dumps(
                {"inputs": inputs, "parameters": parameter_values}, allow_nan=False
            ).encode()) > 64_000:
                raise TransformValidationError("Transform inputs exceed 64000 bytes.")
        except (TypeError, ValueError) as error:
            raise TransformValidationError("Transform inputs must be JSON values.") from error
        output, runtime = await self._runner.execute(
            definition.source, inputs, parameter_values
        )
        if not Draft202012Validator(definition.output_schema).is_valid(output):
            raise TransformValidationError("Transform output does not match its output schema.")
        return TransformPreview(output, runtime, definition.source_hash)

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
                runtime,source_hash,revision,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
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
                output_schema=%s,runtime=%s,source_hash=%s,revision=%s,updated_at=%s
                WHERE project_id=%s AND transform_definition_id=%s AND revision=%s""",
                (
                    definition.name, definition.source, json.dumps(definition.input_selectors),
                    json.dumps(definition.output_schema), definition.runtime,
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
        definition.runtime, definition.source_hash, definition.revision,
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
        source_hash=str(row["source_hash"]),
        revision=cast(int, row["revision"]),
        created_at=cast(datetime, row["created_at"]),
        updated_at=cast(datetime, row["updated_at"]),
    )


def create_postgres_transform_module(
    settings: Settings, projects: ProjectModule
) -> TransformModule:
    from agent_hub_api.modules.transforms._runner import DenoTransformRunner

    runner = (
        DenoTransformRunner(settings.transform_runner_url)
        if settings.transform_runner_url else None
    )
    return TransformModule(projects, PostgresTransformStore(settings), runner)
