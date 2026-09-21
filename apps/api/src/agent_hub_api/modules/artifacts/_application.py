import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from agent_hub_api.contracts import ArtifactDocument, ArtifactProvenanceActor
from agent_hub_api.modules.plugin_gateway import (
    PluginSelection,
    PluginToolResult,
    PluginUiResource,
)
from agent_hub_api.modules.project_files import ARTIFACT_ROOT
from agent_hub_api.modules.projects import ProjectAccess, ProjectModule, ProjectNotFound
from agent_hub_api.settings import Settings


@dataclass(frozen=True, slots=True)
class ArtifactAccess:
    subject: str


@dataclass(frozen=True, slots=True)
class ArtifactMutationAccess(ArtifactAccess):
    """Trusted provenance for a change initiated by one Agent Run."""

    thread_id: str
    run_id: str


@dataclass(frozen=True, slots=True)
class ArtifactUserActionAccess(ArtifactAccess):
    """Trusted provenance for one direct, user-initiated Artifact action."""

    user_action_id: str


ArtifactWriteAccess = ArtifactMutationAccess | ArtifactUserActionAccess

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


class ArtifactPluginUnavailable(Exception):
    """The requested Plugin is not enabled in the authorized Project."""


class ArtifactPluginDraftInvalid(Exception):
    """The Plugin did not return a usable portable Artifact draft."""


class ArtifactPluginReplacementInvalid(Exception):
    """The Plugin did not return a usable portable Artifact replacement."""


class ArtifactAppUnavailable(Exception):
    """The Artifact's reviewed MCP App cannot be safely rendered."""


class ArtifactPluginGateway(Protocol):
    async def selections(
        self, access: ProjectAccess, project_id: str
    ) -> Sequence[PluginSelection]: ...

    async def call(
        self,
        access: ProjectAccess,
        project_id: str,
        plugin_id: str,
        tool_name: str,
        arguments: Mapping[str, object],
    ) -> PluginToolResult: ...

    async def read_ui_resource(
        self,
        access: ProjectAccess,
        project_id: str,
        plugin_id: str,
        resource_uri: str,
    ) -> PluginUiResource: ...


class ArtifactStore(Protocol):
    async def create(self, record: ArtifactRecord) -> ArtifactRecord: ...

    async def load(self, project_id: str, artifact_id: str) -> ArtifactRecord | None: ...

    async def list(self, project_id: str) -> Sequence[ArtifactRecord]: ...

    async def replace(
        self, project_id: str, artifact_id: str, document: ArtifactDocument
    ) -> ArtifactRecord | None: ...

    async def delete(self, project_id: str, artifact_id: str) -> bool: ...


