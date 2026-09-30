import pytest

pytest.importorskip("fastmcp")

from fastmcp.client import Client

from agent_hub_reference_calculation._server import (
    CALCULATION_APP_RESOURCE_URI,
    CANTILEVER_TIP_LOAD_TOOL_NAME,
    create_reference_calculation_server,
)


@pytest.mark.asyncio
async def test_an_ordinary_mcp_client_can_calculate_a_cantilever_tip_moment() -> None:
    async with Client(create_reference_calculation_server(), timeout=1, init_timeout=1) as client:
        tools = await client.list_tools()
        assert [tool.name for tool in tools] == [CANTILEVER_TIP_LOAD_TOOL_NAME]

        result = await client.call_tool(
            CANTILEVER_TIP_LOAD_TOOL_NAME,
            {"length_m": 4, "tip_load_kn": 12.5},
        )
        resources = await client.list_resources()
        assert any(str(resource.uri) == CALCULATION_APP_RESOURCE_URI for resource in resources)
        contents = await client.read_resource(CALCULATION_APP_RESOURCE_URI)

    assert result.data == {
        "calculation": {
            "formula": "M_max = P × L",
            "kind": "cantileverTipLoad",
            "length": {"unit": "m", "value": 4.0},
            "maximumMoment": {"unit": "kN·m", "value": 50.0},
            "tipLoad": {"unit": "kN", "value": 12.5},
        },
        "validation": {"status": "valid", "warnings": []},
    }

    assert contents[0].mime_type == "text/html;profile=mcp-app"
    assert "Cantilever moment" in contents[0].text
    assert "moment-curve" in contents[0].text
