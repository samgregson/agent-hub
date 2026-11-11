import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass

import pytest
from langchain_core.utils.function_calling import convert_to_openai_tool

from agent_hub_api.modules.plugin_gateway import (
    MemoryPluginEnablementStore,
    PluginCallLimitExceeded,
    PluginCapability,
    PluginDiscoveredTool,
    PluginGatewayModule,
    PluginManifest,
    PluginNotEnabled,
    PluginTool,
    PluginToolNotAllowed,
    PluginToolResult,
    PluginTransportError,
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
    assert agent_tool.description.startswith("Return fixture status.")
    assert "foundation-fixture" in agent_tool.description
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
async def test_model_facing_tool_description_includes_declared_output_schema() -> None:
    class ContractClient(FixtureClient):
        async def discover_tools(self) -> tuple[PluginDiscoveredTool, ...]:
            return (
                PluginDiscoveredTool(
                    name="foundation_status",
                    description="Check status.",
                    read_only=True,
                    input_schema={"type": "object", "properties": {}},
                    output_schema={"type": "object", "properties": {"status": {"type": "string"}}},
                ),
            )

    projects = create_memory_project_module()
    access = ProjectAccess(subject="sam")
    project = await projects.create(access, "Schema")
    gateway = PluginGatewayModule(
        projects,
        [
            PluginManifest(
                id="fixture",
                name="Fixture",
                version="1",
                endpoint="http://fixture/mcp",
                tools=(PluginTool(name="foundation_status", read_only=True),),
            )
        ],
        MemoryPluginEnablementStore(),
        {"fixture": ContractClient(calls=[])},
    )
    await gateway.enable(access, project.id, "fixture")
    direct = (await gateway.agent_tools(project.id))[0]
    ptc = (await gateway.programmatic_tools(access, project.id))[0]
    for tool in (direct, ptc):
        assert '"status":{"type":"string"}' in tool.description
        assert "Plugin ID 'fixture'" in tool.description
        model_tool = convert_to_openai_tool(tool)["function"]
        assert model_tool["parameters"]["type"] == "object"
        assert '"status":{"type":"string"}' in model_tool["description"]


@pytest.mark.asyncio
async def test_programmatic_plugin_input_error_is_recoverable() -> None:
    class NumericClient(FixtureClient):
        async def discover_tools(self) -> tuple[PluginDiscoveredTool, ...]:
            return (
                PluginDiscoveredTool(
                    name="foundation_status",
                    description="Numeric values",
                    read_only=True,
                    input_schema={
                        "type": "object",
                        "properties": {
                            "values": {
                                "type": "object",
                                "additionalProperties": {
                                    "anyOf": [{"type": "integer"}, {"type": "number"}]
                                },
                            }
                        },
                        "required": ["values"],
                    },
                ),
            )

    projects = create_memory_project_module()
    access = ProjectAccess(subject="sam")
    project = await projects.create(access, "Input recovery")
    client = NumericClient(calls=[])
    gateway = PluginGatewayModule(
        projects,
        [
            PluginManifest(
                id="fixture",
                name="Fixture",
                version="1",
                endpoint="http://fixture/mcp",
                tools=(PluginTool(name="foundation_status", read_only=True),),
            )
        ],
        MemoryPluginEnablementStore(),
        {"fixture": client},
    )
    await gateway.enable(access, project.id, "fixture")
    tool = (await gateway.programmatic_tools(access, project.id))[0]
    result = await tool.ainvoke({"values": {"label": "not a number"}})
    assert result["error"]["code"] == "invalid_plugin_input"
    assert "/values/label" in result["error"]["message"]
    assert "integer or number" in result["error"]["message"]
    assert client.calls == []
    valid = await tool.ainvoke({"values": {"amount": 3}})
    assert valid["structuredContent"] == {"status": "available"}


@pytest.mark.asyncio
async def test_saved_large_repeated_output_is_summarized_without_losing_snapshot() -> None:
    payload = {"kind": "example", "outputs": {"total": 42}, "report": "x" * 12000}

    class LargeClient(FixtureClient):
        async def call_tool(
            self, tool_name: str, arguments: Mapping[str, object]
        ) -> PluginToolResult:
            content = getattr(self, "text_override", json.dumps(payload))
            return PluginToolResult(content=(content,), structured_content=payload)

    projects = create_memory_project_module()
    access = ProjectAccess(subject="sam")
    project = await projects.create(access, "Large output")
    client = LargeClient(calls=[])
    gateway = PluginGatewayModule(
        projects,
        [
            PluginManifest(
                id="fixture",
                name="Fixture",
                version="1",
                endpoint="http://fixture/mcp",
                tools=(PluginTool(name="foundation_status", read_only=True),),
            )
        ],
        MemoryPluginEnablementStore(),
        {"fixture": client},
    )
    await gateway.enable(access, project.id, "fixture")
    recorded: list[Mapping[str, object] | None] = []

    async def save(_manifest, _tool, _arguments, result):
        recorded.append(result.structured_content)
        return {"artifactId": "saved", "outputPointer": "/payload/output"}

    tool = (await gateway.agent_tools(project.id, on_success=save))[0]
    text = await tool.ainvoke({})
    assert len(text) < 1000
    assert '"total": 42' in text
    assert '"omittedFields": ["report"]' in text
    assert '"artifactId": "saved"' in text
    assert recorded == [payload]
    unsaved = (await gateway.agent_tools(project.id))[0]
    assert await unsaved.ainvoke({}) == json.dumps(payload)

    async def no_reference(_manifest, _tool, _arguments, _result):
        return {"note": "not a recoverable snapshot"}

    without_reference = (await gateway.agent_tools(project.id, on_success=no_reference))[0]
    assert (await without_reference.ainvoke({})).startswith(json.dumps(payload))
    client.text_override = "Important narrative " + "x" * 12000
    assert (await tool.ainvoke({})).startswith(client.text_override)


@pytest.mark.asyncio
async def test_single_call_can_review_non_repeat_safe_tool_schema() -> None:
    class SchemaClient(FixtureClient):
        async def discover_tools(self) -> tuple[PluginDiscoveredTool, ...]:
            return (
                PluginDiscoveredTool(
                    name="calculate",
                    description="Calculate once.",
                    read_only=False,
                    input_schema={"type": "object", "required": ["x"]},
                    output_schema={"type": "object", "required": ["result"]},
                ),
            )

    projects = create_memory_project_module()
    access = ProjectAccess(subject="sam")
    project = await projects.create(access, "Single call")
    gateway = PluginGatewayModule(
        projects,
        [
            PluginManifest(
                id="fixture",
                name="Fixture",
                version="2.0",
                endpoint="http://fixture/mcp",
                tools=(PluginTool(name="calculate", read_only=False, repeat_safe=False),),
            )
        ],
        MemoryPluginEnablementStore(),
        {"fixture": SchemaClient(calls=[])},
    )
    await gateway.enable(access, project.id, "fixture")

    assert await gateway.tool_version(access, project.id, "fixture", "calculate") == "2.0"
    assert (
        await gateway.output_schema(
            access, project.id, "fixture", "calculate", require_repeat_safe=False
        )
    )["required"] == ["result"]
    with pytest.raises(PluginToolNotAllowed):
        await gateway.output_schema(access, project.id, "fixture", "calculate")


@pytest.mark.asyncio
async def test_unavailable_enabled_plugin_does_not_abort_agent_tool_setup() -> None:
    class UnavailableClient(FixtureClient):
        async def discover_tools(self) -> tuple[PluginDiscoveredTool, ...]:
            raise PluginTransportError("The Plugin server is unavailable or did not respond.")

    projects = create_memory_project_module()
    access = ProjectAccess(subject="sam")
    project = await projects.create(access, "Offline Plugin")
    gateway = PluginGatewayModule(
        projects,
        [
            PluginManifest(
                id="foundation-fixture",
                name="Foundation fixture",
                version="0.1.0",
                endpoint="http://foundation-fixture:8000/mcp",
                tools=(PluginTool(name="foundation_status", read_only=True),),
            ),
            PluginManifest(
                id="available-plugin",
                name="Available Plugin",
                version="0.1.0",
                endpoint="http://available-plugin:8000/mcp",
                tools=(PluginTool(name="foundation_status", read_only=True),),
            ),
        ],
        MemoryPluginEnablementStore(),
        {
            "foundation-fixture": UnavailableClient(calls=[]),
            "available-plugin": FixtureClient(calls=[]),
        },
    )
    await gateway.enable(access, project.id, "foundation-fixture")
    await gateway.enable(access, project.id, "available-plugin")

    assert tuple(tool.name for tool in await gateway.agent_tools(project.id)) == (
        "available_plugin__foundation_status",
    )


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


@pytest.mark.asyncio
@pytest.mark.parametrize("reviewed", [False, True])
async def test_only_deployment_review_can_grant_wasm_to_an_app(reviewed: bool) -> None:
    class WasmRequestClient(FixtureClient):
        async def read_ui_resource(self, resource_uri: str) -> PluginUiResource:
            return PluginUiResource(uri=resource_uri, html="<main>App</main>", allow_wasm=True)

    projects = create_memory_project_module()
    access = ProjectAccess(subject="sam")
    project = await projects.create(access, "App capability test")
    uri = "ui://fixture/view.html"
    gateway = PluginGatewayModule(
        projects,
        [
            PluginManifest(
                id="fixture",
                name="Fixture",
                version="1",
                endpoint="http://fixture/mcp",
                tools=(),
                app_resource_uri=uri,
                app_allow_wasm=reviewed,
            )
        ],
        MemoryPluginEnablementStore(),
        {"fixture": WasmRequestClient(calls=[])},
    )
    await gateway.enable(access, project.id, "fixture")
    resource = await gateway.read_ui_resource(access, project.id, "fixture", uri)
    assert ("'wasm-unsafe-eval'" in resource.content_security_policy) is reviewed
    assert "connect-src 'none'" in resource.content_security_policy
    assert "'unsafe-eval'" not in resource.content_security_policy
