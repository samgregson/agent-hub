import pytest

pytest.importorskip("fastmcp")

from fastmcp.client import Client

from agent_hub_reference_calculation._server import (
    BEAM_DEFLECTION_TOOL_NAME,
    CALCULATION_APP_RESOURCE_URI,
    CANTILEVER_TIP_LOAD_TOOL_NAME,
    DRAFT_BEAM_REVIEW_NOTE_TOOL_NAME,
    SIZE_FOR_DEFLECTION_TOOL_NAME,
    create_reference_calculation_server,
)


@pytest.mark.asyncio
async def test_an_ordinary_mcp_client_can_calculate_a_cantilever_tip_moment() -> None:
    async with Client(create_reference_calculation_server(), timeout=1, init_timeout=1) as client:
        tools = await client.list_tools()
        assert {tool.name for tool in tools} == {
            CANTILEVER_TIP_LOAD_TOOL_NAME,
            BEAM_DEFLECTION_TOOL_NAME,
            SIZE_FOR_DEFLECTION_TOOL_NAME,
            DRAFT_BEAM_REVIEW_NOTE_TOOL_NAME,
        }

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


@pytest.mark.asyncio
async def test_beam_check_returns_the_input_context_and_a_check_result() -> None:
    async with Client(create_reference_calculation_server(), timeout=1, init_timeout=1) as client:
        result = await client.call_tool(
            BEAM_DEFLECTION_TOOL_NAME,
            {
                "beam_ref": "B-12",
                "span_m": 6,
                "imposed_load_kn_m2": 3,
                "tributary_width_m": 3,
                "elastic_modulus_gpa": 210,
                "inertia_mm4": 40_000_000,
                "deflection_limit_ratio": 360,
            },
        )

    assert result.data["beam_ref"] == "B-12"
    assert result.data["check_status"] == "fails"
    assert result.data["maximum_deflection_mm"] == pytest.approx(18.080357142857142)
    assert result.data["limit_mm"] == pytest.approx(16.666666666666668)
    assert result.data["method"] == "5wL^4/(384EI)"


@pytest.mark.asyncio
async def test_beam_check_rejects_non_positive_or_missing_physical_inputs() -> None:
    async with Client(create_reference_calculation_server(), timeout=1, init_timeout=1) as client:
        result = await client.call_tool(
            BEAM_DEFLECTION_TOOL_NAME,
            {
                "beam_ref": "B-12",
                "span_m": 6,
                "imposed_load_kn_m2": 3,
                "tributary_width_m": 3,
                "elastic_modulus_gpa": 210,
                "inertia_mm4": 40_000_000,
                "deflection_limit_ratio": 360,
            },
        )
        invalid = await client.call_tool(
            BEAM_DEFLECTION_TOOL_NAME,
            {
                "beam_ref": "B-12",
                "span_m": -1,
                "imposed_load_kn_m2": 3,
                "tributary_width_m": 3,
                "elastic_modulus_gpa": 210,
                "inertia_mm4": 40_000_000,
                "deflection_limit_ratio": 360,
            },
        )

    assert result.data["check_status"] == "fails"
    assert invalid.data["validation"]["status"] == "invalid"
    assert "span_m must be greater than zero." in invalid.data["validation"]["errors"]


@pytest.mark.asyncio
async def test_sizing_and_review_tools_compose_using_structured_values() -> None:
    async with Client(create_reference_calculation_server(), timeout=1, init_timeout=1) as client:
        sizing = await client.call_tool(
            SIZE_FOR_DEFLECTION_TOOL_NAME,
            {
                "beam_ref": "B-12",
                "span_m": 6,
                "imposed_load_kn_m2": 3,
                "tributary_width_m": 3,
                "elastic_modulus_gpa": 210,
                "limit_mm": 6000 / 360,
                "trial_inertia_mm4": 40_000_000,
                "trial_deflection_mm": 18.080357142857142,
            },
        )
        note = await client.call_tool(
            DRAFT_BEAM_REVIEW_NOTE_TOOL_NAME,
            sizing.data,
        )

    assert sizing.data["minimum_inertia_mm4"] == pytest.approx(43_392_857.14285714)
    assert sizing.data["trial_deflection_mm"] > sizing.data["limit_mm"]
    assert "B-12" in note.data["note"]
    assert "43.393" in note.data["note"]
    assert note.data["review_only"] is True
