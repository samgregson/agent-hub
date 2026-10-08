import json
from typing import Any, cast

import pytest

from agent_hub_api.modules.agent_execution._deep_agent import PostgresDeepAgentRunner
from agent_hub_api.modules.artifacts import ArtifactAccess, create_memory_artifact_module
from agent_hub_api.modules.plugin_gateway import (
    PluginManifest,
    PluginSelection,
    PluginTool,
    PluginToolResult,
)
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module


class FixtureGateway:
    manifest = PluginManifest(
        id="foundation-fixture",
        name="Foundation fixture",
        version="0.1.0",
        endpoint="http://fixture/mcp",
        tools=(
            PluginTool(name="create_status_artifact", read_only=False),
            PluginTool(name="set_status_artifact_status", read_only=False),
        ),
    )

    async def selections(self, *_: object) -> tuple[PluginSelection, ...]:
        return (PluginSelection(manifest=self.manifest, enabled=True),)

    async def call(
        self,
        _access: object,
        _project_id: str,
        _plugin_id: str,
        tool_name: str,
        arguments: dict[str, object],
    ) -> PluginToolResult:
        if tool_name == "create_status_artifact":
            return PluginToolResult(
                content=("Created status draft.",),
                structured_content={
                    "type": "agent-hub.fixture.status",
                    "title": arguments["title"],
                    "summary": "Fixture status is available.",
                    "schema": {"id": "agent-hub.fixture.status", "version": "1.0"},
                    "payload": {"status": "available"},
                },
            )
        assert tool_name == "set_status_artifact_status"
        document = cast(dict[str, Any], arguments["document"])
        document["payload"]["status"] = arguments["status"]
        return PluginToolResult(content=("Updated status.",), structured_content=document)


@pytest.mark.asyncio
async def test_two_threads_create_discover_and_plugin_edit_one_artifact() -> None:
    projects = create_memory_project_module()
    access = ProjectAccess(subject="sam")
    project = await projects.create(access, "Bridge")
    first = await projects.create_thread(access, project.id, "First")
    second = await projects.create_thread(access, project.id, "Second")
    artifacts = create_memory_artifact_module(projects, plugin_gateway=cast(Any, FixtureGateway()))

    first_tools = {
        item.name: item
        for item in PostgresDeepAgentRunner._artifact_tools(
            artifacts, project.id, access.subject, first.id, "run-first"
        )
    }
    second_tools = {
        item.name: item
        for item in PostgresDeepAgentRunner._artifact_tools(
            artifacts, project.id, access.subject, second.id, "run-second"
        )
    }

    await first_tools["create_project_artifact"].ainvoke(
        {
            "plugin_id": "foundation-fixture",
            "tool_name": "create_status_artifact",
            "arguments_json": '{"title":"Bridge status"}',
        }
    )
    summary = json.loads(await second_tools["discover_project_artifacts"].ainvoke({}))[0]
    artifact_id = summary["id"]
    assert summary == {
        "id": artifact_id,
        "title": "Bridge status",
        "type": "agent-hub.fixture.status",
        "version": 1,
    }
    loaded = json.loads(
        await second_tools["load_project_artifact"].ainvoke({"artifact_id": artifact_id})
    )
    assert loaded["payload"] == {"status": "available"}

    await second_tools["edit_project_artifact"].ainvoke(
        {
            "artifact_id": artifact_id,
            "expected_version": 1,
            "tool_name": "set_status_artifact_status",
            "arguments_json": '{"status":"unavailable"}',
        }
    )
    current = await artifacts.load(ArtifactAccess(subject="sam"), project.id, artifact_id)
    assert current.artifact.document_version == 2
    assert current.payload == {"status": "unavailable"}
    assert current.artifact.provenance.created_by.thread_id is not None
    assert current.artifact.provenance.created_by.run_id is not None
    assert current.artifact.provenance.last_changed_by.thread_id is not None
    assert current.artifact.provenance.last_changed_by.run_id is not None
    assert current.artifact.provenance.created_by.thread_id.root == first.id
    assert current.artifact.provenance.created_by.run_id.root == "run-first"
    assert current.artifact.provenance.last_changed_by.thread_id.root == second.id
    assert current.artifact.provenance.last_changed_by.run_id.root == "run-second"
