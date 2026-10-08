"""Host-owned Project File inputs for MCP Batch Definitions."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from typing import Protocol
from uuid import uuid4

from jsonschema import Draft202012Validator, ValidationError  # type: ignore[import-untyped]
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from agent_hub_api.modules.datasets import BatchDefinition, DatasetModule, DatasetNotFound
from agent_hub_api.modules.project_files import (
    ProjectFile,
    ProjectFileAccess,
    ProjectFileError,
    ProjectFilesModule,
)
from agent_hub_api.modules.projects import ProjectAccess, ProjectModule, ProjectNotFound
from agent_hub_api.settings import Settings

MAX_BOUND_FILE_BYTES = 64_000


@dataclass(frozen=True, slots=True)
class FileBinding:
    id: str
    project_id: str
    definition_id: str
    argument: str
    source_path: str
    expected_file_version: int
    created_at: datetime
    version: int = 1


@dataclass(frozen=True, slots=True)
class CapturedFileBinding:
    binding_id: str
    argument: str
    path: str
    version: int
    content: str
    sha256: str

    def snapshot(self) -> Mapping[str, object]:
        return {
            "bindingId": self.binding_id,
            "argument": self.argument,
            "sourcePath": self.path,
            "sourceVersion": self.version,
            "content": self.content,
            "sha256": self.sha256,
            "cardinality": "scalar-to-selected-records",
        }


class BindingUnavailable(Exception):
    """The declared Binding cannot safely supply this invocation."""


class BindingStore(Protocol):
    async def create(self, binding: FileBinding) -> FileBinding: ...
    async def load(self, project_id: str, definition_id: str) -> FileBinding | None: ...
    async def replace(self, binding: FileBinding, expected_version: int) -> FileBinding: ...


class BindingModule:
    def __init__(
        self,
        projects: ProjectModule,
        datasets: DatasetModule,
        files: ProjectFilesModule,
        store: BindingStore,
    ) -> None:
        self._projects = projects
        self._datasets = datasets
        self._files = files
        self._store = store

    async def bind_file(
        self,
        access: ProjectAccess,
        project_id: str,
        definition_id: str,
        source_path: str,
        expected_file_version: int,
    ) -> FileBinding:
        definition = await self._definition(access, project_id, definition_id)
        if definition.file_argument is None or definition.transform_definition_id is not None:
            raise BindingUnavailable("Batch Definition has no file argument.")
        if await self._store.load(project_id, definition_id) is not None:
            raise BindingUnavailable("A file Binding already exists for this Batch Definition.")
        file = await self._file(access, project_id, source_path, expected_file_version)
        _validate_content(definition, file.content)
        return await self._store.create(
            FileBinding(
                id=str(uuid4()),
                project_id=project_id,
                definition_id=definition_id,
                argument=definition.file_argument,
                source_path=file.path,
                expected_file_version=file.version,
                created_at=datetime.now(UTC),
            )
        )

    async def load(self, access: ProjectAccess, project_id: str, definition_id: str) -> FileBinding:
        await self._definition(access, project_id, definition_id)
        binding = await self._store.load(project_id, definition_id)
        if binding is None:
            raise BindingUnavailable("The Batch Definition has no file Binding.")
        return binding

    async def rebind_file(
        self,
        access: ProjectAccess,
        project_id: str,
        definition_id: str,
        source_path: str,
        expected_file_version: int,
        *,
        expected_binding_version: int,
    ) -> FileBinding:
        definition = await self._definition(access, project_id, definition_id)
        binding = await self._store.load(project_id, definition_id)
        if binding is None or binding.argument != definition.file_argument:
            raise BindingUnavailable("The Batch Definition has no current file Binding.")
        if binding.version != expected_binding_version:
            raise BindingUnavailable("The Binding version changed; reload before editing.")
        file = await self._file(access, project_id, source_path, expected_file_version)
        _validate_content(definition, file.content)
        return await self._store.replace(
            replace(
                binding,
                source_path=file.path,
                expected_file_version=file.version,
                version=binding.version + 1,
            ),
            expected_binding_version,
        )

    async def capture(
        self, access: ProjectAccess, project_id: str, definition: BatchDefinition
    ) -> CapturedFileBinding | None:
        await self._authorize(access, project_id)
        if definition.project_id != project_id:
            raise BindingUnavailable("Batch Definition is outside this Project.")
        if definition.file_argument is None:
            return None
        binding = await self._store.load(project_id, definition.id)
        if binding is None or binding.argument != definition.file_argument:
            raise BindingUnavailable("The Batch Definition needs a current file Binding.")
        file = await self._file(
            access, project_id, binding.source_path, binding.expected_file_version
        )
        _validate_content(definition, file.content)
        return CapturedFileBinding(
            binding.id,
            binding.argument,
            file.path,
            file.version,
            file.content,
            sha256(file.content.encode("utf-8")).hexdigest(),
        )

    async def _authorize(self, access: ProjectAccess, project_id: str) -> None:
        try:
            await self._projects.load(access, project_id)
        except ProjectNotFound as error:
            raise BindingUnavailable("Project is unavailable.") from error

    async def _definition(
        self, access: ProjectAccess, project_id: str, definition_id: str
    ) -> BatchDefinition:
        await self._authorize(access, project_id)
        try:
            return await self._datasets.load_definition(access, project_id, definition_id)
        except DatasetNotFound as error:
            raise BindingUnavailable("Batch Definition is unavailable.") from error

    async def _file(
        self, access: ProjectAccess, project_id: str, path: str, version: int
    ) -> ProjectFile:
        if path.startswith(("/.datasets/", "/.artifacts/")):
            raise BindingUnavailable("Only ordinary Project Files can be bound.")
        try:
            file = await self._files.preview(
                ProjectFileAccess(subject=access.subject), project_id, path
            )
        except ProjectFileError as error:
            raise BindingUnavailable("The bound Project File is unavailable.") from error
        if file.version != version:
            raise BindingUnavailable("The bound Project File changed; review and rebind it.")
        if len(file.content.encode("utf-8")) > MAX_BOUND_FILE_BYTES:
            raise BindingUnavailable("The bound Project File exceeds the 64 KB input limit.")
        return file


class MemoryBindingStore:
    def __init__(self) -> None:
        self._bindings: dict[tuple[str, str], FileBinding] = {}

    async def create(self, binding: FileBinding) -> FileBinding:
        key = (binding.project_id, binding.definition_id)
        if key in self._bindings:
            raise BindingUnavailable("A file Binding already exists for this Batch Definition.")
        self._bindings[key] = binding
        return binding

    async def load(self, project_id: str, definition_id: str) -> FileBinding | None:
        return self._bindings.get((project_id, definition_id))

    async def replace(self, binding: FileBinding, expected_version: int) -> FileBinding:
        key = (binding.project_id, binding.definition_id)
        current = self._bindings.get(key)
        if current is None or current.version != expected_version:
            raise BindingUnavailable("The Binding version changed; reload before editing.")
        self._bindings[key] = binding
        return binding


class PostgresBindingStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def _connect(self) -> AsyncConnection[dict[str, object]]:
        return await AsyncConnection.connect(
            str(self._settings.database_url),
            connect_timeout=self._settings.database_connect_timeout_seconds,
            row_factory=dict_row,
        )

    async def create(self, binding: FileBinding) -> FileBinding:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """INSERT INTO file_bindings
                (project_id, binding_id, batch_definition_id, argument, source_path,
                 expected_file_version, created_at, version)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (project_id, batch_definition_id) DO NOTHING
                RETURNING binding_id""",
                (
                    binding.project_id,
                    binding.id,
                    binding.definition_id,
                    binding.argument,
                    binding.source_path,
                    binding.expected_file_version,
                    binding.created_at,
                    binding.version,
                ),
            )
            if await cursor.fetchone() is None:
                raise BindingUnavailable("A file Binding already exists for this Batch Definition.")
        return binding

    async def load(self, project_id: str, definition_id: str) -> FileBinding | None:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """SELECT * FROM file_bindings
                WHERE project_id=%s AND batch_definition_id=%s""",
                (project_id, definition_id),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return FileBinding(
            id=str(row["binding_id"]),
            project_id=str(row["project_id"]),
            definition_id=str(row["batch_definition_id"]),
            argument=str(row["argument"]),
            source_path=str(row["source_path"]),
            expected_file_version=int(str(row["expected_file_version"])),
            created_at=row["created_at"],  # type: ignore[arg-type]
            version=int(str(row["version"])),
        )

    async def replace(self, binding: FileBinding, expected_version: int) -> FileBinding:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """UPDATE file_bindings SET source_path=%s, expected_file_version=%s,
                version=version+1 WHERE project_id=%s AND batch_definition_id=%s
                AND version=%s RETURNING version""",
                (
                    binding.source_path,
                    binding.expected_file_version,
                    binding.project_id,
                    binding.definition_id,
                    expected_version,
                ),
            )
            if await cursor.fetchone() is None:
                raise BindingUnavailable("The Binding version changed; reload before editing.")
        return binding


def create_postgres_binding_module(
    settings: Settings,
    projects: ProjectModule,
    datasets: DatasetModule,
    files: ProjectFilesModule,
) -> BindingModule:
    return BindingModule(projects, datasets, files, PostgresBindingStore(settings))


def _validate_content(definition: BatchDefinition, content: str) -> None:
    properties = definition.input_schema.get("properties")
    if not isinstance(properties, Mapping) or definition.file_argument not in properties:
        raise BindingUnavailable("The target MCP tool no longer declares the file argument.")
    argument_schema = properties[definition.file_argument]
    if not isinstance(argument_schema, Mapping):
        raise BindingUnavailable("The MCP tool file argument schema is invalid.")
    try:
        Draft202012Validator(argument_schema).validate(content)
    except ValidationError as error:
        raise BindingUnavailable(
            "Project File content does not satisfy the MCP argument schema."
        ) from error
