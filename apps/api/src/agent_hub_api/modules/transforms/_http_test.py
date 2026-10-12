import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

from agent_hub_api.modules.identity import create_identity_module
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module
from agent_hub_api.modules.transforms import (
    MemoryTransformStore,
    TransformModule,
    TransformRuntimeIdentity,
    create_function_router,
)
from agent_hub_api.settings import Settings


class _PinnedRunner:
    async def identity(self) -> TransformRuntimeIdentity:
        return TransformRuntimeIdentity("deno:2.9.7;pyodide:314.0.7", "a" * 64)


def test_function_http_surface_exposes_authoring_and_preview_without_runs() -> None:
    projects = create_memory_project_module()
    app_settings = Settings(environment="test", fixed_identity_subject="sam")
    router = create_function_router(
        create_identity_module(app_settings),
        TransformModule(projects, MemoryTransformStore()),
    )
    paths = {route.path for route in router.routes if isinstance(route, APIRoute)}

    assert "/projects/{project_id}/functions" in paths
    assert "/projects/{project_id}/functions/{definition_id}/preview" in paths
    assert not any(
        suffix in path
        for path in paths
        for suffix in ("/runs", "/call", "selection", "save-dataset", "save-artifact")
    )


@pytest.mark.asyncio
async def test_transform_definition_http_round_trip() -> None:
    projects = create_memory_project_module()
    project = await projects.create(ProjectAccess(subject="sam"), "Bridge")
    app = FastAPI()
    app.include_router(
        create_function_router(
            create_identity_module(Settings(environment="test", fixed_identity_subject="sam")),
            TransformModule(projects, MemoryTransformStore()),
        ),
        prefix="/api",
    )
    path = f"/api/projects/{project.id}/functions"
    body = {
        "name": "Double loads",
        "source": "def transform(inputs, parameters):\n    return {}\n",
        "inputSelectors": {"load": "/load"},
        "inputSchema": {
            "type": "object",
            "properties": {"load": {"type": "number"}},
            "required": ["load"],
            "additionalProperties": False,
        },
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


@pytest.mark.asyncio
async def test_preview_http_uses_definition_and_returns_transient_output() -> None:
    projects = create_memory_project_module()
    project = await projects.create(ProjectAccess(subject="sam"), "Bridge")

    class Runner(_PinnedRunner):
        async def execute(
            self, source: str, inputs: dict[str, object], parameters: dict[str, object]
        ) -> tuple[object, str]:
            assert inputs == {"load": 3}
            return {"value": 6}, "deno:2.9.7;pyodide:314.0.7"

    transforms = TransformModule(projects, MemoryTransformStore(), Runner())
    definition = await transforms.define(
        ProjectAccess(subject="sam"),
        project.id,
        "Double",
        "def transform(inputs, parameters):\n    return {}\n",
        {"load": "/load"},
        {"type": "object"},
    )
    app = FastAPI()
    app.include_router(
        create_function_router(
            create_identity_module(Settings(environment="test", fixed_identity_subject="sam")),
            transforms,
        ),
        prefix="/api",
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/projects/{project.id}/functions/{definition.id}/preview",
            json={"record": {"load": 3}, "parameters": {}},
        )
    assert response.status_code == 200
    assert response.json() == {
        "output": {"value": 6},
        "runtime": "deno:2.9.7;pyodide:314.0.7",
        "sourceHash": definition.source_hash,
    }
