"""Project-owned Python Functions and their persistence boundary."""

import ast
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import uuid4

from jsonschema import Draft202012Validator, SchemaError  # type: ignore[import-untyped]
from jsonschema import ValidationError as JsonSchemaValidationError
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from agent_hub_api.modules.projects import ProjectAccess, ProjectModule, ProjectNotFound
from agent_hub_api.settings import Settings


@dataclass(frozen=True, slots=True)
class FunctionDefinition:
    id: str
    project_id: str
    name: str
    source: str
    input_schema: Mapping[str, object]
    output_schema: Mapping[str, object]
    runtime: str | None
    package_hash: str | None
    source_hash: str
    revision: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class FunctionPreview:
    output: object
    runtime: str
    source_hash: str


@dataclass(frozen=True, slots=True)
class FunctionRuntimeIdentity:
    runtime: str
    package_hash: str
    limits: Mapping[str, object] = field(default_factory=dict)


class FunctionNotFound(Exception):
    """The Function is unavailable in this Project."""


class FunctionValidationError(Exception):
    """The Function does not meet its declared contract."""


class FunctionExecutionError(Exception):
    """The isolated Function runner could not produce a valid output."""

    def __init__(
        self,
        code: str,
        diagnostic: Mapping[str, object] | None = None,
    ) -> None:
        self.code = code
        self.diagnostic = dict(diagnostic) if diagnostic else None
        message = self.diagnostic.get("message") if self.diagnostic else None
        traceback = self.diagnostic.get("traceback") if self.diagnostic else None
        stderr = self.diagnostic.get("stderr") if self.diagnostic else None
        details = [
            value for value in (message, traceback, stderr) if isinstance(value, str) and value
        ]
        details_text = "\n".join(details)
        super().__init__(f"{code}: {details_text}" if details_text else code)


class FunctionStore(Protocol):
    async def create(self, definition: FunctionDefinition) -> FunctionDefinition: ...
    async def load(self, project_id: str, definition_id: str) -> FunctionDefinition | None: ...
    async def list(self, project_id: str) -> Sequence[FunctionDefinition]: ...
    async def replace(self, definition: FunctionDefinition) -> bool: ...
    async def delete(self, project_id: str, definition_id: str) -> bool: ...


class FunctionRunner(Protocol):
    async def identity(self) -> FunctionRuntimeIdentity: ...

    async def execute(
        self, source: str, inputs: dict[str, object], parameters: dict[str, object]
    ) -> tuple[object, str]: ...


