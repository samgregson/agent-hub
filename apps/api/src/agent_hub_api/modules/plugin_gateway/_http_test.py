import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from agent_hub_api.modules.identity import create_identity_module
from agent_hub_api.modules.plugin_gateway import (
    MemoryPluginEnablementStore,
    PluginGatewayModule,
    PluginManifest,
    PluginTool,
    create_plugin_gateway_router,
)
from agent_hub_api.modules.projects import (
    ProjectModule,
    create_memory_project_module,
    create_project_router,
)
from agent_hub_api.settings import Settings


def client_for(subject: str, projects: ProjectModule, gateway: PluginGatewayModule) -> AsyncClient:
    settings = Settings(environment="test", fixed_identity_subject=subject)
    app = FastAPI()
    identity = create_identity_module(settings)
    app.include_router(create_project_router(identity, projects), prefix="/api")
    app.include_router(
        create_plugin_gateway_router(identity, gateway), prefix="/api"
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_plugin_selection_is_project_scoped_and_idempotent() -> None:
    projects = create_memory_project_module()
    gateway = PluginGatewayModule(
        projects,
        catalog=(
            PluginManifest(
                id="foundation-fixture",
                name="Foundation fixture",
                version="0.1.0",
                endpoint="http://foundation-fixture:8000/mcp",
                tools=(PluginTool(name="foundation_status", read_only=True),),
            ),
        ),
        enablements=MemoryPluginEnablementStore(),
        clients={},
    )

    async with client_for("subject-a", projects, gateway) as alice:
        created = await alice.post("/api/projects", json={"name": "Bridge study"})
        project_id = created.json()["id"]
        before = await alice.get(f"/api/projects/{project_id}/plugins")
        enabled = await alice.put(f"/api/projects/{project_id}/plugins/foundation-fixture")
        repeated_enable = await alice.put(
            f"/api/projects/{project_id}/plugins/foundation-fixture"
        )
        after = await alice.get(f"/api/projects/{project_id}/plugins")
        disabled = await alice.delete(f"/api/projects/{project_id}/plugins/foundation-fixture")
        after_disable = await alice.get(f"/api/projects/{project_id}/plugins")

    async with client_for("subject-b", projects, gateway) as bob:
        hidden = await bob.get(f"/api/projects/{project_id}/plugins")

    assert before.status_code == 200
    assert before.json() == [
        {
            "enabled": False,
            "id": "foundation-fixture",
            "name": "Foundation fixture",
            "tools": [{"name": "foundation_status", "readOnly": True}],
            "version": "0.1.0",
        }
    ]
    assert enabled.status_code == 204
    assert repeated_enable.status_code == 204
    assert after.json()[0]["enabled"] is True
    assert disabled.status_code == 204
    assert after_disable.json()[0]["enabled"] is False
    assert hidden.status_code == 404
