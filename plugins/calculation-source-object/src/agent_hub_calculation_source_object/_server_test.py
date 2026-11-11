import pytest
from fastmcp.client import Client
from jsonschema import Draft202012Validator

from agent_hub_calculation_source_object import _server


@pytest.mark.asyncio
async def test_discovery_guide_and_structured_public_outputs(monkeypatch):
    async def execute(source, function, inputs):
        return {
            "entry": {"sourceHash": "abc"},
            "authoring": {
                "outputs": [
                    {"invocationId": "root", "name": "area", "value": 6},
                    {"invocationId": "child", "name": "ignored", "value": 99},
                ]
            },
        }

    monkeypatch.setattr(_server, "_execute_source", execute)
    async with Client(_server.create_calculation_source_object_server()) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        tool = tools["run_calculation"]
        assert tool.annotations.read_only_hint is True
        Draft202012Validator.check_schema(tool.input_schema)
        Draft202012Validator.check_schema(tool.output_schema)
        result = await client.call_tool(
            "run_calculation",
            {
                "source": "example",
                "function": "area",
                "inputs": {"width": 2, "height": 3},
            },
        )
        Draft202012Validator(tool.output_schema).validate(result.structured_content)
        assert result.structured_content["outputs"] == {"area": 6}
        guide = await client.call_tool("get_calculation_guide", {})
        resource = await client.read_resource(_server.GUIDE_URI)
        assert "@calculation" in guide.content[0].text
        assert resource[0].text == guide.content[0].text
