import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from jsonschema import Draft202012Validator, ValidationError  # type: ignore[import-untyped]
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from agent_hub_api.modules.projects import ProjectAccess, ProjectModule, ProjectNotFound
from agent_hub_api.settings import Settings


@dataclass(frozen=True, slots=True)
class DatasetRecordInput:
    value: Mapping[str, object]
    source_key: str | None = None
    id: str | None = None


@dataclass(frozen=True, slots=True)
class DatasetRecord:
    id: str
    position: int
    value: Mapping[str, object]
    source_key: str | None


@dataclass(frozen=True, slots=True)
class Dataset:
    id: str
    project_id: str
    name: str
    records: tuple[DatasetRecord, ...]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class BatchDefinition:
    id: str
    project_id: str
    dataset_id: str
    name: str
    plugin_id: str
    tool_name: str
    argument_mappings: Mapping[str, str]
    input_schema: Mapping[str, object]
    created_at: datetime
    updated_at: datetime


class DatasetNotFound(Exception):
    """No Dataset or Batch Definition is visible in the Project."""


class DatasetValidationError(Exception):
    """A Dataset or Batch Definition violates its host-owned contract."""


class ToolSchemaResolver(Protocol):
    async def input_schema(
        self,
        access: ProjectAccess,
        project_id: str,
        plugin_id: str,
        tool_name: str,
    ) -> Mapping[str, object]: ...


class DatasetStore(Protocol):
    async def create_dataset(self, dataset: Dataset) -> Dataset: ...

    async def load_dataset(self, project_id: str, dataset_id: str) -> Dataset | None: ...

    async def list_datasets(self, project_id: str) -> Sequence[Dataset]: ...

    async def replace_dataset(self, dataset: Dataset) -> Dataset | None: ...

    async def delete_dataset(self, project_id: str, dataset_id: str) -> bool: ...

    async def create_definition(self, definition: BatchDefinition) -> BatchDefinition: ...

    async def load_definition(
        self, project_id: str, definition_id: str
    ) -> BatchDefinition | None: ...

    async def list_definitions(self, project_id: str) -> Sequence[BatchDefinition]: ...

    async def replace_definition(self, definition: BatchDefinition) -> BatchDefinition | None: ...

    async def delete_definition(self, project_id: str, definition_id: str) -> bool: ...


