import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from agent_hub_api.modules.identity import create_identity_module
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module
from agent_hub_api.modules.transforms import (
    MemoryTransformStore,
    TransformModule,
    create_transform_router,
)
from agent_hub_api.settings import Settings


@pytest.mark.asyncio
async def test_transform_definition_http_round_trip() -> None:
    projects = create_memory_project_module()
    project = await projects.create(ProjectAccess(subject="sam"), "Bridge")
    app = FastAPI()
    app.include_router(
        create_transform_router(
            create_identity_module(Settings(environment="test", fixed_identity_subject="sam")),
            TransformModule(projects, MemoryTransformStore()),
        ),
        prefix="/api",
    )
    path = f"/api/projects/{project.id}/transforms"
    body = {
        "name": "Double loads",
        "source": "def transform(inputs, parameters):\n    return {}\n",
        "inputSelectors": {"load": "/load"},
        "outputSchema": {"type": "object"},
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(path, json=body)
        assert created.status_code == 201
        definition_id = created.json()["id"]
        loaded = await client.get(f"{path}/{definition_id}")
        listed = await client.get(path)
        invalid = await client.put(f"{path}/{definition_id}", json={**body, "source": " "})
        deleted = await client.delete(f"{path}/{definition_id}")
        missing = await client.get(f"{path}/{definition_id}")

    assert loaded.json()["sourceHash"] == created.json()["sourceHash"]
    assert [item["id"] for item in listed.json()] == [definition_id]
    assert invalid.status_code == 422
    assert deleted.status_code == 204
    assert missing.status_code == 404