class FunctionModule:
    """Own validation, authoring, preview, and Workflow execution of Python Functions."""

    def __init__(
        self,
        projects: ProjectModule,
        store: FunctionStore,
        runner: FunctionRunner | None = None,
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
        input_schema: Mapping[str, object],
        output_schema: Mapping[str, object],
    ) -> FunctionDefinition:
        await self._authorize(access, project_id)
        clean_name, clean_source, contract, schema = _validate_definition(
            name, source, input_schema, output_schema
        )
        identity = await self._runner.identity() if self._runner else None
        now = datetime.now(UTC)
        return await self._store.create(
            FunctionDefinition(
                str(uuid4()),
                project_id,
                clean_name,
                clean_source,
                contract,
                schema,
                identity.runtime if identity else None,
                identity.package_hash if identity else None,
                hashlib.sha256(clean_source.encode()).hexdigest(),
                1,
                now,
                now,
            )
        )

    async def load(
        self, access: ProjectAccess, project_id: str, definition_id: str
    ) -> FunctionDefinition:
        await self._authorize(access, project_id)
        definition = await self._store.load(project_id, definition_id)
        if definition is None:
            raise FunctionNotFound
        return definition

    async def list(self, access: ProjectAccess, project_id: str) -> Sequence[FunctionDefinition]:
        await self._authorize(access, project_id)
        return await self._store.list(project_id)

    async def revise(
        self,
        access: ProjectAccess,
        project_id: str,
        definition_id: str,
        name: str,
        source: str,
        input_schema: Mapping[str, object],
        output_schema: Mapping[str, object],
    ) -> FunctionDefinition:
        current = await self.load(access, project_id, definition_id)
        clean_name, clean_source, contract, schema = _validate_definition(
            name, source, input_schema, output_schema
        )
        identity = await self._runner.identity() if self._runner else None
        revised = replace(
            current,
            name=clean_name,
            source=clean_source,
            input_schema=contract,
            output_schema=schema,
            runtime=identity.runtime if identity else None,
            package_hash=identity.package_hash if identity else None,
            source_hash=hashlib.sha256(clean_source.encode()).hexdigest(),
            revision=current.revision + 1,
            updated_at=datetime.now(UTC),
        )
        if not await self._store.replace(revised):
            raise FunctionNotFound
        return revised

    async def delete(self, access: ProjectAccess, project_id: str, definition_id: str) -> None:
        await self._authorize(access, project_id)
        if not await self._store.delete(project_id, definition_id):
            raise FunctionNotFound

    async def preview(
        self,
        access: ProjectAccess,
        project_id: str,
        definition_id: str,
        inputs: Mapping[str, object],
        parameters: Mapping[str, object],
    ) -> FunctionPreview:
        definition = await self.load(access, project_id, definition_id)
        if self._runner is None:
            raise FunctionExecutionError("runner_unavailable")
        input_values = cast(dict[str, object], _snapshot_value(dict(inputs)))
        _validate_function_values(definition.input_schema, input_values)
        parameter_values = cast(dict[str, object], _snapshot_value(dict(parameters)))
        if len(_canonical({"inputs": input_values, "parameters": parameter_values})) > 64_000:
            raise FunctionValidationError("Function preview inputs exceed 64000 bytes.")
        output, runtime = await self._runner.execute(
            definition.source, input_values, parameter_values
        )
        if not Draft202012Validator(definition.output_schema).is_valid(output):
            raise FunctionValidationError("Function output does not match its output schema.")
        return FunctionPreview(output, runtime, definition.source_hash)

    async def execute_workflow_function(
        self,
        access: ProjectAccess,
        project_id: str,
        snapshot: Mapping[str, object],
        inputs: Mapping[str, object],
    ) -> object:
        """Execute a captured Function for a Workflow without creating a child Run."""
        await self._authorize(access, project_id)
        if self._runner is None:
            raise FunctionExecutionError("runner_unavailable")
        try:
            runtime = snapshot["runtime"]
            package_hash = snapshot["packageHash"]
            source = snapshot["source"]
            input_schema = snapshot["inputSchema"]
            output_schema = snapshot["outputSchema"]
            input_names = snapshot["inputNames"]
        except KeyError as error:
            raise FunctionValidationError("Function snapshot is incomplete.") from error
        if (
            not isinstance(runtime, str)
            or not isinstance(package_hash, str)
            or not isinstance(source, str)
            or not isinstance(input_schema, Mapping)
            or not isinstance(output_schema, Mapping)
            or not isinstance(input_names, list)
            or not all(isinstance(name, str) for name in input_names)
        ):
            raise FunctionValidationError("Function snapshot is invalid.")
        if not set(inputs).issubset(input_names):
            raise FunctionValidationError("Function input names must be declared inputs.")
        identity = await self._runner.identity()
        if runtime != identity.runtime or package_hash != identity.package_hash:
            raise FunctionExecutionError("runtime_mismatch")
        try:
            input_values = cast(dict[str, object], _snapshot_value(dict(inputs)))
            _validate_function_values(input_schema, input_values)
            if len(_canonical({"inputs": input_values, "parameters": {}})) > 64_000:
                raise FunctionValidationError("Function inputs exceed 64000 bytes.")
        except (TypeError, ValueError) as error:
            raise FunctionValidationError("Function inputs must be JSON values.") from error
        output, executed_runtime = await self._runner.execute(source, input_values, {})
        if executed_runtime != runtime:
            raise FunctionExecutionError("runtime_mismatch")
        if not Draft202012Validator(output_schema).is_valid(output):
            raise FunctionValidationError("Function output does not match its output schema.")
        try:
            if len(_canonical(output)) > 128_000:
                raise FunctionExecutionError("output_limit")
        except (TypeError, ValueError) as error:
            raise FunctionValidationError("Function output must be a JSON value.") from error
        return output

    async def _authorize(self, access: ProjectAccess, project_id: str) -> None:
        try:
            await self._projects.load(access, project_id)
        except ProjectNotFound as error:
            raise FunctionNotFound from error


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _snapshot_value(value: object) -> object:
    return json.loads(_canonical(value))


