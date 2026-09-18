import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from agent_hub_api.modules.artifacts import (
    ArtifactDraft,
    ArtifactMutationAccess,
    create_artifact_router,
    create_memory_artifact_module,
)
from agent_hub_api.modules.identity import create_identity_module
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module
from agent_hub_api.settings import Settings


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
