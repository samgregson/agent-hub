import asyncio
from collections.abc import Mapping
from dataclasses import dataclass

import pytest

from agent_hub_api.modules.plugin_gateway import (
    MemoryPluginEnablementStore,
    PluginCallLimitExceeded,
    PluginCapability,
    PluginDiscoveredTool,
    PluginGatewayModule,
    PluginManifest,
    PluginNotEnabled,
    PluginTool,
    PluginToolResult,
    PluginUiResource,
)
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module


@dataclass
class FixtureClient:
    calls: list[tuple[str, Mapping[str, object]]]
    discoveries: int = 0

    async def discover_tools(self) -> tuple[PluginDiscoveredTool, ...]:
        self.discoveries += 1
        return (
            PluginDiscoveredTool(
                name="foundation_status",
                description="Return fixture status.",
                read_only=True,
                input_schema={"type": "object", "properties": {}},
            ),
            PluginDiscoveredTool(
                name="unreviewed_tool", description="Must not be exposed.", read_only=True
            ),
        )

    async def call_tool(self, tool_name: str, arguments: Mapping[str, object]) -> PluginToolResult:
        self.calls.append((tool_name, arguments))
        return PluginToolResult(
            content=("Agent Hub's portable MCP fixture is available.",),
            structured_content={"status": "available"},
        )

    async def read_ui_resource(self, resource_uri: str) -> PluginUiResource:
        return PluginUiResource(uri=resource_uri, html="<main>Fixture App</main>")


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
                endpoint="http://foundation-fixture:8000/mcp",
                tools=(PluginTool(name="foundation_status", read_only=True),),
            )
        ],
        MemoryPluginEnablementStore(),
        {"foundation-fixture": client},
    )

    with pytest.raises(PluginNotEnabled):
        await gateway.call(access, project.id, "foundation-fixture", "foundation_status", {})
    assert await gateway.agent_tools(project.id) == ()

    await gateway.enable(access, project.id, "foundation-fixture")

    assert (await gateway.selections(access, project.id))[0].enabled is True

    assert await gateway.capabilities(access, project.id) == (
        PluginCapability(plugin_id="foundation-fixture", tool_name="foundation_status"),
    )
    agent_tool = (await gateway.agent_tools(project.id))[0]
    assert agent_tool.name == "foundation_fixture__foundation_status"
    assert agent_tool.description == "Return fixture status."
    assert await agent_tool.ainvoke({}) == "Agent Hub's portable MCP fixture is available."
    assert len(await gateway.agent_tools(project.id)) == 1
    assert client.discoveries == 1
    result = await gateway.call(access, project.id, "foundation-fixture", "foundation_status", {})
    assert result.structured_content == {"status": "available"}
    assert client.calls == [
        ("foundation_status", {}),
        ("foundation_status", {}),
    ]

    await gateway.disable(access, project.id, "foundation-fixture")
    assert (await gateway.selections(access, project.id))[0].enabled is False


@pytest.mark.asyncio
async def test_plugin_gateway_rejects_excess_rate_and_concurrent_calls() -> None:
    class BlockingClient(FixtureClient):
        def __init__(self) -> None:
            super().__init__(calls=[])
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def call_tool(
            self, tool_name: str, arguments: Mapping[str, object]
        ) -> PluginToolResult:
            self.started.set()
            await self.release.wait()
            return await super().call_tool(tool_name, arguments)

    projects = create_memory_project_module()
    access = ProjectAccess(subject="sam")
    project = await projects.create(access, "Budget test")
    client = BlockingClient()
    gateway = PluginGatewayModule(
        projects,
        [
            PluginManifest(
                id="foundation-fixture",
                name="Foundation fixture",
                version="0.1.0",
                endpoint="http://foundation-fixture:8000/mcp",
                tools=(PluginTool(name="foundation_status", read_only=True),),
            )
        ],
        MemoryPluginEnablementStore(),
        {"foundation-fixture": client},
        max_concurrent_calls=1,
        max_calls_per_minute=2,
    )
    await gateway.enable(access, project.id, "foundation-fixture")
    first = asyncio.create_task(
        gateway.call(access, project.id, "foundation-fixture", "foundation_status", {})
    )
    try:
        await client.started.wait()
        with pytest.raises(PluginCallLimitExceeded, match="retry later"):
            await gateway.call(access, project.id, "foundation-fixture", "foundation_status", {})
    finally:
        client.release.set()
        await first

    await gateway.call(access, project.id, "foundation-fixture", "foundation_status", {})
    with pytest.raises(PluginCallLimitExceeded, match="retry later"):
        await gateway.call(access, project.id, "foundation-fixture", "foundation_status", {})
    assert len(client.calls) == 2
