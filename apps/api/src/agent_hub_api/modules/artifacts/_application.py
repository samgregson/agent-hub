import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from agent_hub_api.contracts import ArtifactDocument, EntityId
from agent_hub_api.modules.project_files import ARTIFACT_ROOT
from agent_hub_api.modules.projects import ProjectAccess, ProjectModule, ProjectNotFound
from agent_hub_api.settings import Settings


@dataclass(frozen=True, slots=True)
class ArtifactAccess:
    subject: str


@dataclass(frozen=True, slots=True)
class ArtifactMutationAccess(ArtifactAccess):
    thread_id: str
    run_id: str


@dataclass(frozen=True, slots=True)
class ArtifactDraft:
    type: str
    title: str
    plugin_id: str
    plugin_version: str
    schema_id: str
    schema_version: str
    payload: Mapping[str, Any]
    summary: str | None = None


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    project_id: str
    document: ArtifactDocument


class ArtifactNotFound(Exception):
    """The Artifact is absent from the caller's authorized Project."""


class ArtifactVersionConflict(Exception):
    """The supplied version is no longer the canonical current document."""


class ArtifactAuthorityError(Exception):
    """A Plugin replacement changed a field owned by Agent Hub."""


class ArtifactStore(Protocol):
    async def create(self, record: ArtifactRecord) -> ArtifactRecord: ...

    async def load(self, project_id: str, artifact_id: str) -> ArtifactRecord | None: ...

    async def list(self, project_id: str) -> Sequence[ArtifactRecord]: ...

    async def replace(
        self, project_id: str, artifact_id: str, document: ArtifactDocument
    ) -> ArtifactRecord | None: ...


class ArtifactModule:
    """Own portable Artifact documents and restore host authority before persistence."""

    def __init__(self, projects: ProjectModule, store: ArtifactStore) -> None:
        self._projects = projects
        self._store = store

    async def create(
        self, access: ArtifactMutationAccess, project_id: str, draft: ArtifactDraft
    ) -> ArtifactDocument:
        await self._authorize(access, project_id)
        document = ArtifactDocument.model_validate(
            {
                "artifact": {
                    "id": str(uuid4()),
                    "type": draft.type,
                    "documentVersion": 1,
                    "title": draft.title,
                    "summary": draft.summary,
                    "schema": {"id": draft.schema_id, "version": draft.schema_version},
                    "plugin": {"id": draft.plugin_id, "version": draft.plugin_version},
                    "provenance": {
                        "createdByThreadId": access.thread_id,
                        "createdByRunId": access.run_id,
                        "lastChangedByThreadId": access.thread_id,
                        "lastChangedByRunId": access.run_id,
                    },
                    "relations": [],
                },
                "payload": dict(draft.payload),
            }
        )
        return (await self._store.create(ArtifactRecord(project_id, document))).document

    async def load(
        self, access: ArtifactAccess, project_id: str, artifact_id: str
    ) -> ArtifactDocument:
        await self._authorize(access, project_id)
        record = await self._store.load(project_id, artifact_id)
        if record is None:
            raise ArtifactNotFound
        return record.document

    async def discover(
        self, access: ArtifactAccess, project_id: str
    ) -> tuple[ArtifactDocument, ...]:
        await self._authorize(access, project_id)
        return tuple(record.document for record in await self._store.list(project_id))

    async def replace(
        self,
        access: ArtifactMutationAccess,
        project_id: str,
        artifact_id: str,
        expected_version: int,
        replacement: ArtifactDocument,
    ) -> ArtifactDocument:
        current = await self.load(access, project_id, artifact_id)
        if current.artifact.document_version != expected_version:
            raise ArtifactVersionConflict
        replacement = ArtifactDocument.model_validate(replacement.model_dump(by_alias=True))
        _require_same_plugin_binding(current, replacement)
        artifact = replacement.artifact.model_copy(
            update={
                "id": current.artifact.id,
                "document_version": current.artifact.document_version + 1,
                "provenance": current.artifact.provenance.model_copy(
                    update={
                        "last_changed_by_thread_id": EntityId.model_validate(access.thread_id),
                        "last_changed_by_run_id": EntityId.model_validate(access.run_id),
                    }
                ),
                "relations": current.artifact.relations,
            }
        )
        saved = await self._store.replace(
            project_id,
            artifact_id,
            ArtifactDocument.model_validate(
                {"artifact": artifact.model_dump(by_alias=True), "payload": replacement.payload}
            ),
        )
        if saved is None:
            raise ArtifactNotFound
        return saved.document

    async def _authorize(self, access: ArtifactAccess, project_id: str) -> None:
        try:
            await self._projects.load(ProjectAccess(subject=access.subject), project_id)
        except ProjectNotFound as error:
            raise ArtifactNotFound from error


def _require_same_plugin_binding(current: ArtifactDocument, replacement: ArtifactDocument) -> None:
    if (
        current.artifact.type != replacement.artifact.type
        or current.artifact.schema_ != replacement.artifact.schema_
        or current.artifact.plugin != replacement.artifact.plugin
    ):
        raise ArtifactAuthorityError("A Plugin cannot change an Artifact binding.")


class MemoryArtifactStore:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str], ArtifactRecord] = {}

    async def create(self, record: ArtifactRecord) -> ArtifactRecord:
        self._records[(record.project_id, record.document.artifact.id.root)] = record
        return record

    async def load(self, project_id: str, artifact_id: str) -> ArtifactRecord | None:
        return self._records.get((project_id, artifact_id))

    async def list(self, project_id: str) -> Sequence[ArtifactRecord]:
        return tuple(
            record
            for (owner, _), record in sorted(self._records.items())
            if owner == project_id
        )

    async def replace(
        self, project_id: str, artifact_id: str, document: ArtifactDocument
    ) -> ArtifactRecord | None:
        key = (project_id, artifact_id)
        if key not in self._records:
            return None
        record = ArtifactRecord(project_id, document)
        self._records[key] = record
        return record


