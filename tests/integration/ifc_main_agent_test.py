"""Native read-only PTC over real IFC MCP, then a normal approval-gated Workflow.

A deterministic model tests orchestration. The IFC server runs independently.
"""

import asyncio
import json
import os
import socket
import subprocess
from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agent_hub_api.modules.agent_execution._deep_agent import PostgresDeepAgentRunner
from agent_hub_api.modules.artifacts import ArtifactAccess, create_memory_artifact_module
from agent_hub_api.modules.datasets import DatasetModule, MemoryDatasetStore
from agent_hub_api.modules.functions import FunctionModule, MemoryFunctionStore
from agent_hub_api.modules.functions._runner import DenoFunctionRunner
from agent_hub_api.modules.plugin_gateway import (
    McpPluginClient,
    MemoryPluginEnablementStore,
    PluginGatewayModule,
    PluginManifest,
    PluginTool,
    PluginTransportError,
)
from agent_hub_api.modules.project_files import ProjectFileAccess, create_memory_project_files
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module
from agent_hub_api.modules.workflows import (
    MemoryWorkflowRunStore,
    MemoryWorkflowStore,
    WorkflowDefinitionModule,
    WorkflowRunModule,
)
from agent_hub_api.settings import Settings

ROOT = Path(__file__).parents[2]
IFC_PYTHON = os.environ.get("AGENT_HUB_IFC_PYTHON")
pytestmark = pytest.mark.skipif(
    not IFC_PYTHON, reason="Requires the independently installed IFC MCP service"
)


def summary_from_eval(message: ToolMessage) -> dict[str, Any]:
    text = str(message.content)
    assert "<error" not in text, text
    return json.loads(text.split("<result>", 1)[1].split("</result>", 1)[0])


class AssignmentModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "deterministic-native-ptc-ifc"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "AssignmentModel":
        return self

    def _generate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        results = [message for message in messages if isinstance(message, ToolMessage)]
        latest = results[-1] if results else None
        if latest is None:
            name, args = "ifc_viewer__get_ifc_guide", {}
        elif latest.name == "ifc_viewer__get_ifc_guide":
            name, args = (
                "eval",
                {
                    "code": """
              const files=JSON.parse(await tools.listProjectFiles({query:"beam.ifc"}));
              const source=files.files[0];
              const file=await tools.readProjectFile({
                path:source.path,expected_version:source.version});
              const inspected=await tools.ifcViewer_InspectIfcObjects({ifc_text:file.content});
              const metadata=inspected.structuredContent.objects.filter(o=>o.ifcType==="IfcBeam")
                .map(o=>({globalId:o.globalId,values:{status:"reviewed"}}));
              const view=await tools.ifcViewer_PrepareIfcView({ifc_text:file.content,
                metadata,colour_by:"status"});
              JSON.stringify({source,metadata,kind:view.structuredContent.kind,
                modelSha256:view.structuredContent.modelSha256});
            """
                },
            )
        elif latest.name == "eval":
            summary = summary_from_eval(latest)
            assert summary["kind"] == "ifc.view"
            name, args = (
                "create_project_workflow",
                {
                    "name": "IFC reviewed beams",
                    "graph_json": {
                        "nodes": [
                            {
                                "id": "source",
                                "kind": "file",
                                "ref_id": summary["source"]["path"],
                                "version": summary["source"]["version"],
                            },
                            {
                                "id": "view",
                                "kind": "mcp",
                                "ref_id": "ifc-viewer",
                                "version": "0.1.0",
                                "tool_name": "prepare_ifc_view",
                            },
                        ],
                        "edges": [
                            {
                                "source_kind": "node",
                                "source_node": "source",
                                "source_port": "content",
                                "target_node": "view",
                                "target_port": "ifc_text",
                            },
                            {
                                "source_kind": "literal",
                                "literal": summary["metadata"],
                                "target_node": "view",
                                "target_port": "metadata",
                            },
                            {
                                "source_kind": "literal",
                                "literal": "status",
                                "target_node": "view",
                                "target_port": "colour_by",
                            },
                        ],
                        "outputs": [{"name": "view", "node": "view", "port": "result"}],
                    },
                },
            )
        elif latest.name == "create_project_workflow":
            assert "workflowId" in json.loads(str(latest.content))
            return ChatResult(
                generations=[
                    ChatGeneration(
                        message=AIMessage(
                            content="The approved Workflow is saved; the PTC preview was transient."
                        )
                    )
                ]
            )
        else:
            raise AssertionError(f"Unexpected tool: {latest.name}: {latest.content}")
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "id": f"step-{len(results)}",
                                "name": name,
                                "args": args,
                            }
                        ],
                    )
                )
            ]
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("engineering", [False, True])
async def test_main_agent_reads_ifc_and_assigns_metadata_through_mcp(engineering: bool) -> None:
    runner_url = os.environ.get("AGENT_HUB_FUNCTION_RUNNER_URL")
    if engineering and not runner_url:
        pytest.skip("Requires the real isolated Python runner")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    command = [
        str(Path(IFC_PYTHON).absolute()),
        "-c",
        "from agent_hub_ifc_viewer._server import create_ifc_viewer_server; "
        + f"create_ifc_viewer_server().run(transport='http',host='127.0.0.1',port={port})",
    ]
    process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.DEVNULL)
    try:
        client = McpPluginClient(
            endpoint=f"http://127.0.0.1:{port}/mcp",
            timeout_seconds=10,
            max_result_bytes=1_000_000,
            max_ui_resource_bytes=12_000_000,
            allow_private_network=True,
        )
        for attempt in range(30):
            try:
                await client.discover_tools()
                break
            except PluginTransportError:
                if attempt == 29:
                    raise
                await asyncio.sleep(0.2)
        projects = create_memory_project_module()
        access = ProjectAccess(subject="sam")
        project = await projects.create(access, "IFC agent test")
        files = create_memory_project_files(projects)
        source = (ROOT / "plugins/ifc-viewer/app/tests/beam.ifc").read_text()
        await files.create_visible(
            ProjectFileAccess(subject="sam"), project.id, "/beam.ifc", source
        )
        manifest = PluginManifest(
            id="ifc-viewer",
            name="IFC viewer",
            version="0.1.0",
            endpoint=client.endpoint,
            app_resource_uri="ui://agent-hub-ifc-viewer/view.html",
            app_allow_wasm=True,
            tools=tuple(
                PluginTool(name=name, read_only=True, repeat_safe=True)
                for name in ("get_ifc_guide", "inspect_ifc_objects", "prepare_ifc_view")
            ),
        )
        gateway = PluginGatewayModule(
            projects, [manifest], MemoryPluginEnablementStore(), {manifest.id: client}
        )
        await gateway.enable(access, project.id, manifest.id)
        artifacts = create_memory_artifact_module(projects)
        datasets = DatasetModule(projects, MemoryDatasetStore())
        functions = FunctionModule(
            projects, MemoryFunctionStore(), DenoFunctionRunner(runner_url) if runner_url else None
        )
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
        runner._model = AssignmentModel()
        runner._checkpointer = InMemorySaver()
        agent = await runner._agent_for(
            project.id, thread_id="thread-ifc", run_id="run-ifc", subject="sam"
        )
        config = {"configurable": {"thread_id": "thread-ifc"}, "recursion_limit": 25}
        result = await agent.graph.ainvoke(
            {
                "messages": [
                    HumanMessage(
                        content=(
                            "Inspect /project/beam.ifc, preview reviewed status on beams, "
                            "then propose a saved Workflow."
                        )
                    )
                ]
            },
            config=config,
        )
        assert result["__interrupt__"]
        assert (
            result["__interrupt__"][0].value["action_requests"][0]["name"]
            == "create_project_workflow"
        )
        # PTC inspection and view preparation produced no durable changes.
        assert await artifacts.discover(ArtifactAccess(subject="sam"), project.id) == ()
        assert await workflows.list(access, project.id) == ()
        assert [file.path for file in await files.list(project.id)] == ["/beam.ifc"]
        completed = await agent.graph.ainvoke(
            Command(resume={"decisions": [{"type": "approve"}]}), config=config
        )
        assert not completed.get("__interrupt__")
        for message in completed["messages"]:
            assert "ISO-10303-21;" not in str(message.content)
            if isinstance(message, AIMessage):
                assert "ISO-10303-21;" not in json.dumps(message.tool_calls)
        definition = (await workflows.list(access, project.id))[0]
        # Simulate the user's normal Workflow Run action outside PTC.
        prepared = await runs.prepare(
            access,
            project.id,
            definition.id,
            "approved-ifc-smoke",
            expected_version=definition.version,
        )
        executed = await runs.execute(access, project.id, prepared.id)
        assert executed.status == "succeeded", executed.execution
        view = executed.execution["outputs"]["view"]
        assert view["ifcText"] == source
        assert view["colourBy"] == "status"
        assert len(view["metadata"]) == 1
        assert view["metadata"][0]["values"] == {"status": "reviewed"}
        resource = await runs.app_resource(access, project.id, definition.id, executed.id, "view")
        assert "wasm-unsafe-eval" in resource.content_security_policy
        assert "<html" in resource.html.lower()
        assert await artifacts.discover(ArtifactAccess(subject="sam"), project.id) == ()
        # Browser API fixture wraps the captured Workflow output, not a PTC auto-save.
        if engineering:
            view = await check_engineering_workflow(
                runner, functions, workflows, runs, access, project.id, source
            )
        export_path = os.environ.get("AGENT_HUB_IFC_SMOKE_ARTIFACT")
        if export_path:
            fixture = {
                "artifact": {
                    "id": "ifc-workflow-smoke",
                    "title": "IFC beam review",
                    "type": "ifc.view",
                    "documentVersion": 1,
                    "plugin": {"id": "ifc-viewer", "version": "0.1.0"},
                    "schema": {"id": "agent-hub.tool-result-snapshot", "version": "1.0"},
                    "relations": [],
                    "provenance": {
                        "createdBy": {
                            "kind": "agentRun",
                            "threadId": "thread-ifc",
                            "runId": "run-ifc",
                        },
                        "lastChangedBy": {
                            "kind": "agentRun",
                            "threadId": "thread-ifc",
                            "runId": "run-ifc",
                        },
                    },
                },
                "payload": {"input": {"ifc_text": source}, "output": view},
            }
            Path(export_path).write_text(json.dumps(fixture), encoding="utf-8")
    finally:
        process.terminate()
        process.wait(timeout=5)


