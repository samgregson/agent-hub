from collections.abc import Mapping
from typing import cast

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from agent_hub_api.modules.artifacts import (
    ArtifactDraft,
    ArtifactMutationAccess,
    ArtifactUserActionAccess,
    create_artifact_router,
    create_memory_artifact_module,
)
from agent_hub_api.modules.identity import create_identity_module
from agent_hub_api.modules.plugin_gateway import (
    PluginManifest,
    PluginSelection,
    PluginTool,
    PluginToolResult,
    PluginUiResource,
)
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module
from agent_hub_api.settings import Settings


class FixtureGateway:
    manifest = PluginManifest(
        id="foundation-fixture",
        name="Foundation fixture",
        version="0.1.0",
        endpoint="https://fixture.example/mcp",
        tools=(PluginTool(name="set_status_artifact_status", read_only=False),),
        app_resource_uri="ui://agent-hub-foundation/status.html",
        app_tool_names=("set_status_artifact_status",),
    )

    async def selections(self, *_: object) -> tuple[PluginSelection, ...]:
        return (PluginSelection(manifest=self.manifest, enabled=True),)

    async def call(
        self, _: object, __: str, ___: str, ____: str, arguments: dict[str, object]
    ) -> PluginToolResult:
        replacement = dict(cast(Mapping[str, object], arguments["document"]))
        replacement["payload"] = {"status": arguments["status"]}
        return PluginToolResult(content=("Saved.",), structured_content=replacement)

    async def read_ui_resource(self, *_: object) -> PluginUiResource:
        return PluginUiResource(
            uri="ui://agent-hub-foundation/status.html",
            html="<main>Fixture App</main>",
        )


@pytest.mark.asyncio
async def test_authorized_project_can_discover_compact_artifacts_and_load_one() -> None:
    projects = create_memory_project_module()
    project = await projects.create(ProjectAccess(subject="sam"), "Bridge")
    artifacts = create_memory_artifact_module(projects)
    created = await artifacts.create(
        ArtifactMutationAccess(subject="sam", thread_id="thread-a", run_id="run-a"),
        project.id,
        ArtifactDraft(
            type="agent-hub.fixture.status",
            title="Foundation status",
            summary="The fixture is available.",
            plugin_id="foundation-fixture",
            plugin_version="0.1.0",
            schema_id="agent-hub.fixture.status",
            schema_version="1.0",
            payload={"status": "available"},
        ),
    )
    app = FastAPI()
    app.include_router(
        create_artifact_router(
            create_identity_module(Settings(environment="test", fixed_identity_subject="sam")),
            artifacts,
        ),
        prefix="/api",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        catalog = await client.get(f"/api/projects/{project.id}/artifacts")
        document = await client.get(
            f"/api/projects/{project.id}/artifacts/{created.artifact.id.root}"
        )

    assert catalog.status_code == 200
    assert catalog.json() == {
        "artifacts": [
            {
                "id": created.artifact.id.root,
                "type": "agent-hub.fixture.status",
                "documentVersion": 1,
                "title": "Foundation status",
                "summary": "The fixture is available.",
                "pluginId": "foundation-fixture",
                "pluginVersion": "0.1.0",
            }
        ]
    }
    assert document.status_code == 200
    assert document.json()["payload"] == {"status": "available"}


@pytest.mark.asyncio
async def test_user_can_delete_an_artifact_only_from_their_authorized_project() -> None:
    projects = create_memory_project_module()
    project = await projects.create(ProjectAccess(subject="sam"), "Bridge")
    artifacts = create_memory_artifact_module(projects)
    created = await artifacts.create(
        ArtifactUserActionAccess(subject="sam", user_action_id="create-action"),
        project.id,
        ArtifactDraft(
            type="agent-hub.fixture.status",
            title="Foundation status",
            plugin_id="foundation-fixture",
            plugin_version="0.1.0",
            schema_id="agent-hub.fixture.status",
            schema_version="1.0",
            payload={"status": "available"},
        ),
    )
    app = FastAPI()
    app.include_router(
        create_artifact_router(
            create_identity_module(Settings(environment="test", fixed_identity_subject="sam")),
            artifacts,
        ),
        prefix="/api",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        deleted = await client.delete(
            f"/api/projects/{project.id}/artifacts/{created.artifact.id.root}"
        )
        missing = await client.get(
            f"/api/projects/{project.id}/artifacts/{created.artifact.id.root}"
        )

    assert deleted.status_code == 204
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_artifact_app_has_a_sandbox_safe_resource_and_a_reviewed_action_route() -> None:
    projects = create_memory_project_module()
    project = await projects.create(ProjectAccess(subject="sam"), "Bridge")
    artifacts = create_memory_artifact_module(projects, plugin_gateway=FixtureGateway())  # type: ignore[arg-type]
    created = await artifacts.create(
        ArtifactUserActionAccess(subject="sam", user_action_id="create-action"),
        project.id,
        ArtifactDraft(
            type="agent-hub.fixture.status",
            title="Foundation status",
            plugin_id="foundation-fixture",
            plugin_version="0.1.0",
            schema_id="agent-hub.fixture.status",
            schema_version="1.0",
            payload={"status": "available"},
        ),
    )
    app = FastAPI()
    app.include_router(
        create_artifact_router(
            create_identity_module(Settings(environment="test", fixed_identity_subject="sam")),
            artifacts,
        ),
        prefix="/api",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resource = await client.get(
            f"/api/projects/{project.id}/artifacts/{created.artifact.id.root}/app"
        )
        saved = await client.post(
            f"/api/projects/{project.id}/artifacts/{created.artifact.id.root}/app/actions",
            json={
                "name": "set_status_artifact_status",
                "arguments": {"status": "unavailable"},
                "expectedVersion": 1,
            },
        )
        forbidden = await client.post(
            f"/api/projects/{project.id}/artifacts/{created.artifact.id.root}/app/actions",
            json={
                "name": "read_file",
                "arguments": {},
                "expectedVersion": 2,
            },
        )

    assert resource.status_code == 200
    assert resource.headers["content-security-policy"] == (
        "default-src 'none'; base-uri 'none'; connect-src 'none'; "
        "font-src data:; form-action 'none'; frame-ancestors 'self'; "
        "frame-src 'none'; img-src data:; script-src 'unsafe-inline'; style-src 'unsafe-inline'"
    )
    assert resource.headers["x-content-type-options"] == "nosniff"
    assert saved.status_code == 200
    assert saved.json()["payload"] == {"status": "unavailable"}
    assert forbidden.status_code == 422
