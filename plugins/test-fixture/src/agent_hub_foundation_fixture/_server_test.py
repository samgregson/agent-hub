import pytest

fastmcp = pytest.importorskip("fastmcp")

from fastmcp.client import Client

from agent_hub_foundation_fixture._server import (
    FIXTURE_APP_RESOURCE_URI,
    FIXTURE_CREATE_ARTIFACT_TOOL_NAME,
    FIXTURE_EDIT_ARTIFACT_TOOL_NAME,
    FIXTURE_TOOL_NAME,
    FIXTURE_VALIDATE_ARTIFACT_TOOL_NAME,
    create_fixture_server,
)


@pytest.mark.asyncio
async def test_the_fixture_is_usable_by_an_ordinary_mcp_client() -> None:
    async with Client(create_fixture_server(), timeout=1, init_timeout=1) as client:
        tools = await client.list_tools()
        fixture_tool = next(tool for tool in tools if tool.name == FIXTURE_TOOL_NAME)
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
        assert "set_status_artifact_status" in contents[0].text
        assert "ui/initialize" in contents[0].text


@pytest.mark.asyncio
async def test_the_fixture_creates_validates_and_semantically_edits_a_portable_artifact() -> None:
    async with Client(create_fixture_server(), timeout=1, init_timeout=1) as client:
        tools = await client.list_tools()
        names = {tool.name for tool in tools}
        assert {
            FIXTURE_CREATE_ARTIFACT_TOOL_NAME,
            FIXTURE_VALIDATE_ARTIFACT_TOOL_NAME,
            FIXTURE_EDIT_ARTIFACT_TOOL_NAME,
        } <= names

        draft = await client.call_tool(
            FIXTURE_CREATE_ARTIFACT_TOOL_NAME,
            {"title": "Foundation status for Bridge"},
        )
        assert draft.data == {
            "type": "agent-hub.fixture.status",
            "title": "Foundation status for Bridge",
            "summary": "Foundation fixture status.",
            "schema": {"id": "agent-hub.fixture.status", "version": "1.0"},
            "payload": {"status": "available"},
        }
        document = {
            "artifact": {
                "id": "artifact-1",
                "type": draft.data["type"],
                "documentVersion": 1,
                "title": draft.data["title"],
                "summary": draft.data["summary"],
                "schema": draft.data["schema"],
                "plugin": {"id": "foundation-fixture", "version": "0.1.0"},
                "provenance": {
                    "createdByThreadId": "thread-1",
                    "createdByRunId": "run-1",
                    "lastChangedByThreadId": "thread-1",
                    "lastChangedByRunId": "run-1",
                },
                "relations": [],
            },
            "payload": draft.data["payload"],
        }

        validated = await client.call_tool(
            FIXTURE_VALIDATE_ARTIFACT_TOOL_NAME,
            {"document": document},
        )
        edited = await client.call_tool(
            FIXTURE_EDIT_ARTIFACT_TOOL_NAME,
            {"document": document, "status": "unavailable"},
        )

    assert validated.data == document
    assert edited.data == {**document, "payload": {"status": "unavailable"}}
