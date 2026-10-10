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
        assert {tool.name for tool in tools} == {
            FIXTURE_TOOL_NAME,
            "create_status_artifact",
            "validate_status_artifact",
            "set_status_artifact_status",
            "render_template_value",
        }
        fixture_tool = next(tool for tool in tools if tool.name == FIXTURE_TOOL_NAME)
        assert fixture_tool.annotations is not None
        assert fixture_tool.annotations.read_only_hint is True

        result = await client.call_tool(FIXTURE_TOOL_NAME, {})
        assert result.data == {
            "source": "agent-hub-foundation-fixture",
            "status": "available",
        }
        rendered = await client.call_tool(
            "render_template_value", {"template": "value={{value}}", "value": 2.5}
        )
        assert rendered.data == {"rendered": "value=2.5"}

        resources = await client.list_resources()
        assert any(str(resource.uri) == FIXTURE_APP_RESOURCE_URI for resource in resources)
        contents = await client.read_resource(FIXTURE_APP_RESOURCE_URI)
        assert contents[0].mime_type == "text/html;profile=mcp-app"
        assert "ui/initialize" in contents[0].text


@pytest.mark.asyncio
async def test_portable_artifact_round_trip_needs_no_agent_hub_storage() -> None:
    async with Client(create_fixture_server(), timeout=1, init_timeout=1) as client:
        draft = (await client.call_tool("create_status_artifact", {"title": "Bridge status"})).data
        assert draft["payload"] == {"status": "available"}
        document = {
            "artifact": {
                "id": "client-artifact",
                "type": draft["type"],
                "documentVersion": 1,
                "title": draft["title"],
                "summary": draft["summary"],
                "schema": draft["schema"],
                "plugin": {"id": "foundation-fixture", "version": "0.1.0"},
                "provenance": {
                    "createdBy": {
                        "kind": "agentRun",
                        "threadId": "client-thread",
                        "runId": "client-run",
                    },
                    "lastChangedBy": {
                        "kind": "agentRun",
                        "threadId": "client-thread",
                        "runId": "client-run",
                    },
                },
                "relations": [],
            },
            "payload": draft["payload"],
        }

        validation = (
            await client.call_tool("validate_status_artifact", {"document": document})
        ).data
        replacement = (
            await client.call_tool(
                "set_status_artifact_status",
                {"document": document, "status": "unavailable"},
            )
        ).data

        assert validation == {"valid": True, "status": "available"}
        assert replacement["payload"] == {"status": "unavailable"}
        assert replacement["artifact"]["id"] == "client-artifact"
        assert document["payload"] == {"status": "available"}
