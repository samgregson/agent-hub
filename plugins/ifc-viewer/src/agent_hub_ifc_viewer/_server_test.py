from pathlib import Path

import ifcopenshell
import pytest
from fastmcp.client import Client
from fastmcp.exceptions import ToolError
from pydantic import ValidationError

from agent_hub_ifc_viewer._server import APP_URI, ObjectMetadata, create_ifc_viewer_server

FIXTURE = Path(__file__).parents[2] / "app" / "tests" / "beam.ifc"


@pytest.mark.asyncio
async def test_extract_map_join_and_reopen_with_an_ordinary_mcp_client():
    text = FIXTURE.read_text()
    async with Client(create_ifc_viewer_server()) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        assert set(tools) == {"get_ifc_guide", "inspect_ifc_objects", "prepare_ifc_view"}
        assert (
            tools["inspect_ifc_objects"].output_schema["properties"]["objects"]["type"] == "array"
        )
        assert tools["prepare_ifc_view"].meta["ui"]["resourceUri"] == APP_URI
        inspected = (
            await client.call_tool("inspect_ifc_objects", {"ifc_text": text})
        ).structured_content
        beam = next(row for row in inspected["objects"] if row["ifcType"] == "IfcBeam")
        assert beam["properties"]["Pset_BeamCommon"]["Reference"] == "B-01"
        # A calculation keeps the stable IFC GlobalId through Workflow Map.
        rows = [{"globalId": beam["globalId"], "values": {"utilisation": 0.75, "status": "pass"}}]
        result = (
            await client.call_tool(
                "prepare_ifc_view",
                {
                    "ifc_text": text,
                    "metadata": rows,
                    "colour_by": "status",
                },
            )
        ).structured_content
        assert result["metadata"] == rows
        assert result["ifcText"] == text
        assert result["modelSha256"] == inspected["modelSha256"]
        resources = await client.read_resource(APP_URI)
        assert resources[0].mime_type == "text/html;profile=mcp-app"
        assert "<title>IFC viewer</title>" in resources[0].text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"ifc_text": "invalid IFC"},
        {"ifc_text": "x" * 400001},
        {"metadata": [{"globalId": "unknown", "values": {"status": "pass"}}]},
        {"colour_by": "absent"},
    ],
)
async def test_invalid_inputs_fail_without_a_view(overrides):
    async with Client(create_ifc_viewer_server()) as client:
        with pytest.raises(ToolError):
            await client.call_tool(
                "prepare_ifc_view", {"ifc_text": FIXTURE.read_text(), **overrides}
            )


@pytest.mark.asyncio
async def test_duplicate_rows_and_nonfinite_values_are_rejected():
    text = FIXTURE.read_text()
    global_id = ifcopenshell.file.from_string(text).by_type("IfcBeam")[0].GlobalId
    async with Client(create_ifc_viewer_server()) as client:
        row = {"globalId": global_id, "values": {"x": 1}}
        with pytest.raises(ToolError, match="duplicate"):
            await client.call_tool("prepare_ifc_view", {"ifc_text": text, "metadata": [row, row]})
        with pytest.raises(ValidationError):
            ObjectMetadata(globalId=global_id, values={"x": float("inf")})


@pytest.mark.asyncio
async def test_colour_scale_is_captured_and_invalid_thresholds_rejected():
    text = FIXTURE.read_text()
    global_id = ifcopenshell.file.from_string(text).by_type("IfcBeam")[0].GlobalId
    scale = {
        "key": "utilisation",
        "bands": [{"max": 0.95, "colour": "#008000"}, {"max": 1, "colour": "#ffbf00"}],
        "aboveColour": "#ff0000",
    }
    async with Client(create_ifc_viewer_server()) as client:
        args = {
            "ifc_text": text,
            "metadata": [{"globalId": global_id, "values": {"utilisation": 1}}],
            "colour_by": "utilisation",
            "colour_scale": scale,
        }
        result = (await client.call_tool("prepare_ifc_view", args)).structured_content
        assert result["colourScale"] == scale
        with pytest.raises((ToolError, ValidationError)):
            await client.call_tool(
                "prepare_ifc_view",
                {**args, "colour_scale": {**scale, "bands": list(reversed(scale["bands"]))}},
            )
