from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4

from agent_hub_api.contracts import ArtifactDocument, EntityId
from agent_hub_api.modules.projects import ProjectAccess, ProjectModule, ProjectNotFound


@dataclass(frozen=True, slots=True)
class ArtifactAccess:
    subject: str
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
        self, access: ArtifactAccess, project_id: str, draft: ArtifactDraft
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
        access: ArtifactAccess,
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


def create_memory_artifact_module(projects: ProjectModule) -> ArtifactModule:
    return ArtifactModule(projects, MemoryArtifactStore())