class DatasetModule:
    """Own Project Dataset and Batch Definition validation and lifecycle."""

    def __init__(
        self,
        projects: ProjectModule,
        store: DatasetStore,
        tool_schemas: ToolSchemaResolver,
    ) -> None:
        self._projects = projects
        self._store = store
        self._tool_schemas = tool_schemas

    async def create_dataset(
        self,
        access: ProjectAccess,
        project_id: str,
        name: str,
        records: Sequence[DatasetRecordInput],
    ) -> Dataset:
        await self._authorize(access, project_id)
        now = datetime.now(UTC)
        return await self._store.create_dataset(
            Dataset(
                id=str(uuid4()),
                project_id=project_id,
                name=_name(name, "Dataset"),
                records=_records(records),
                created_at=now,
                updated_at=now,
            )
        )

    async def list_datasets(self, access: ProjectAccess, project_id: str) -> Sequence[Dataset]:
        await self._authorize(access, project_id)
        return await self._store.list_datasets(project_id)

    async def load_dataset(
        self, access: ProjectAccess, project_id: str, dataset_id: str
    ) -> Dataset:
        await self._authorize(access, project_id)
        dataset = await self._store.load_dataset(project_id, dataset_id)
        if dataset is None:
            raise DatasetNotFound
        return dataset

    async def update_dataset(
        self,
        access: ProjectAccess,
        project_id: str,
        dataset_id: str,
        name: str,
        records: Sequence[DatasetRecordInput],
    ) -> Dataset:
        current = await self.load_dataset(access, project_id, dataset_id)
        updated = Dataset(
            id=current.id,
            project_id=current.project_id,
            name=_name(name, "Dataset"),
            records=_records(records, existing=current.records),
            created_at=current.created_at,
            updated_at=datetime.now(UTC),
        )
        saved = await self._store.replace_dataset(updated)
        if saved is None:
            raise DatasetNotFound
        return saved

    async def delete_dataset(self, access: ProjectAccess, project_id: str, dataset_id: str) -> None:
        await self._authorize(access, project_id)
        if not await self._store.delete_dataset(project_id, dataset_id):
            raise DatasetNotFound

    async def create_definition(
        self,
        access: ProjectAccess,
        project_id: str,
        dataset_id: str,
        name: str,
        plugin_id: str,
        tool_name: str,
        argument_mappings: Mapping[str, str],
    ) -> BatchDefinition:
        dataset = await self.load_dataset(access, project_id, dataset_id)
        schema = await self._tool_schemas.input_schema(access, project_id, plugin_id, tool_name)
        mappings = _mappings(argument_mappings)
        _validate_mappings(dataset.records, mappings, schema)
        now = datetime.now(UTC)
        return await self._store.create_definition(
            BatchDefinition(
                id=str(uuid4()),
                project_id=project_id,
                dataset_id=dataset_id,
                name=_name(name, "Batch Definition"),
                plugin_id=plugin_id,
                tool_name=tool_name,
                argument_mappings=mappings,
                input_schema=dict(schema),
                created_at=now,
                updated_at=now,
            )
        )

    async def list_definitions(
        self, access: ProjectAccess, project_id: str
    ) -> Sequence[BatchDefinition]:
        await self._authorize(access, project_id)
        return await self._store.list_definitions(project_id)

    async def load_definition(
        self, access: ProjectAccess, project_id: str, definition_id: str
    ) -> BatchDefinition:
        await self._authorize(access, project_id)
        definition = await self._store.load_definition(project_id, definition_id)
        if definition is None:
            raise DatasetNotFound
        return definition

    async def update_definition(
        self,
        access: ProjectAccess,
        project_id: str,
        definition_id: str,
        dataset_id: str,
        name: str,
        plugin_id: str,
        tool_name: str,
        argument_mappings: Mapping[str, str],
    ) -> BatchDefinition:
        current = await self.load_definition(access, project_id, definition_id)
        dataset = await self.load_dataset(access, project_id, dataset_id)
        schema = await self._tool_schemas.input_schema(access, project_id, plugin_id, tool_name)
        mappings = _mappings(argument_mappings)
        _validate_mappings(dataset.records, mappings, schema)
        updated = BatchDefinition(
            id=current.id,
            project_id=current.project_id,
            dataset_id=dataset_id,
            name=_name(name, "Batch Definition"),
            plugin_id=plugin_id,
            tool_name=tool_name,
            argument_mappings=mappings,
            input_schema=dict(schema),
            created_at=current.created_at,
            updated_at=datetime.now(UTC),
        )
        saved = await self._store.replace_definition(updated)
        if saved is None:
            raise DatasetNotFound
        return saved

    async def delete_definition(
        self, access: ProjectAccess, project_id: str, definition_id: str
    ) -> None:
        await self._authorize(access, project_id)
        if not await self._store.delete_definition(project_id, definition_id):
            raise DatasetNotFound

    async def _authorize(self, access: ProjectAccess, project_id: str) -> None:
        try:
            await self._projects.load(access, project_id)
        except ProjectNotFound as error:
            raise DatasetNotFound from error