def _validate_function_values(schema: Mapping[str, object], values: Mapping[str, object]) -> None:
    try:
        Draft202012Validator(schema).validate(dict(values))
    except JsonSchemaValidationError as error:
        path = ".".join(str(part) for part in error.absolute_path) or "inputs"
        raise FunctionValidationError(
            f"Function input does not match its declared schema at {path}: {error.message}"
        ) from error


def _validate_definition(
    name: str,
    source: str,
    input_schema: Mapping[str, object],
    output_schema: Mapping[str, object],
) -> tuple[str, str, dict[str, object], dict[str, object]]:
    clean_name = name.strip()
    if not clean_name or len(clean_name) > 160:
        raise FunctionValidationError("Function name must contain 1 to 160 characters.")
    if not source.strip() or len(source.encode()) > 64_000:
        raise FunctionValidationError("Function source must contain 1 to 64000 bytes.")
    try:
        ast.parse(source)
    except SyntaxError as error:
        raise FunctionValidationError("Function source is not valid Python.") from error
    contract = dict(input_schema)
    properties = contract.get("properties")
    required = contract.get("required", [])
    try:
        if len(json.dumps(contract, allow_nan=False).encode()) > 16_000:
            raise FunctionValidationError("Function input schema exceeds 16000 bytes.")
        Draft202012Validator.check_schema(contract)
        if (
            contract.get("type") != "object"
            or not isinstance(properties, Mapping)
            or len(properties) > 32
            or any(not isinstance(key, str) or not key.isidentifier() for key in properties)
            or not isinstance(required, list)
            or any(not isinstance(item, str) for item in required)
            or not set(required).issubset(properties)
        ):
            raise FunctionValidationError("Function input schema must describe named inputs.")
    except (SchemaError, TypeError, ValueError) as error:
        raise FunctionValidationError("Function input schema is invalid.") from error
    schema = dict(output_schema)
    try:
        if len(json.dumps(schema, allow_nan=False).encode()) > 16_000:
            raise FunctionValidationError("Function output schema exceeds 16000 bytes.")
        Draft202012Validator.check_schema(schema)
    except (SchemaError, TypeError, ValueError) as error:
        raise FunctionValidationError("Function output schema is invalid.") from error
    return clean_name, source, contract, schema


class MemoryFunctionStore:
    def __init__(self) -> None:
        self._definitions: dict[tuple[str, str], FunctionDefinition] = {}

    async def create(self, definition: FunctionDefinition) -> FunctionDefinition:
        self._definitions[(definition.project_id, definition.id)] = definition
        return definition

    async def load(self, project_id: str, definition_id: str) -> FunctionDefinition | None:
        return self._definitions.get((project_id, definition_id))

    async def list(self, project_id: str) -> Sequence[FunctionDefinition]:
        return tuple(
            item
            for (stored_project, _), item in self._definitions.items()
            if stored_project == project_id
        )

    async def replace(self, definition: FunctionDefinition) -> bool:
        key = (definition.project_id, definition.id)
        if key not in self._definitions:
            return False
        self._definitions[key] = definition
        return True

    async def delete(self, project_id: str, definition_id: str) -> bool:
        return self._definitions.pop((project_id, definition_id), None) is not None


class PostgresFunctionStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def _connect(self) -> AsyncConnection[dict[str, object]]:
        return await AsyncConnection.connect(
            str(self._settings.database_url),
            connect_timeout=self._settings.database_connect_timeout_seconds,
            row_factory=dict_row,
        )

    async def create(self, definition: FunctionDefinition) -> FunctionDefinition:
        connection = await self._connect()
        async with connection:
            await connection.execute(
                """INSERT INTO functions
                (project_id,function_id,name,source,input_schema,output_schema,runtime,
                 package_hash,source_hash,revision,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                _values(definition),
            )
        return definition

    async def load(self, project_id: str, definition_id: str) -> FunctionDefinition | None:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                "SELECT * FROM functions WHERE project_id=%s AND function_id=%s",
                (project_id, definition_id),
            )
            row = await cursor.fetchone()
        return _from_row(row) if row else None

    async def list(self, project_id: str) -> Sequence[FunctionDefinition]:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                "SELECT * FROM functions WHERE project_id=%s ORDER BY created_at, function_id",
                (project_id,),
            )
            rows = await cursor.fetchall()
        return tuple(_from_row(row) for row in rows)

    async def replace(self, definition: FunctionDefinition) -> bool:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """UPDATE functions SET name=%s,source=%s,input_schema=%s,output_schema=%s,
                runtime=%s,package_hash=%s,source_hash=%s,revision=%s,updated_at=%s
                WHERE project_id=%s AND function_id=%s AND revision=%s""",
                (
                    definition.name,
                    definition.source,
                    json.dumps(definition.input_schema),
                    json.dumps(definition.output_schema),
                    definition.runtime,
                    definition.package_hash,
                    definition.source_hash,
                    definition.revision,
                    definition.updated_at,
                    definition.project_id,
                    definition.id,
                    definition.revision - 1,
                ),
            )
            return cursor.rowcount == 1

    async def delete(self, project_id: str, definition_id: str) -> bool:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                "DELETE FROM functions WHERE project_id=%s AND function_id=%s",
                (project_id, definition_id),
            )
            return cursor.rowcount == 1


def _values(definition: FunctionDefinition) -> tuple[object, ...]:
    return (
        definition.project_id,
        definition.id,
        definition.name,
        definition.source,
        json.dumps(definition.input_schema),
        json.dumps(definition.output_schema),
        definition.runtime,
        definition.package_hash,
        definition.source_hash,
        definition.revision,
        definition.created_at,
        definition.updated_at,
    )


def _from_row(row: Mapping[str, object]) -> FunctionDefinition:
    input_schema = row["input_schema"]
    output_schema = row["output_schema"]
    return FunctionDefinition(
        id=str(row["function_id"]),
        project_id=str(row["project_id"]),
        name=str(row["name"]),
        source=str(row["source"]),
        input_schema=(
            json.loads(input_schema)
            if isinstance(input_schema, str)
            else dict(cast(Mapping[str, object], input_schema))
        ),
        output_schema=(
            json.loads(output_schema)
            if isinstance(output_schema, str)
            else dict(cast(Mapping[str, object], output_schema))
        ),
        runtime=str(row["runtime"]) if row["runtime"] is not None else None,
        package_hash=str(row["package_hash"]) if row["package_hash"] is not None else None,
        source_hash=str(row["source_hash"]),
        revision=cast(int, row["revision"]),
        created_at=cast(datetime, row["created_at"]),
        updated_at=cast(datetime, row["updated_at"]),
    )


def create_postgres_function_module(
    settings: Settings,
    projects: ProjectModule,
    runner: FunctionRunner | None = None,
) -> FunctionModule:
    from agent_hub_api.modules.functions._runner import DenoFunctionRunner

    resolved_runner = runner or (
        DenoFunctionRunner(settings.function_runner_url) if settings.function_runner_url else None
    )
    return FunctionModule(projects, PostgresFunctionStore(settings), resolved_runner)