class ArtifactModule:
    """Own portable Artifact documents and restore host authority before persistence."""

    def __init__(
        self,
        projects: ProjectModule,
        store: ArtifactStore,
        plugin_gateway: ArtifactPluginGateway | None = None,
    ) -> None:
        self._projects = projects
        self._store = store
        self._plugin_gateway = plugin_gateway

    async def create(
        self, access: ArtifactWriteAccess, project_id: str, draft: ArtifactDraft
    ) -> ArtifactDocument:
        await self._authorize(access, project_id)
        actor = _provenance_actor(access)
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
                        "createdBy": actor.model_dump(by_alias=True),
                        "lastChangedBy": actor.model_dump(by_alias=True),
                    },
                    "relations": [],
                },
                "payload": dict(draft.payload),
            }
        )
        return (await self._store.create(ArtifactRecord(project_id, document))).document

    async def create_from_plugin(
        self,
        access: ArtifactWriteAccess,
        project_id: str,
        *,
        plugin_id: str,
        tool_name: str,
        arguments: Mapping[str, object],
    ) -> ArtifactDocument:
        """Persist an enabled Plugin's portable draft with host-owned fields."""
        await self._authorize(access, project_id)
        selection = await self._enabled_plugin(access, project_id, plugin_id)
        assert self._plugin_gateway is not None
        result = await self._plugin_gateway.call(
            ProjectAccess(subject=access.subject),
            project_id,
            plugin_id,
            tool_name,
            arguments,
        )
        return await self.create(
            access,
            project_id,
            _draft_from_plugin_result(result, selection.manifest.id, selection.manifest.version),
        )

    async def apply_plugin_operation(
        self,
        access: ArtifactWriteAccess,
        project_id: str,
        artifact_id: str,
        *,
        expected_version: int,
        tool_name: str,
        arguments: Mapping[str, object],
    ) -> ArtifactDocument:
        """Apply a Plugin's complete replacement to one current Artifact document."""
        current = await self.load(access, project_id, artifact_id)
        selection = await self._enabled_plugin(access, project_id, current.artifact.plugin.id)
        if selection.manifest.version != current.artifact.plugin.version:
            raise ArtifactPluginUnavailable
        if "document" in arguments:
            raise ArtifactPluginReplacementInvalid(
                "The host, rather than the caller, supplies the current Artifact document."
            )
        assert self._plugin_gateway is not None
        result = await self._plugin_gateway.call(
            ProjectAccess(subject=access.subject),
            project_id,
            selection.manifest.id,
            tool_name,
            {"document": current.model_dump(by_alias=True), **arguments},
        )
        if result.structured_content is None:
            raise ArtifactPluginReplacementInvalid(
                "The Plugin result did not include a structured Artifact replacement."
            )
        try:
            replacement = ArtifactDocument.model_validate(result.structured_content)
        except ValueError as error:
            raise ArtifactPluginReplacementInvalid(
                "The Plugin result has an invalid Artifact replacement."
            ) from error
        return await self.replace(
            access,
            project_id,
            artifact_id,
            expected_version,
            replacement,
        )

    async def app_resource(
        self, access: ArtifactAccess, project_id: str, artifact_id: str
    ) -> PluginUiResource:
        """Resolve the single reviewed App resource for an authorized Artifact."""
        current = await self.load(access, project_id, artifact_id)
        selection = await self._enabled_plugin(access, project_id, current.artifact.plugin.id)
        if (
            selection.manifest.version != current.artifact.plugin.version
            or selection.manifest.app_resource_uri is None
        ):
            raise ArtifactAppUnavailable
        assert self._plugin_gateway is not None
        try:
            return await self._plugin_gateway.read_ui_resource(
                ProjectAccess(subject=access.subject),
                project_id,
                selection.manifest.id,
                selection.manifest.app_resource_uri,
            )
        except Exception as error:
            raise ArtifactAppUnavailable from error

    async def apply_app_operation(
        self,
        access: ArtifactUserActionAccess,
        project_id: str,
        artifact_id: str,
        *,
        expected_version: int,
        tool_name: str,
        arguments: Mapping[str, object],
    ) -> ArtifactDocument:
        """Apply the narrowly allowed semantic operation requested by a mounted App."""
        current = await self.load(access, project_id, artifact_id)
        selection = await self._enabled_plugin(access, project_id, current.artifact.plugin.id)
        if tool_name not in selection.manifest.app_tool_names:
            raise ArtifactAppUnavailable
        return await self.apply_plugin_operation(
            access,
            project_id,
            artifact_id,
            expected_version=expected_version,
            tool_name=tool_name,
            arguments=arguments,
        )

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

    async def delete(self, access: ArtifactAccess, project_id: str, artifact_id: str) -> None:
        await self._authorize(access, project_id)
        if not await self._store.delete(project_id, artifact_id):
            raise ArtifactNotFound

    async def replace(
        self,
        access: ArtifactWriteAccess,
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
                    update={"last_changed_by": _provenance_actor(access)}
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

    async def _enabled_plugin(
        self, access: ArtifactAccess, project_id: str, plugin_id: str
    ) -> PluginSelection:
        if self._plugin_gateway is None:
            raise ArtifactPluginUnavailable
        selections = await self._plugin_gateway.selections(
            ProjectAccess(subject=access.subject), project_id
        )
        selection = next(
            (
                candidate
                for candidate in selections
                if candidate.enabled and candidate.manifest.id == plugin_id
            ),
            None,
        )
        if selection is None:
            raise ArtifactPluginUnavailable
        return selection


def _require_same_plugin_binding(current: ArtifactDocument, replacement: ArtifactDocument) -> None:
    if (
        current.artifact.type != replacement.artifact.type
        or current.artifact.schema_ != replacement.artifact.schema_
        or current.artifact.plugin != replacement.artifact.plugin
    ):
        raise ArtifactAuthorityError("A Plugin cannot change an Artifact binding.")


def _provenance_actor(access: ArtifactWriteAccess) -> ArtifactProvenanceActor:
    if isinstance(access, ArtifactMutationAccess):
        return ArtifactProvenanceActor.model_validate(
            {"kind": "agentRun", "threadId": access.thread_id, "runId": access.run_id}
        )
    return ArtifactProvenanceActor.model_validate(
        {"kind": "userAction", "userActionId": access.user_action_id}
    )


def _catalog_actor_values(actor: Any) -> tuple[str, str | None, str | None, str | None]:
    return (
        actor.kind,
        actor.thread_id.root if actor.thread_id else None,
        actor.run_id.root if actor.run_id else None,
        actor.user_action_id.root if actor.user_action_id else None,
    )


def _draft_from_plugin_result(
    result: PluginToolResult, plugin_id: str, plugin_version: str
) -> ArtifactDraft:
    value = result.structured_content
    if value is None:
        raise ArtifactPluginDraftInvalid(
            "The Plugin result did not include a structured Artifact draft."
        )
    type_ = value.get("type")
    title = value.get("title")
    summary = value.get("summary")
    schema = value.get("schema")
    payload = value.get("payload")
    if (
        not isinstance(type_, str)
        or not isinstance(title, str)
        or not isinstance(summary, str | type(None))
        or not isinstance(schema, Mapping)
        or not isinstance(payload, Mapping)
    ):
        raise ArtifactPluginDraftInvalid("The Plugin result has an invalid Artifact draft shape.")
    schema_id = schema.get("id")
    schema_version = schema.get("version")
    if not isinstance(schema_id, str) or not isinstance(schema_version, str):
        raise ArtifactPluginDraftInvalid(
            "The Plugin result has an invalid Artifact schema binding."
        )
    return ArtifactDraft(
        type=type_,
        title=title,
        summary=summary,
        plugin_id=plugin_id,
        plugin_version=plugin_version,
        schema_id=schema_id,
        schema_version=schema_version,
        payload=dict(payload),
    )


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

    async def delete(self, project_id: str, artifact_id: str) -> bool:
        return self._records.pop((project_id, artifact_id), None) is not None


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
        created_by = _catalog_actor_values(artifact.provenance.created_by)
        last_changed_by = _catalog_actor_values(artifact.provenance.last_changed_by)
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
                     created_by_kind, created_by_thread_id, created_by_run_id,
                     created_by_user_action_id, last_changed_by_kind,
                     last_changed_by_thread_id, last_changed_by_run_id,
                     last_changed_by_user_action_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                    *created_by,
                    *last_changed_by,
                ),
            )
        return record

    async def delete(self, project_id: str, artifact_id: str) -> bool:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """
                DELETE FROM artifact_catalog
                WHERE project_id = %s AND artifact_id = %s
                RETURNING path
                """,
                (project_id, artifact_id),
            )
            row = await cursor.fetchone()
            if row is None:
                return False
            path = row["path"]
            assert isinstance(path, str)
            await connection.execute(
                "DELETE FROM project_files WHERE project_id = %s AND path = %s",
                (project_id, path),
            )
            return True

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
        last_changed_by = _catalog_actor_values(artifact.provenance.last_changed_by)
        expected_version = artifact.document_version - 1
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """
                UPDATE artifact_catalog
                SET document_version = %s, title = %s, summary = %s,
                    last_changed_by_kind = %s, last_changed_by_thread_id = %s,
                    last_changed_by_run_id = %s, last_changed_by_user_action_id = %s,
                    updated_at = now()
                WHERE project_id = %s AND artifact_id = %s AND document_version = %s
                RETURNING path
                """,
                (
                    artifact.document_version,
                    artifact.title,
                    artifact.summary,
                    *last_changed_by,
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


def create_memory_artifact_module(
    projects: ProjectModule, plugin_gateway: ArtifactPluginGateway | None = None
) -> ArtifactModule:
    return ArtifactModule(projects, MemoryArtifactStore(), plugin_gateway)


def create_postgres_artifact_module(
    settings: Settings,
    projects: ProjectModule,
    plugin_gateway: ArtifactPluginGateway | None = None,
) -> ArtifactModule:
    return ArtifactModule(projects, PostgresArtifactStore(settings), plugin_gateway)