class MemoryDatasetStore:
    def __init__(self) -> None:
        self._datasets: dict[tuple[str, str], Dataset] = {}
        self._definitions: dict[tuple[str, str], BatchDefinition] = {}

    async def create_dataset(self, dataset: Dataset) -> Dataset:
        self._datasets[(dataset.project_id, dataset.id)] = dataset
        return dataset

    async def load_dataset(self, project_id: str, dataset_id: str) -> Dataset | None:
        return self._datasets.get((project_id, dataset_id))

    async def list_datasets(self, project_id: str) -> Sequence[Dataset]:
        return tuple(
            dataset for (owner, _), dataset in self._datasets.items() if owner == project_id
        )

    async def replace_dataset(self, dataset: Dataset) -> Dataset | None:
        key = (dataset.project_id, dataset.id)
        if key not in self._datasets:
            return None
        self._datasets[key] = dataset
        return dataset

    async def delete_dataset(self, project_id: str, dataset_id: str) -> bool:
        return self._datasets.pop((project_id, dataset_id), None) is not None

    async def create_definition(self, definition: BatchDefinition) -> BatchDefinition:
        self._definitions[(definition.project_id, definition.id)] = definition
        return definition

    async def load_definition(self, project_id: str, definition_id: str) -> BatchDefinition | None:
        return self._definitions.get((project_id, definition_id))

    async def list_definitions(self, project_id: str) -> Sequence[BatchDefinition]:
        return tuple(
            definition
            for (owner, _), definition in self._definitions.items()
            if owner == project_id
        )

    async def replace_definition(self, definition: BatchDefinition) -> BatchDefinition | None:
        key = (definition.project_id, definition.id)
        if key not in self._definitions:
            return None
        self._definitions[key] = definition
        return definition

    async def delete_definition(self, project_id: str, definition_id: str) -> bool:
        return self._definitions.pop((project_id, definition_id), None) is not None


class PostgresDatasetStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def _connect(self) -> AsyncConnection[dict[str, object]]:
        return await AsyncConnection.connect(
            str(self._settings.database_url),
            connect_timeout=self._settings.database_connect_timeout_seconds,
            row_factory=dict_row,
        )

    async def create_dataset(self, dataset: Dataset) -> Dataset:
        connection = await self._connect()
        async with connection:
            await _write_dataset(connection, dataset, replace=False)
        return dataset

    async def load_dataset(self, project_id: str, dataset_id: str) -> Dataset | None:
        connection = await self._connect()
        async with connection:
            return await _load_dataset(connection, project_id, dataset_id)

    async def list_datasets(self, project_id: str) -> Sequence[Dataset]:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                "SELECT dataset_id FROM datasets WHERE project_id=%s ORDER BY created_at",
                (project_id,),
            )
            datasets: list[Dataset] = []
            for row in await cursor.fetchall():
                dataset = await _load_dataset(connection, project_id, str(row["dataset_id"]))
                if dataset is not None:
                    datasets.append(dataset)
            return tuple(datasets)

    async def replace_dataset(self, dataset: Dataset) -> Dataset | None:
        connection = await self._connect()
        async with connection:
            existing = await _load_dataset(connection, dataset.project_id, dataset.id)
            if existing is None:
                return None
            await _write_dataset(connection, dataset, replace=True)
        return dataset

    async def delete_dataset(self, project_id: str, dataset_id: str) -> bool:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                "DELETE FROM datasets WHERE project_id=%s AND dataset_id=%s RETURNING dataset_id",
                (project_id, dataset_id),
            )
            return await cursor.fetchone() is not None

    async def create_definition(self, definition: BatchDefinition) -> BatchDefinition:
        connection = await self._connect()
        async with connection:
            await connection.execute(
                """INSERT INTO batch_definitions
                (project_id, batch_definition_id, dataset_id, name, plugin_id, tool_name,
                 argument_mappings, input_schema, created_at, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                _definition_values(definition),
            )
        return definition

    async def load_definition(self, project_id: str, definition_id: str) -> BatchDefinition | None:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                "SELECT * FROM batch_definitions WHERE project_id=%s AND batch_definition_id=%s",
                (project_id, definition_id),
            )
            row = await cursor.fetchone()
        return _definition_from_row(row) if row else None

    async def list_definitions(self, project_id: str) -> Sequence[BatchDefinition]:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                "SELECT * FROM batch_definitions WHERE project_id=%s ORDER BY created_at",
                (project_id,),
            )
            return tuple(_definition_from_row(row) for row in await cursor.fetchall())

    async def replace_definition(self, definition: BatchDefinition) -> BatchDefinition | None:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """UPDATE batch_definitions SET dataset_id=%s, name=%s, plugin_id=%s,
                tool_name=%s, argument_mappings=%s, input_schema=%s, updated_at=%s
                WHERE project_id=%s AND batch_definition_id=%s RETURNING batch_definition_id""",
                (
                    definition.dataset_id,
                    definition.name,
                    definition.plugin_id,
                    definition.tool_name,
                    json.dumps(definition.argument_mappings),
                    json.dumps(definition.input_schema),
                    definition.updated_at,
                    definition.project_id,
                    definition.id,
                ),
            )
            return definition if await cursor.fetchone() else None

    async def delete_definition(self, project_id: str, definition_id: str) -> bool:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """DELETE FROM batch_definitions
                WHERE project_id=%s AND batch_definition_id=%s
                RETURNING batch_definition_id""",
                (project_id, definition_id),
            )
            return await cursor.fetchone() is not None


async def _write_dataset(
    connection: AsyncConnection[dict[str, object]], dataset: Dataset, *, replace: bool
) -> None:
    if replace:
        await connection.execute(
            "UPDATE datasets SET name=%s, updated_at=%s WHERE project_id=%s AND dataset_id=%s",
            (dataset.name, dataset.updated_at, dataset.project_id, dataset.id),
        )
        await connection.execute(
            "DELETE FROM dataset_records WHERE project_id=%s AND dataset_id=%s",
            (dataset.project_id, dataset.id),
        )
    else:
        await connection.execute(
            """INSERT INTO datasets
            (project_id,dataset_id,name,created_at,updated_at) VALUES (%s,%s,%s,%s,%s)""",
            (
                dataset.project_id,
                dataset.id,
                dataset.name,
                dataset.created_at,
                dataset.updated_at,
            ),
        )
    for record in dataset.records:
        await connection.execute(
            """INSERT INTO dataset_records
            (project_id,dataset_id,record_id,position,source_key,value)
            VALUES (%s,%s,%s,%s,%s,%s)""",
            (
                dataset.project_id,
                dataset.id,
                record.id,
                record.position,
                record.source_key,
                json.dumps(record.value),
            ),
        )


async def _load_dataset(
    connection: AsyncConnection[dict[str, object]], project_id: str, dataset_id: str
) -> Dataset | None:
    cursor = await connection.execute(
        "SELECT * FROM datasets WHERE project_id=%s AND dataset_id=%s", (project_id, dataset_id)
    )
    dataset = await cursor.fetchone()
    if dataset is None:
        return None
    cursor = await connection.execute(
        "SELECT * FROM dataset_records WHERE project_id=%s AND dataset_id=%s ORDER BY position",
        (project_id, dataset_id),
    )
    records = tuple(
        DatasetRecord(
            id=str(row["record_id"]),
            position=int(str(row["position"])),
            source_key=str(row["source_key"]) if row["source_key"] is not None else None,
            value=_json_object(row["value"]),
        )
        for row in await cursor.fetchall()
    )
    return Dataset(
        id=str(dataset["dataset_id"]),
        project_id=str(dataset["project_id"]),
        name=str(dataset["name"]),
        records=records,
        created_at=dataset["created_at"],  # type: ignore[arg-type]
        updated_at=dataset["updated_at"],  # type: ignore[arg-type]
    )


def _definition_values(definition: BatchDefinition) -> tuple[object, ...]:
    return (
        definition.project_id,
        definition.id,
        definition.dataset_id,
        definition.name,
        definition.plugin_id,
        definition.tool_name,
        json.dumps(definition.argument_mappings),
        json.dumps(definition.input_schema),
        definition.created_at,
        definition.updated_at,
    )


def _definition_from_row(row: Mapping[str, object]) -> BatchDefinition:
    return BatchDefinition(
        id=str(row["batch_definition_id"]),
        project_id=str(row["project_id"]),
        dataset_id=str(row["dataset_id"]),
        name=str(row["name"]),
        plugin_id=str(row["plugin_id"]),
        tool_name=str(row["tool_name"]),
        argument_mappings={
            str(key): str(value) for key, value in _json_object(row["argument_mappings"]).items()
        },
        input_schema=_json_object(row["input_schema"]),
        created_at=row["created_at"],  # type: ignore[arg-type]
        updated_at=row["updated_at"],  # type: ignore[arg-type]
    )


def _json_object(value: object) -> Mapping[str, object]:
    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, Mapping):
        raise DatasetValidationError("Stored JSON value must be an object.")
    return dict(parsed)


def _name(value: str, kind: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 160:
        raise DatasetValidationError(f"{kind} name must contain between 1 and 160 characters.")
    return normalized


def _records(
    inputs: Sequence[DatasetRecordInput], *, existing: Sequence[DatasetRecord] = ()
) -> tuple[DatasetRecord, ...]:
    existing_ids = {record.id for record in existing}
    used_ids: set[str] = set()
    records: list[DatasetRecord] = []
    for position, item in enumerate(inputs):
        if not _is_json_object(item.value):
            raise DatasetValidationError("Dataset Records must be JSON objects.")
        if item.id is not None and item.id not in existing_ids:
            raise DatasetValidationError("Dataset Record IDs are issued by Agent Hub.")
        record_id = item.id or str(uuid4())
        if record_id in used_ids:
            raise DatasetValidationError("Dataset Record IDs must be unique.")
        used_ids.add(record_id)
        if item.source_key is not None and len(item.source_key) > 240:
            raise DatasetValidationError(
                "Dataset Record source keys must contain at most 240 characters."
            )
        records.append(DatasetRecord(record_id, position, dict(item.value), item.source_key))
    return tuple(records)


def _is_json_object(value: Mapping[str, object]) -> bool:
    try:
        encoded = json.dumps(value, allow_nan=False)
    except (TypeError, ValueError):
        return False
    return isinstance(json.loads(encoded), dict)


def _mappings(value: Mapping[str, str]) -> Mapping[str, str]:
    if not value:
        raise DatasetValidationError("A Batch Definition must map at least one tool argument.")
    mappings: dict[str, str] = {}
    for argument, selector in value.items():
        if (
            not argument
            or "/" in argument
            or not isinstance(selector, str)
            or not selector.startswith("/")
        ):
            raise DatasetValidationError(
                "Mappings use top-level tool arguments and RFC 6901 JSON Pointers."
            )
        mappings[argument] = selector
    return mappings


def _validate_mappings(
    records: Sequence[DatasetRecord], mappings: Mapping[str, str], schema: Mapping[str, object]
) -> None:
    if not records:
        return
    validator = Draft202012Validator(schema)
    for record in records:
        arguments = {
            argument: _select(record.value, selector) for argument, selector in mappings.items()
        }
        try:
            validator.validate(arguments)
        except ValidationError as error:
            raise DatasetValidationError(
                "Dataset mappings do not satisfy the selected MCP tool input schema."
            ) from error


def _select(value: Mapping[str, object], selector: str) -> object:
    current: object = value
    for token in selector[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, Mapping) or token not in current:
            raise DatasetValidationError(
                "A Dataset mapping must identify a value in every Dataset Record."
            )
        current = current[token]
    return current


def create_postgres_dataset_module(
    settings: Settings, projects: ProjectModule, tool_schemas: ToolSchemaResolver
) -> DatasetModule:
    return DatasetModule(projects, PostgresDatasetStore(settings), tool_schemas)
