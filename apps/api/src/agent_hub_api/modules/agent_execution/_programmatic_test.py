import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agent_hub_api.modules.artifacts import ArtifactAccess, create_memory_artifact_module
from agent_hub_api.modules.datasets import DatasetModule, MemoryDatasetStore
from agent_hub_api.modules.functions import FunctionModule, MemoryFunctionStore
from agent_hub_api.modules.plugin_gateway import (
    MemoryPluginEnablementStore,
    PluginDiscoveredTool,
    PluginGatewayModule,
    PluginManifest,
    PluginNotEnabled,
    PluginTool,
    PluginToolResult,
    PluginUiResource,
)
from agent_hub_api.modules.project_files import (
    ProjectFileAccess,
    ProjectFileError,
    ProjectFileNotFound,
    create_memory_project_files,
)
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module
from agent_hub_api.modules.workflows import (
    MemoryWorkflowRunStore,
    MemoryWorkflowStore,
    WorkflowDefinitionModule,
    WorkflowRunModule,
)
from agent_hub_api.settings import Settings

from ._deep_agent import PostgresDeepAgentRunner
from ._programmatic import project_read_tools


class ProgramModel(BaseChatModel):
    code: str
    after: str | None = None

    @property
    def _llm_type(self) -> str:
        return "test-native-ptc"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ProgramModel":
        return self

    def _generate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        results = [message for message in messages if isinstance(message, ToolMessage)]
        if not results:
            message = AIMessage(
                content="",
                tool_calls=[{"id": "eval-1", "name": "eval", "args": {"code": self.code}}],
            )
        elif len(results) == 1 and self.after:
            message = AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "normal-write",
                        "name": self.after,
                        "args": {"file_path": "/project/approved.txt", "content": "approved"},
                    }
                ],
            )
        else:
            message = AIMessage(content="Finished.")
        return ChatResult(generations=[ChatGeneration(message=message)])


@dataclass
class PtcClient:
    calls: list[tuple[str, Mapping[str, object]]] = field(default_factory=list)

    async def discover_tools(self) -> tuple[PluginDiscoveredTool, ...]:
        return tuple(
            PluginDiscoveredTool(
                name=name,
                description="Test tool",
                read_only=read_only,
                input_schema={
                    "type": "object",
                    "properties": {"source": {"type": "string"}},
                    "required": ["source"],
                    "additionalProperties": False,
                },
            )
            for name, read_only in [("inspect", True), ("mutate", True), ("ambiguous", False)]
        )

    async def call_tool(self, name: str, arguments: Mapping[str, object]) -> PluginToolResult:
        self.calls.append((name, arguments))
        return PluginToolResult(content=("Inspected.",), structured_content={"count": 1})

    async def read_ui_resource(self, uri: str) -> PluginUiResource:
        raise AssertionError("No UI resource should be read")


async def setup_program(code: str, after: str | None = None) -> Any:
    projects = create_memory_project_module()
    access = ProjectAccess(subject="sam")
    project = await projects.create(access, "PTC")
    files = create_memory_project_files(projects)
    await files.create_visible(
        ProjectFileAccess(subject="sam"), project.id, "/source.txt", "SOURCE_BYTES"
    )
    client = PtcClient()
    manifest = PluginManifest(
        id="fixture",
        name="Fixture",
        version="1",
        endpoint="http://fixture/mcp",
        tools=(
            PluginTool(name="inspect", read_only=True),
            PluginTool(name="mutate", read_only=False),
            PluginTool(name="ambiguous", read_only=True),
        ),
    )
    gateway = PluginGatewayModule(
        projects, [manifest], MemoryPluginEnablementStore(), {"fixture": client}
    )
    await gateway.enable(access, project.id, "fixture")
    artifacts = create_memory_artifact_module(projects)
    datasets = DatasetModule(projects, MemoryDatasetStore())
    functions = FunctionModule(projects, MemoryFunctionStore())
    workflows = WorkflowDefinitionModule(
        projects, datasets, functions, gateway, MemoryWorkflowStore(), project_files=files
    )
    runs = WorkflowRunModule(
        workflows, datasets, functions, gateway, MemoryWorkflowRunStore(), project_files=files
    )
    runner = PostgresDeepAgentRunner(
        Settings(environment="test"),
        files,
        gateway,
        artifacts,
        datasets,
        functions,
        workflows,
        runs,
    )
    runner._checkpointer = InMemorySaver()
    runner._model = ProgramModel(code=code, after=after)
    agent = await runner._agent_for(
        project.id, thread_id="ptc-thread", run_id="ptc-run", subject="sam"
    )
    return project, files, gateway, artifacts, workflows, client, agent


def eval_result(result: dict[str, Any]) -> Any:
    message = next(
        item for item in result["messages"] if isinstance(item, ToolMessage) and item.name == "eval"
    )
    text = str(message.content)
    assert "<error" not in text, text
    return json.loads(text.split("<result>", 1)[1].split("</result>", 1)[0])


