import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from agent_hub_api.modules.identity import create_identity_module
from agent_hub_api.modules.project_files import (
    create_memory_project_files,
    create_project_files_router,
)
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module
from agent_hub_api.settings import Settings


@pytest.mark.asyncio
async def test_preview_is_safe_project_authorized_and_does_not_create_an_artifact() -> None:
    settings = Settings(environment="test", fixed_identity_subject="alice")
    projects = create_memory_project_module()
    project = await projects.create(ProjectAccess(subject="alice"), "Bridge")
    files = create_memory_project_files()
    await files.write(project.id, "/notes/check.md", "# Beam check\n<script>no</script>")
    app = FastAPI()
    app.include_router(
        create_project_files_router(create_identity_module(settings), projects, files),
        prefix="/api",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/api/projects/{project.id}/files", params={"path": "/project/notes/check.md"}
        )
        host_path = await client.get(
            f"/api/projects/{project.id}/files", params={"path": "/etc/passwd"}
        )

    assert response.status_code == 200
    assert response.json() == {
        "path": "/project/notes/check.md",
        "content": "# Beam check\n<script>no</script>",
        "version": 1,
    }
    assert host_path.status_code == 422
    assert [file.path for file in await files.list(project.id)] == ["/notes/check.md"]


@pytest.mark.asyncio
async def test_preview_does_not_reveal_another_subjects_project() -> None:
    projects = create_memory_project_module()
    project = await projects.create(ProjectAccess(subject="alice"), "Private")
    files = create_memory_project_files()
    await files.write(project.id, "/private.md", "secret")
    app = FastAPI()
    app.include_router(
        create_project_files_router(
            create_identity_module(Settings(environment="test", fixed_identity_subject="bob")),
            projects,
            files,
        ),
        prefix="/api",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/api/projects/{project.id}/files", params={"path": "/project/private.md"}
        )

    assert response.status_code == 404
