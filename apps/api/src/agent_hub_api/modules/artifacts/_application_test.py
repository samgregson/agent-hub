import pytest

from agent_hub_api.contracts import EntityId
from agent_hub_api.modules.artifacts import (
    ArtifactAuthorityError,
    ArtifactDraft,
    ArtifactMutationAccess,
    ArtifactVersionConflict,
    create_memory_artifact_module,
)
from agent_hub_api.modules.plugin_gateway import (
    PluginManifest,
    PluginSelection,
    PluginTool,
    PluginToolResult,
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


class FixtureGateway:
    manifest = PluginManifest(
        id="foundation-fixture",
        name="Foundation fixture",
        version="0.1.0",
        endpoint="https://fixture.example/mcp",
        tools=(PluginTool(name="create_status_artifact", read_only=False),),
    )

    def __init__(self, result: PluginToolResult) -> None:
        self.result = result
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    async def selections(self, *_: object) -> tuple[PluginSelection, ...]:
        return (PluginSelection(manifest=self.manifest, enabled=True),)

    async def call(
        self, _: object, __: str, plugin_id: str, tool_name: str, arguments: dict[str, object]
    ) -> PluginToolResult:
        self.calls.append((plugin_id, tool_name, arguments))
        return self.result


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


@pytest.mark.asyncio
async def test_enabled_plugin_draft_is_saved_with_host_assigned_artifact_fields() -> None:
    projects = create_memory_project_module()
    project = await projects.create(ProjectAccess(subject="sam"), "Bridge")
    gateway = FixtureGateway(
        PluginToolResult(
            content=("Created a portable status Artifact draft.",),
            structured_content={
                "type": "agent-hub.fixture.status",
                "title": "Bridge status",
                "summary": "Foundation fixture status.",
                "schema": {"id": "agent-hub.fixture.status", "version": "1.0"},
                "payload": {"status": "available"},
            },
        )
    )
    artifacts = create_memory_artifact_module(projects, plugin_gateway=gateway)  # type: ignore[arg-type]

    created = await artifacts.create_from_plugin(
        ArtifactMutationAccess(subject="sam", thread_id="thread-a", run_id="run-a"),
        project.id,
        plugin_id="foundation-fixture",
        tool_name="create_status_artifact",
        arguments={"title": "Bridge status"},
    )

    assert created.artifact.id.root
    assert created.artifact.document_version == 1
    assert created.artifact.plugin.id == "foundation-fixture"
    assert created.artifact.plugin.version == "0.1.0"
    assert created.artifact.provenance.created_by_run_id.root == "run-a"
    assert created.payload == {"status": "available"}
    assert gateway.calls == [
        ("foundation-fixture", "create_status_artifact", {"title": "Bridge status"})
    ]


@pytest.mark.asyncio
async def test_enabled_plugin_replacement_is_applied_through_the_artifact_authority() -> None:
    projects = create_memory_project_module()
    project = await projects.create(ProjectAccess(subject="sam"), "Bridge")
    gateway = FixtureGateway(
        PluginToolResult(content=("",), structured_content={"placeholder": True})
    )
    artifacts = create_memory_artifact_module(projects, plugin_gateway=gateway)  # type: ignore[arg-type]
    access = ArtifactMutationAccess(subject="sam", thread_id="thread-a", run_id="run-a")
    created = await artifacts.create(access, project.id, _draft())
    replacement = created.model_copy(update={"payload": {"status": "unavailable"}})
    gateway.result = (
        PluginToolResult(
            content=("Set the fixture status to unavailable.",),
            structured_content=replacement.model_dump(by_alias=True),
        )
    )

    saved = await artifacts.apply_plugin_operation(
        ArtifactMutationAccess(subject="sam", thread_id="thread-b", run_id="run-b"),
        project.id,
        created.artifact.id.root,
        expected_version=1,
        tool_name="set_status_artifact_status",
        arguments={"status": "unavailable"},
    )

    assert saved.payload == {"status": "unavailable"}
    assert saved.artifact.document_version == 2
    assert saved.artifact.provenance.last_changed_by_run_id.root == "run-b"
    plugin_id, tool_name, arguments = gateway.calls[0]
    assert (plugin_id, tool_name) == ("foundation-fixture", "set_status_artifact_status")
    assert arguments["status"] == "unavailable"
    assert arguments["document"] == created.model_dump(by_alias=True)
