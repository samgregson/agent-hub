import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from agent_hub_api.modules.datasets import (
    DatasetModule,
    MemoryDatasetStore,
    create_dataset_router,
)
from agent_hub_api.modules.identity import create_identity_module
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module
from agent_hub_api.settings import Settings


@pytest.mark.asyncio
async def test_direct_user_dataset_actions_are_project_scoped() -> None:
    settings = Settings(environment="test", fixed_identity_subject="sam")
    projects = create_memory_project_module()
    datasets = DatasetModule(projects, MemoryDatasetStore())
    app = FastAPI()
    app.include_router(
        create_dataset_router(create_identity_module(settings), datasets), prefix="/api"
    )
    project = await projects.create(ProjectAccess(subject="sam"), "Bridge")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            f"/api/projects/{project.id}/datasets",
            json={
                "name": "Loads",
                "records": [{"sourceKey": "LC-1", "value": {"length": 2}}],
            },
        )
        dataset = created.json()
        deleted = await client.delete(f"/api/projects/{project.id}/datasets/{dataset['id']}")

    assert created.status_code == 201
    assert dataset["records"][0]["position"] == 0
    assert deleted.status_code == 204


@pytest.mark.asyncio
async def test_dataset_update_requires_the_loaded_document_version() -> None:
    settings = Settings(environment="test", fixed_identity_subject="sam")
    projects = create_memory_project_module()
    datasets = DatasetModule(projects, MemoryDatasetStore())
    app = FastAPI()
    app.include_router(
        create_dataset_router(create_identity_module(settings), datasets), prefix="/api"
    )
    project = await projects.create(ProjectAccess(subject="sam"), "Bridge")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            f"/api/projects/{project.id}/datasets",
            json={"name": "Loads", "records": [{"value": {"length": 2}}]},
        )
        initial = created.json()
        changed = await client.put(
            f"/api/projects/{project.id}/datasets/{initial['id']}",
            json={
                "name": "Loads",
                "expectedVersion": initial["version"],
                "records": [{"id": initial["records"][0]["id"], "value": {"length": 3}}],
            },
        )
        stale = await client.put(
            f"/api/projects/{project.id}/datasets/{initial['id']}",
            json={
                "name": "Loads",
                "expectedVersion": initial["version"],
                "records": [{"id": initial["records"][0]["id"], "value": {"length": 4}}],
            },
        )

    assert initial["version"] == 1
    assert changed.status_code == 200
    assert changed.json()["version"] == 2
    assert stale.status_code == 409
