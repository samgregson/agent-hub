import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

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
    version: int = 1


class DatasetNotFound(Exception):
    """No Dataset is visible in the Project."""


class DatasetValidationError(Exception):
    """A Dataset violates its host-owned contract."""


class DatasetVersionConflict(DatasetValidationError):
    """The Dataset changed since the caller loaded its document version."""


class DatasetStore(Protocol):
    async def create_dataset(self, dataset: Dataset) -> Dataset: ...

    async def load_dataset(self, project_id: str, dataset_id: str) -> Dataset | None: ...

    async def list_datasets(self, project_id: str) -> Sequence[Dataset]: ...

    async def replace_dataset(self, dataset: Dataset) -> Dataset | None: ...

    async def delete_dataset(self, project_id: str, dataset_id: str) -> bool: ...


class DatasetModule:
    """Own Project Dataset validation and lifecycle."""

    def __init__(
        self,
        projects: ProjectModule,
        store: DatasetStore,
    ) -> None:
        self._projects = projects
        self._store = store

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
                version=1,
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
        expected_version: int | None = None,
    ) -> Dataset:
        current = await self.load_dataset(access, project_id, dataset_id)
        if expected_version is not None and current.version != expected_version:
            raise DatasetVersionConflict("Dataset version has changed.")
        updated = Dataset(
            id=current.id,
            project_id=current.project_id,
            name=_name(name, "Dataset"),
            records=_records(records, existing=current.records),
            created_at=current.created_at,
            updated_at=datetime.now(UTC),
            version=current.version + 1,
        )
        saved = await self._store.replace_dataset(updated)
        if saved is None:
            raise DatasetNotFound
        return saved

    async def delete_dataset(self, access: ProjectAccess, project_id: str, dataset_id: str) -> None:
        await self._authorize(access, project_id)
        if not await self._store.delete_dataset(project_id, dataset_id):
            raise DatasetNotFound

    async def _authorize(self, access: ProjectAccess, project_id: str) -> None:
        try:
            await self._projects.load(access, project_id)
        except ProjectNotFound as error:
            raise DatasetNotFound from error


class MemoryDatasetStore:
    def __init__(self) -> None:
        self._datasets: dict[tuple[str, str], Dataset] = {}

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
        self._check_file_size(dataset)
        connection = await self._connect()
        async with connection:
            await connection.execute(
                "SELECT 1 FROM projects WHERE id=%s FOR UPDATE", (dataset.project_id,)
            )
            count = await connection.execute(
                "SELECT count(*) AS count FROM project_files WHERE project_id=%s",
                (dataset.project_id,),
            )
            count_row = await count.fetchone()
            assert count_row is not None
            if int(str(count_row["count"])) >= self._settings.project_file_max_files:
                raise DatasetValidationError("Project file-count limit reached.")
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
        self._check_file_size(dataset)
        connection = await self._connect()
        async with connection:
            existing = await _load_dataset(connection, dataset.project_id, dataset.id)
            if existing is None:
                return None
            await _write_dataset(connection, dataset, replace=True)
        return dataset

    def _check_file_size(self, dataset: Dataset) -> None:
        if len(_dataset_content(dataset).encode("utf-8")) > self._settings.project_file_max_bytes:
            raise DatasetValidationError("Dataset exceeds the Project file size limit.")

    async def delete_dataset(self, project_id: str, dataset_id: str) -> bool:
        connection = await self._connect()
        async with connection:
            await connection.execute(
                "DELETE FROM project_files WHERE project_id=%s AND path=%s",
                (project_id, _dataset_path(dataset_id)),
            )
            cursor = await connection.execute(
                "DELETE FROM datasets WHERE project_id=%s AND dataset_id=%s RETURNING dataset_id",
                (project_id, dataset_id),
            )
            return await cursor.fetchone() is not None


async def _write_dataset(
    connection: AsyncConnection[dict[str, object]], dataset: Dataset, *, replace: bool
) -> None:
    content = _dataset_content(dataset)
    path = _dataset_path(dataset.id)
    if replace:
        file = await connection.execute(
            """UPDATE project_files SET content=%s, version=version+1, updated_at=%s
            WHERE project_id=%s AND path=%s AND version=%s RETURNING version""",
            (content, dataset.updated_at, dataset.project_id, path, dataset.version - 1),
        )
        if await file.fetchone() is None:
            raise DatasetVersionConflict("Dataset version has changed.")
        await connection.execute(
            "UPDATE datasets SET name=%s, updated_at=%s WHERE project_id=%s AND dataset_id=%s",
            (dataset.name, dataset.updated_at, dataset.project_id, dataset.id),
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
        await connection.execute(
            """INSERT INTO project_files
            (project_id,path,content,version,created_at,updated_at)
            VALUES (%s,%s,%s,1,%s,%s)""",
            (
                dataset.project_id,
                path,
                content,
                dataset.created_at,
                dataset.updated_at,
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
        "SELECT content, version FROM project_files WHERE project_id=%s AND path=%s",
        (project_id, _dataset_path(dataset_id)),
    )
    file = await cursor.fetchone()
    if file is None:
        raise DatasetValidationError("Registered Dataset file is missing.")
    document = _json_object(file["content"])
    if document.get("kind") != "dataset" or document.get("id") != dataset_id:
        raise DatasetValidationError("Registered Dataset file is invalid.")
    raw_records = document.get("records")
    if not isinstance(raw_records, list):
        raise DatasetValidationError("Registered Dataset Records are invalid.")
    records = tuple(
        DatasetRecord(
            id=str(record["id"]),
            position=int(str(record["position"])),
            source_key=(str(record["sourceKey"]) if record.get("sourceKey") is not None else None),
            value=_json_object(record["value"]),
        )
        for record in raw_records
    )
    return Dataset(
        id=str(dataset["dataset_id"]),
        project_id=str(dataset["project_id"]),
        name=str(document["name"]),
        records=records,
        created_at=dataset["created_at"],  # type: ignore[arg-type]
        updated_at=dataset["updated_at"],  # type: ignore[arg-type]
        version=int(str(file["version"])),
    )


def _dataset_path(dataset_id: str) -> str:
    return f"/.datasets/{dataset_id}.json"


def _dataset_content(dataset: Dataset) -> str:
    return json.dumps(
        {
            "kind": "dataset",
            "schemaVersion": 1,
            "id": dataset.id,
            "name": dataset.name,
            "records": [
                {
                    "id": record.id,
                    "position": record.position,
                    "sourceKey": record.source_key,
                    "value": record.value,
                }
                for record in dataset.records
            ],
        },
        allow_nan=False,
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


def create_postgres_dataset_module(settings: Settings, projects: ProjectModule) -> DatasetModule:
    return DatasetModule(projects, PostgresDatasetStore(settings))
