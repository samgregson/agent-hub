import pytest

fastmcp = pytest.importorskip("fastmcp")

from fastmcp.client import Client

from agent_hub_foundation_fixture._server import (
    FIXTURE_APP_RESOURCE_URI,
    FIXTURE_TOOL_NAME,
    create_fixture_server,
)


@pytest.mark.asyncio
async def test_the_fixture_is_usable_by_an_ordinary_mcp_client() -> None:
    async with Client(create_fixture_server(), timeout=1, init_timeout=1) as client:
        tools = await client.list_tools()
        assert [tool.name for tool in tools] == [FIXTURE_TOOL_NAME]
        fixture_tool = tools[0]
        assert fixture_tool.annotations is not None
        assert fixture_tool.annotations.read_only_hint is True

        result = await client.call_tool(FIXTURE_TOOL_NAME, {})
        assert result.data == {
            "source": "agent-hub-foundation-fixture",
            "status": "available",
        }

        resources = await client.list_resources()
        assert any(str(resource.uri) == FIXTURE_APP_RESOURCE_URI for resource in resources)
        contents = await client.read_resource(FIXTURE_APP_RESOURCE_URI)
        assert contents[0].mime_type == "text/html;profile=mcp-app"
        assert "ui/initialize" in contents[0].text