@pytest.mark.asyncio
async def test_native_ptc_reads_exact_files_and_mcp_data_without_saving_or_exposing_source() -> (
    None
):
    project, _, gateway, artifacts, _, client, agent = await setup_program("""
      const file = await tools.readProjectFile({path:"/project/source.txt",expected_version:1});
      const result = await tools.fixture_Inspect({source:file.content});
      JSON.stringify({count:result.structuredContent.count,version:file.version});
    """)
    result = await agent.graph.ainvoke(
        {"messages": [HumanMessage(content="Inspect the Project file.")]},
        config={"configurable": {"thread_id": "ptc-thread"}},
    )
    assert eval_result(result) == {"count": 1, "version": 1}
    assert client.calls == [("inspect", {"source": "SOURCE_BYTES"})]
    assert await artifacts.discover(ArtifactAccess(subject="sam"), project.id) == ()
    for message in result["messages"]:
        assert "SOURCE_BYTES" not in str(message.content)
    assert [
        tool.name
        for tool in await gateway.programmatic_tools(ProjectAccess(subject="sam"), project.id)
    ] == ["fixture__inspect"]


@pytest.mark.asyncio
async def test_ptc_has_no_mutation_workflow_subagent_or_host_access() -> None:
    project, files, _, artifacts, workflows, client, agent = await setup_program("""
      const forbidden=["writeFile","editFile","createProjectArtifact","editProjectArtifact",
        "createProjectWorkflow","reviseProjectWorkflow","prepareProjectWorkflowRun",
        "executeProjectWorkflowRun","createProjectDataset","updateProjectDataset",
        "deleteProjectDataset","createProjectFunction","updateProjectFunction",
        "previewProjectFunction","fixture_Mutate","fixture_Ambiguous","eval","execute"];
      const exposed=forbidden.filter(name=>typeof tools[name]!=="undefined");
      let denied=false;
      try {await tools.writeFile({file_path:"/project/forbidden.txt",content:"no"});}
      catch {denied=true;}
      JSON.stringify({exposed,denied,task:typeof task,fetch:typeof fetch,process:typeof process});
    """)
    result = await agent.graph.ainvoke(
        {"messages": [HumanMessage(content="Probe interpreter permissions.")]},
        config={"configurable": {"thread_id": "ptc-thread"}},
    )
    assert eval_result(result) == {
        "exposed": [],
        "denied": True,
        "task": "undefined",
        "fetch": "undefined",
        "process": "undefined",
    }
    assert client.calls == []
    assert await artifacts.discover(ArtifactAccess(subject="sam"), project.id) == ()
    assert await workflows.list(ProjectAccess(subject="sam"), project.id) == ()
    assert [file.path for file in await files.list(project.id)] == ["/source.txt"]


@pytest.mark.asyncio
async def test_normal_file_write_still_requires_approval_after_ptc() -> None:
    project, files, _, _, _, _, agent = await setup_program(
        "JSON.stringify({ready:true});", after="write_file"
    )
    config = {"configurable": {"thread_id": "ptc-thread"}}
    result = await agent.graph.ainvoke(
        {"messages": [HumanMessage(content="Inspect, then propose a save.")]}, config=config
    )
    assert result["__interrupt__"]
    with pytest.raises(ProjectFileNotFound):
        await files.load(project.id, "/approved.txt")
    completed = await agent.graph.ainvoke(
        Command(resume={"decisions": [{"type": "approve"}]}), config=config
    )
    assert not completed.get("__interrupt__")
    assert (await files.load(project.id, "/approved.txt")).content == "approved"


@pytest.mark.asyncio
async def test_ptc_rechecks_enablement_and_file_authorization() -> None:
    project, files, gateway, _, _, client, _ = await setup_program("1")
    tools = await gateway.programmatic_tools(ProjectAccess(subject="sam"), project.id)
    await gateway.disable(ProjectAccess(subject="sam"), project.id, "fixture")
    with pytest.raises(PluginNotEnabled):
        await tools[0].ainvoke({"source": "test"})
    assert client.calls == []
    _, read = project_read_tools(files, project.id, "another-subject")
    with pytest.raises(ProjectFileNotFound):
        await read.ainvoke({"path": "/project/source.txt", "expected_version": 1})


@pytest.mark.asyncio
async def test_raw_read_rejects_stale_versions_and_non_project_paths() -> None:
    project, files, _, _, _, _, _ = await setup_program("1")
    _, read = project_read_tools(files, project.id, "sam")
    await files.write(project.id, "/source.txt", "UPDATED_SOURCE")
    with pytest.raises(ValueError, match="changed"):
        await read.ainvoke({"path": "/project/source.txt", "expected_version": 1})
    for path in (
        "/tmp/source.txt",
        "/scratch/source.txt",
        "https://example.com/file",
        "/project/../source.txt",
    ):
        with pytest.raises((ValueError, ProjectFileError)):
            await read.ainvoke({"path": path, "expected_version": 2})