class PostgresArtifactStore:
    """Keep one canonical Artifact document in the reserved Project VFS namespace.

    ``artifact_catalog`` is an indexed projection of the host envelope. It is
    intentionally not a second copy of the portable document.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def _connect(self) -> AsyncConnection[dict[str, object]]:
        return await AsyncConnection.connect(
            str(self._settings.database_url),
            connect_timeout=self._settings.database_connect_timeout_seconds,
            row_factory=dict_row,
        )

    async def create(self, record: ArtifactRecord) -> ArtifactRecord:
        document = record.document
        artifact = document.artifact
        path = _artifact_path(artifact.id.root)
        content = _serialize_document(document)
        connection = await self._connect()
        async with connection:
            project = await connection.execute(
                "SELECT 1 FROM projects WHERE id = %s FOR UPDATE", (record.project_id,)
            )
            if await project.fetchone() is None:
                raise ArtifactNotFound
            await connection.execute(
                """
                INSERT INTO project_files
                    (project_id, path, content, version, created_at, updated_at)
                VALUES (%s, %s, %s, %s, now(), now())
                """,
                (record.project_id, path, content, artifact.document_version),
            )
            await connection.execute(
                """
                INSERT INTO artifact_catalog
                    (project_id, artifact_id, path, document_version, type, title, summary,
                     plugin_id, plugin_version, schema_id, schema_version,
                     created_by_thread_id, created_by_run_id,
                     last_changed_by_thread_id, last_changed_by_run_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    record.project_id,
                    artifact.id.root,
                    path,
                    artifact.document_version,
                    artifact.type,
                    artifact.title,
                    artifact.summary,
                    artifact.plugin.id,
                    artifact.plugin.version,
                    artifact.schema_.id,
                    artifact.schema_.version,
                    artifact.provenance.created_by_thread_id.root,
                    artifact.provenance.created_by_run_id.root,
                    artifact.provenance.last_changed_by_thread_id.root,
                    artifact.provenance.last_changed_by_run_id.root,
                ),
            )
        return record

    async def load(self, project_id: str, artifact_id: str) -> ArtifactRecord | None:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """
                SELECT project_files.content
                FROM artifact_catalog
                JOIN project_files
                  ON project_files.project_id = artifact_catalog.project_id
                 AND project_files.path = artifact_catalog.path
                WHERE artifact_catalog.project_id = %s AND artifact_catalog.artifact_id = %s
                """,
                (project_id, artifact_id),
            )
            row = await cursor.fetchone()
        return None if row is None else ArtifactRecord(project_id, _document_from_row(row))

    async def list(self, project_id: str) -> Sequence[ArtifactRecord]:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """
                SELECT project_files.content
                FROM artifact_catalog
                JOIN project_files
                  ON project_files.project_id = artifact_catalog.project_id
                 AND project_files.path = artifact_catalog.path
                WHERE artifact_catalog.project_id = %s
                ORDER BY artifact_catalog.title, artifact_catalog.artifact_id
                """,
                (project_id,),
            )
            rows = await cursor.fetchall()
        return tuple(ArtifactRecord(project_id, _document_from_row(row)) for row in rows)

    async def replace(
        self, project_id: str, artifact_id: str, document: ArtifactDocument
    ) -> ArtifactRecord | None:
        artifact = document.artifact
        expected_version = artifact.document_version - 1
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """
                UPDATE artifact_catalog
                SET document_version = %s, title = %s, summary = %s,
                    last_changed_by_thread_id = %s, last_changed_by_run_id = %s,
                    updated_at = now()
                WHERE project_id = %s AND artifact_id = %s AND document_version = %s
                RETURNING path
                """,
                (
                    artifact.document_version,
                    artifact.title,
                    artifact.summary,
                    artifact.provenance.last_changed_by_thread_id.root,
                    artifact.provenance.last_changed_by_run_id.root,
                    project_id,
                    artifact_id,
                    expected_version,
                ),
            )
            row = await cursor.fetchone()
            if row is None:
                raise ArtifactVersionConflict
            path = row["path"]
            assert isinstance(path, str)
            await connection.execute(
                """
                UPDATE project_files
                SET content = %s, version = %s, updated_at = now()
                WHERE project_id = %s AND path = %s
                """,
                (
                    _serialize_document(document),
                    artifact.document_version,
                    project_id,
                    path,
                ),
            )
        return ArtifactRecord(project_id, document)


def _artifact_path(artifact_id: str) -> str:
    return f"{ARTIFACT_ROOT}/{artifact_id}.json"


def _serialize_document(document: ArtifactDocument) -> str:
    return json.dumps(document.model_dump(by_alias=True), separators=(",", ":"))


def _document_from_row(row: Mapping[str, object]) -> ArtifactDocument:
    content = row["content"]
    assert isinstance(content, str)
    return ArtifactDocument.model_validate(json.loads(content))


def create_memory_artifact_module(projects: ProjectModule) -> ArtifactModule:
    return ArtifactModule(projects, MemoryArtifactStore())


def create_postgres_artifact_module(settings: Settings, projects: ProjectModule) -> ArtifactModule:
    return ArtifactModule(projects, PostgresArtifactStore(settings))
