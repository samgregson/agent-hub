from collections.abc import Mapping
from dataclasses import dataclass

import pytest

from agent_hub_api.modules.plugin_gateway import (
    MemoryPluginEnablementStore,
    PluginCapability,
    PluginGatewayModule,
    PluginManifest,
    PluginNotEnabled,
    PluginTool,
    PluginToolResult,
)
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module


@dataclass
class FixtureClient:
    calls: list[tuple[str, Mapping[str, object]]]

    async def call_tool(self, tool_name: str, arguments: Mapping[str, object]) -> PluginToolResult:
        self.calls.append((tool_name, arguments))
        return PluginToolResult(
            content=("Agent Hub's portable MCP fixture is available.",),
            structured_content={"status": "available"},
        )


@pytest.mark.asyncio
async def test_only_an_enabled_catalogued_plugin_can_be_called() -> None:
    projects = create_memory_project_module()
    access = ProjectAccess(subject="sam")
    project = await projects.create(access, "Fixture test")
    client = FixtureClient(calls=[])
    gateway = PluginGatewayModule(
        projects,
        [
            PluginManifest(
                id="foundation-fixture",
                name="Foundation fixture",
                version="0.1.0",
                tools=(PluginTool(name="foundation_status", read_only=True),),
            )
        ],
        MemoryPluginEnablementStore(),
        {"foundation-fixture": client},
    )

    with pytest.raises(PluginNotEnabled):
        await gateway.call(access, project.id, "foundation-fixture", "foundation_status", {})

    await gateway.enable(access, project.id, "foundation-fixture")

    assert await gateway.capabilities(access, project.id) == (
        PluginCapability(plugin_id="foundation-fixture", tool_name="foundation_status"),
    )
    result = await gateway.call(access, project.id, "foundation-fixture", "foundation_status", {})
    assert result.structured_content == {"status": "available"}
    assert client.calls == [("foundation_status", {})]
