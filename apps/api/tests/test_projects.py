import pytest
from httpx import ASGITransport, AsyncClient

from agent_hub_api.main import create_app
from agent_hub_api.modules.identity import create_identity_module
from agent_hub_api.modules.projects import ProjectModule, create_memory_project_module
from agent_hub_api.settings import Settings


async def ready(_: Settings) -> None:
    return None


def client_for(subject: str, projects: ProjectModule) -> AsyncClient:
    settings = Settings(environment="test", fixed_identity_subject=subject)
    app = create_app(
        settings=settings,
        readiness_check=ready,
        identity=create_identity_module(settings),
        projects=projects,
    )
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )


@pytest.mark.asyncio
async def test_projects_are_scoped_to_authenticated_subject() -> None:
    projects = create_memory_project_module()

    async with client_for("subject-a", projects) as alice:
        created = await alice.post("/api/projects", json={"name": "Bridge study"})
        project_id = created.json()["id"]

    async with client_for("subject-b", projects) as bob:
        listed = await bob.get("/api/projects")
        guessed = await bob.get(f"/api/projects/{project_id}")

    assert created.status_code == 201
    assert created.json()["name"] == "Bridge study"
    assert listed.status_code == 200
    assert listed.json() == []
    assert guessed.status_code == 404


@pytest.mark.asyncio
async def test_project_name_is_normalized_and_validated() -> None:
    projects = create_memory_project_module()

    async with client_for("subject-a", projects) as client:
        created = await client.post("/api/projects", json={"name": "  New project  "})
        blank = await client.post("/api/projects", json={"name": "   "})

    assert created.status_code == 201
    assert created.json()["name"] == "New project"
    assert blank.status_code == 422


@pytest.mark.asyncio
async def test_missing_platform_identity_is_rejected() -> None:
    settings = Settings(environment="test", identity_mode="trusted_header")
    projects = create_memory_project_module()

    app = create_app(
        settings=settings,
        readiness_check=ready,
        identity=create_identity_module(settings),
        projects=projects,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/projects")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_threads_are_scoped_to_their_project_and_subject() -> None:
    projects = create_memory_project_module()

    async with client_for("subject-a", projects) as alice:
        first = (await alice.post("/api/projects", json={"name": "First"})).json()
        second = (await alice.post("/api/projects", json={"name": "Second"})).json()
        created = await alice.post(
            f"/api/projects/{first['id']}/threads",
            json={"title": "  Load combinations  "},
        )
        thread_id = created.json()["id"]
        wrong_project = await alice.get(f"/api/projects/{second['id']}/threads/{thread_id}")

    async with client_for("subject-b", projects) as bob:
        guessed = await bob.get(f"/api/projects/{first['id']}/threads/{thread_id}")

    assert created.status_code == 201
    assert created.json()["title"] == "Load combinations"
    assert created.json()["projectId"] == first["id"]
    assert wrong_project.status_code == 404
    assert guessed.status_code == 404
