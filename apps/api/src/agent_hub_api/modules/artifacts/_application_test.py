import pytest

from agent_hub_api.contracts import EntityId
from agent_hub_api.modules.artifacts import (
    ArtifactAuthorityError,
    ArtifactDraft,
    ArtifactMutationAccess,
    ArtifactVersionConflict,
    create_memory_artifact_module,
)
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module


def _draft(payload: dict[str, object] | None = None) -> ArtifactDraft:
    return ArtifactDraft(
        type="agent-hub.fixture.status",
        title="Foundation status",
        plugin_id="foundation-fixture",
        plugin_version="0.1.0",
        schema_id="agent-hub.fixture.status",
        schema_version="1.0",
        payload=payload or {"status": "available"},
    )


@pytest.mark.asyncio
async def test_artifact_replacement_preserves_host_fields_and_increments_version() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="sam")
    project = await projects.create(owner, "Bridge")
    artifacts = create_memory_artifact_module(projects)
    creator = ArtifactMutationAccess(subject="sam", thread_id="thread-a", run_id="run-a")
    created = await artifacts.create(creator, project.id, _draft())
    replacement = created.model_copy(
        update={
            "artifact": created.artifact.model_copy(
                update={
                    "document_version": 999,
                    "provenance": created.artifact.provenance.model_copy(
                        update={"created_by_run_id": EntityId.model_validate("forged")}
                    ),
                    "relations": [],
                }
            ),
            "payload": {"status": "updated"},
        }
    )

    saved = await artifacts.replace(
        ArtifactMutationAccess(subject="sam", thread_id="thread-b", run_id="run-b"),
        project.id,
        created.artifact.id.root,
        expected_version=1,
        replacement=replacement,
    )

    assert saved.payload == {"status": "updated"}
    assert saved.artifact.id == created.artifact.id
    assert saved.artifact.document_version == 2
    assert saved.artifact.provenance.created_by_run_id.root == "run-a"
    assert saved.artifact.provenance.last_changed_by_thread_id.root == "thread-b"
    assert saved.artifact.provenance.last_changed_by_run_id.root == "run-b"


@pytest.mark.asyncio
async def test_artifact_replacement_rejects_stale_or_rebound_documents() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="sam")
    project = await projects.create(owner, "Bridge")
    artifacts = create_memory_artifact_module(projects)
    access = ArtifactMutationAccess(subject="sam", thread_id="thread-a", run_id="run-a")
    created = await artifacts.create(access, project.id, _draft())

    with pytest.raises(ArtifactVersionConflict):
        await artifacts.replace(
            access,
            project.id,
            created.artifact.id.root,
            expected_version=2,
            replacement=created,
        )

    rebound = created.model_copy(
        update={
            "artifact": created.artifact.model_copy(update={"type": "forged.type"})
        }
    )
    with pytest.raises(ArtifactAuthorityError):
        await artifacts.replace(
            access,
            project.id,
            created.artifact.id.root,
            expected_version=1,
            replacement=rebound,
        )