async def check_engineering_workflow(
    runner: PostgresDeepAgentRunner,
    functions: FunctionModule,
    workflows: WorkflowDefinitionModule,
    runs: WorkflowRunModule,
    access: ProjectAccess,
    project_id: str,
    source: str,
) -> dict[str, Any]:
    """Author through actual agent tool contracts, invoking reviewed actions directly.

    The graph-interrupt test above covers approval; this exercises real calculations.
    """
    tools = {
        t.name: t
        for t in [
            *runner._function_tools(functions, project_id, access.subject),
            *runner._workflow_tools(workflows, runs, project_id, access.subject),
        ]
    }

    async def call(tool_name: str, **args: Any) -> Any:
        raw = await tools[tool_name].ainvoke(args)
        try:
            result = json.loads(raw)
        except (ValueError, TypeError) as error:
            raise AssertionError(f"{tool_name}: {raw}") from error
        assert "error" not in result, result
        return result

    arrays = {"type": "array", "items": {"type": "object"}}
    function = await call(
        "create_project_function",
        name="IFC imposed-load deflection overlay",
        source=(ROOT / "tests/fixtures/ifc-beam-check/transform.py").read_text(),
        input_schema={
            "type": "object",
            "description": "Join explicit engineering inputs by IFC GlobalId.",
            "properties": {"objects": arrays, "beam_inputs": arrays},
            "required": ["objects", "beam_inputs"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {"metadata": arrays},
            "required": ["metadata"],
        },
    )
    # Use the actual inspection, never hardcode the model's identifiers.
    inspected = await runner._plugin_gateway.call(
        access, project_id, "ifc-viewer", "inspect_ifc_objects", {"ifc_text": source}
    )
    objects = inspected.structured_content["objects"]
    beam = next(o for o in objects if o["ifcType"] == "IfcBeam")
    preview = await call(
        "preview_project_function",
        function_id=function["id"],
        inputs={"objects": objects, "beam_inputs": []},
    )
    missing = preview["output"]["metadata"][0]["values"]
    assert missing["status"] == "missing_inputs"
    assert "span_m" in missing["missing_inputs"]
    assert "support_condition" in missing["missing_inputs"]

    def edge(
        source_node: str,
        source_port: str,
        target_node: str,
        target_port: str,
        source_path: str = "",
    ) -> dict[str, str]:
        return {
            "source_kind": "node",
            "source_node": source_node,
            "source_port": source_port,
            "target_node": target_node,
            "target_port": target_port,
            "source_path": source_path,
        }

    graph = {
        "nodes": [
            {"id": "source", "kind": "file", "ref_id": "/project/beam.ifc", "version": 1},
            {
                "id": "inspect",
                "kind": "mcp",
                "ref_id": "ifc-viewer",
                "version": "0.1.0",
                "tool_name": "inspect_ifc_objects",
            },
            {
                "id": "check",
                "kind": "python",
                "ref_id": function["id"],
                "version": function["revision"],
            },
            {
                "id": "view",
                "kind": "mcp",
                "ref_id": "ifc-viewer",
                "version": "0.1.0",
                "tool_name": "prepare_ifc_view",
            },
        ],
        "edges": [
            edge("source", "content", "inspect", "ifc_text"),
            edge("source", "content", "view", "ifc_text"),
            edge("inspect", "result", "check", "objects", "/objects"),
            edge("check", "result", "view", "metadata", "/metadata"),
            {
                "source_kind": "workflowInput",
                "source_input": "beam_inputs",
                "target_node": "check",
                "target_port": "beam_inputs",
            },
            {
                "source_kind": "literal",
                "literal": "status",
                "target_node": "view",
                "target_port": "colour_by",
            },
        ],
        "inputs": [{"name": "beam_inputs", "schema": arrays}],
        "outputs": [
            {"name": "view", "node": "view", "port": "result"},
            {"name": "checks", "node": "check", "port": "result"},
        ],
    }
    definition = await call("create_project_workflow", name="IFC beam deflection", graph_json=graph)
    row = {
        "globalId": beam["globalId"],
        "support_condition": "simply_supported",
        "span_m": 4.0,
        "imposed_load_kn_m2": 3.0,
        "tributary_width_m": 3.0,
        "elastic_modulus_gpa": 210.0,
        "inertia_mm4": 16_000_000.0,
        "deflection_limit_ratio": 360.0,
    }
    final_view = None
    for case, rows, expected in (
        ("missing", [], "missing_inputs"),
        ("passes", [row], "passes"),
        ("fails", [{**row, "inertia_mm4": 800_000.0}], "fails"),
    ):
        prepared = await call(
            "prepare_project_workflow_run",
            workflow_id=definition["workflowId"],
            idempotency_key=f"engineering-{case}",
            expected_version=definition["version"],
            workflow_inputs={"beam_inputs": rows},
        )
        executed = await call("execute_project_workflow_run", run_id=prepared["runId"])
        assert executed["status"] == "succeeded", executed
        view = executed["execution"]["outputs"]["view"]
        assert view["ifcText"] == source
        assert view["colourBy"] == "status"
        assert view["metadata"][0]["globalId"] == beam["globalId"]
        values = view["metadata"][0]["values"]
        assert values["status"] == expected
        if case != "missing":
            assert values["deflection_mm"] == pytest.approx(
                8.92857142857 if case == "passes" else 178.57142857
            )
            assert values["limit_mm"] == pytest.approx(11.111111111)
        final_view = view
    for rows in (
        [row, row],
        [{**row, "globalId": "unknown-object"}],
        [{**row, "support_condition": "cantilever"}],
        [{**row, "inertia_mm4": 0}],
    ):
        raw = await tools["preview_project_function"].ainvoke(
            {"function_id": function["id"], "inputs": {"objects": objects, "beam_inputs": rows}}
        )
        assert json.loads(raw)["error"]["code"] == "function_preview_failed", raw
    assert final_view is not None
    export_path = os.environ.get("AGENT_HUB_IFC_SMOKE_ARTIFACT")
    if export_path:
        Path(export_path + ".workflow.json").write_text(
            json.dumps(
                {
                    "workflow": await call(
                        "load_project_workflow", workflow_id=definition["workflowId"]
                    ),
                    "run": await call("load_project_workflow_run", run_id=prepared["runId"]),
                }
            )
        )
    return final_view
