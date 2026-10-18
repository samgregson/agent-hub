import json
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import AsyncExitStack
from dataclasses import asdict
from typing import Any
from urllib.parse import quote

from ag_ui.core import BaseEvent, RunAgentInput
from ag_ui_langgraph.utils import langchain_messages_to_agui
from deepagents import create_deep_agent
from deepagents.middleware.filesystem import FilesystemPermission
from langchain.agents.middleware import (
    AgentMiddleware,
    InterruptOnConfig,
    ModelRequest,
    ModelResponse,
    wrap_model_call,
)
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool, tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.base import BaseCheckpointSaver

from agent_hub_api.modules.agent_execution._ag_ui import (
    AgentHubLangGraphAgent,
    map_langchain_interrupts,
)
from agent_hub_api.modules.agent_execution._execution import (
    AgentThreadState,
    ScratchFile,
    ScratchFileNotFound,
)
from agent_hub_api.modules.agent_execution._project_files_backend import (
    create_project_files_backend,
)
from agent_hub_api.modules.artifacts import ArtifactAccess, ArtifactModule, ArtifactMutationAccess
from agent_hub_api.modules.datasets import DatasetModule, DatasetRecordInput
from agent_hub_api.modules.functions import (
    FunctionExecutionError,
    FunctionModule,
    FunctionNotFound,
    FunctionValidationError,
)
from agent_hub_api.modules.plugin_gateway import (
    PluginGatewayModule,
    PluginManifest,
    PluginResultRecorder,
    PluginTool,
    PluginToolResult,
)
from agent_hub_api.modules.project_files import ProjectFilesModule
from agent_hub_api.modules.projects import ProjectAccess
from agent_hub_api.modules.workflows import (
    WorkflowDefinitionModule,
    WorkflowGraph,
    WorkflowImage,
    WorkflowNotFound,
    WorkflowRunConflict,
    WorkflowRunModule,
    WorkflowValidationError,
)
from agent_hub_api.settings import Settings


def _tool_error(code: str, message: str, next_step: str) -> str:
    """Return a compact, machine-readable error that tells the agent how to recover."""
    return json.dumps(
        {"ok": False, "error": {"code": code, "message": message}, "nextStep": next_step}
    )


_AGENT_SYSTEM_PROMPT = "\n\n".join(
    (
        "Use /project for durable files shared by every Thread in the selected Project "
        "and /scratch for Thread-local working files. Never claim access to the host filesystem. "
        "Link virtual files with absolute /project or /scratch paths.",
        "Project file writes, Dataset changes, Function changes, Workflow changes, and "
        "Workflow execution require approval. Start the appropriate tool action without asking "
        "for approval in chat; the approval card is shown automatically. Wait for its result.",
        "Datasets are registered Project Files under /project/.datasets. Use Dataset tools for "
        "Dataset changes; generic file writes cannot change registered Dataset files. When a "
        "user asks for a structured multi-row result, prefer a Dataset table over a large JSON "
        "array in chat. Inspect for a suitable Dataset and update it only when asked to replace "
        "or extend it. Pass records as an array of row objects; optional sourceKey identifies a "
        "row and is stored separately. Report the Dataset name, record count, and a short summary.",
        "Python Functions are authored as transform(inputs, parameters). Use Function tools to "
        "discover, inspect, create, revise, delete, or preview them. Pass input_schema and "
        "output_schema as JSON Schema objects, and pass preview inputs and parameters as objects. "
        "Workflow edges provide named inputs. A preview is transient and creates no durable Run; "
        "use it when a code or data-shape check is useful.",
        "Workflow is the durable execution path for Python Functions and MCP tools. Inspect only "
        "the Project assets needed for the request and reuse a matching source or capability. Use "
        "IDs and versions returned by tools. A Dataset Workflow node's records port is an array "
        "of the original row values; it does not include the id/sourceKey/value wrappers returned "
        "by the Dataset loading tool. Declare a Function input schema that matches those row "
        "values, and have the Function consume each row directly. Bind the whole records array "
        "instead of guessing nested paths.",
        "Workflow Definitions are saved Project DAGs. Pass graph_json as an object with nodes, "
        "edges, outputs, and optional inputs. Each node has id, kind, ref_id, and version "
        "(optionally shape, tool_name, and map_input); kinds are dataset, file, python, and mcp. "
        "Edges use target_node and target_port. A node binding uses source_kind='node', "
        "source_node, and source_port. A run-time input uses source_kind='workflowInput' and "
        "source_input; a constant uses source_kind='literal' and literal. Workflow Inputs have "
        "name, JSON Schema in schema, and optional required. source_path and target_path are RFC "
        "6901 JSON Pointers; empty means the whole value. source_path selects within the source "
        "value; target_path selects or assembles within the target input. target_port names a "
        "Function input, "
        "so leave target_path empty unless assembling a nested input. Each output has name, node, "
        "and port. Python nodes use the saved Function UUID as ref_id and its revision as "
        "version; never put a Function name in ref_id. The result port is the complete Function "
        "output object; Workflow output schema properties are inside the result value, not "
        "separate "
        "ports. Map invokes a one-item Function for each item; use a single node when its Function "
        "accepts a collection. Never map a collection filter. Do not use a node map, from/to edge "
        "keys, or an outputs map. MCP nodes use the enabled Plugin ID, version, "
        "and tool_name. Project File nodes use an absolute /project path and current integer "
        "version; file content is text, including JSON. Use discover_project_file_sources for "
        "Project File Workflow inputs, never /scratch paths.",
        "create_project_workflow and revise_project_workflow validate their graph. For a direct "
        "Dataset-to-Function graph with current IDs, revisions, and matching declared schemas, "
        "create it without a separate validation call. Use validate_project_workflow when a "
        "complex graph or uncertain binding benefits from preflight. If a tool "
        "reports an error, correct the named reference, schema, or binding and retry with the "
        "corrected input. Never repeat an unchanged failing call. Use the revision returned by a "
        "Function update in the Workflow node; reload only when that revision is unavailable.",
        "To run a Workflow, prepare it once with its declared workflow_inputs, then execute the "
        "prepared Run. Inspect saved outputs and diagnostics. Do not repeat a failed Run "
        "unchanged.",
        "The isolated Python runner supports matplotlib and loads it when imported; it does not "
        "provide pandas or general network access. For a PNG Function output, import io, base64, "
        "and matplotlib.pyplot as plt, save the figure to "
        "io.BytesIO and return {kind: 'image', mimeType: 'image/png', dataBase64: "
        "base64.b64encode(buffer.getvalue()).decode(), altText}; keep encoded data under 90 KB. "
        "Workflow image outputs render in the Workflow view. Use view_image when visual "
        "inspection helps, and use its exact Markdown image link to show an image in chat.",
    )
)


def _without_image_data(value: Any) -> Any:
    """Keep image metadata in ordinary tool output and load pixels only on request."""
    if isinstance(value, Mapping):
        if value.get("kind") == "image" and isinstance(value.get("dataBase64"), str):
            return {
                key: _without_image_data(item) for key, item in value.items() if key != "dataBase64"
            } | {"imageAvailable": True}
        return {key: _without_image_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_without_image_data(item) for item in value]
    if isinstance(value, tuple):
        return [_without_image_data(item) for item in value]
    return value


@tool
def foundation_protected_action(note: str) -> str:
    """Echo a note after human approval to verify the interrupt transport."""
    return f"Approved foundation action: {note}"


def _project_file_permissions() -> list[FilesystemPermission]:
    """Require an explicit decision before a Deep Agents file tool mutates a Project."""
    return [FilesystemPermission(operations=["write"], paths=["/project/**"], mode="interrupt")]


def _project_change_notice_middleware(change_notice: str) -> AgentMiddleware[Any, Any]:
    """Add an out-of-band Project change notice to each model call only."""

    @wrap_model_call
    async def inject_project_change_notice(
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        return await handler(
            request.override(
                messages=[
                    *request.messages,
                    HumanMessage(content=f"[System Notification]: {change_notice}"),
                ]
            )
        )

    return inject_project_change_notice


class PostgresDeepAgentRunner:
    """Lazily owns the Deep Agent and its long-lived PostgreSQL checkpointer."""

    def __init__(
        self,
        settings: Settings,
        project_files: ProjectFilesModule,
        plugin_gateway: PluginGatewayModule | None = None,
        artifacts: ArtifactModule | None = None,
        datasets: DatasetModule | None = None,
        functions: FunctionModule | None = None,
        workflows: WorkflowDefinitionModule | None = None,
        workflow_runs: WorkflowRunModule | None = None,
    ) -> None:
        self._settings = settings
        self._project_files = project_files
        self._plugin_gateway = plugin_gateway
        self._artifacts = artifacts
        self._datasets = datasets
        self._functions = functions
        self._workflows = workflows
        self._workflow_runs = workflow_runs
        self._stack: AsyncExitStack | None = None
        self._checkpointer: BaseCheckpointSaver[Any] | None = None
        self._model: ChatOpenAI | None = None

    async def open(self) -> None:
        if self._stack is not None:
            return
        if self._settings.openai_api_key is None:
            raise RuntimeError("AGENT_HUB_OPENAI_API_KEY is required to run the agent")

        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        except ImportError as error:
            raise RuntimeError(
                "langgraph-checkpoint-postgres must be installed to run the agent"
            ) from error

        stack = AsyncExitStack()
        checkpointer = await stack.enter_async_context(
            AsyncPostgresSaver.from_conn_string(str(self._settings.database_url))
        )
        await checkpointer.setup()
        model = ChatOpenAI(
            api_key=self._settings.openai_api_key,
            model=self._settings.openai_model,
        )
        self._checkpointer = checkpointer
        self._model = model
        self._stack = stack

    async def _agent_for(
        self,
        project_id: str,
        *,
        thread_id: str | None = None,
        run_id: str | None = None,
        subject: str | None = None,
        change_notice: str | None = None,
    ) -> AgentHubLangGraphAgent:
        assert self._checkpointer is not None
        assert self._model is not None
        tools = [foundation_protected_action] if self._settings.enable_foundation_test_tool else []
        if self._plugin_gateway is not None:
            tools.extend(
                await self._plugin_gateway.agent_tools(
                    project_id,
                    on_success=self._snapshot_recorder(project_id, thread_id, run_id, subject),
                )
            )
        artifacts = getattr(self, "_artifacts", None)
        has_artifact_context = artifacts is not None and subject is not None
        if has_artifact_context:
            assert artifacts is not None
            assert subject is not None
            tools.extend(self._artifact_tools(artifacts, project_id, subject, thread_id, run_id))
        datasets = getattr(self, "_datasets", None)
        if datasets is not None and subject is not None:
            tools.extend(self._dataset_tools(datasets, project_id, subject))
        functions = getattr(self, "_functions", None)
        if functions is not None and subject is not None:
            tools.extend(self._function_tools(functions, project_id, subject))
        workflows = getattr(self, "_workflows", None)
        workflow_runs = getattr(self, "_workflow_runs", None)
        if workflows is not None and subject is not None:
            tools.extend(self._workflow_tools(workflows, workflow_runs, project_id, subject))
        interrupt_on: dict[str, bool | InterruptOnConfig] = {}
        if self._settings.enable_foundation_test_tool:
            interrupt_on.update(
                {
                    "foundation_protected_action": {
                        "allowed_decisions": ["approve", "reject"],
                        "description": "Run the harmless foundation approval test action?",
                    }
                }
            )
        if has_artifact_context and thread_id is not None and run_id is not None:
            interrupt_on.update(
                {
                    "create_project_artifact": {
                        "allowed_decisions": ["approve", "reject"],
                        "description": "Create the proposed Project Artifact?",
                    },
                    "edit_project_artifact": {
                        "allowed_decisions": ["approve", "reject"],
                        "description": "Apply the proposed Plugin edit to this Artifact?",
                    },
                }
            )
        if datasets is not None and subject is not None:
            interrupt_on.update(
                {
                    "create_project_dataset": {
                        "allowed_decisions": ["approve", "reject"],
                        "description": "Create the proposed Project Dataset?",
                    },
                    "delete_project_dataset": {
                        "allowed_decisions": ["approve", "reject"],
                        "description": "Delete the proposed Project Dataset?",
                    },
                    "update_project_dataset": {
                        "allowed_decisions": ["approve", "reject"],
                        "description": "Update the proposed Project Dataset?",
                    },
                }
            )
        if functions is not None and subject is not None:
            interrupt_on.update(
                {
                    "create_project_function": {
                        "allowed_decisions": ["approve", "reject"],
                        "description": "Create the proposed Python Function?",
                    },
                    "update_project_function": {
                        "allowed_decisions": ["approve", "reject"],
                        "description": "Update the proposed Python Function?",
                    },
                    "delete_project_function": {
                        "allowed_decisions": ["approve", "reject"],
                        "description": "Delete the proposed Python Function?",
                    },
                }
            )
        if workflows is not None and subject is not None:
            interrupt_on["create_project_workflow"] = {
                "allowed_decisions": ["approve", "reject"],
                "description": "Create this Workflow Definition?",
            }
            interrupt_on["revise_project_workflow"] = {
                "allowed_decisions": ["approve", "reject"],
                "description": "Revise this Workflow Definition?",
            }
            if workflow_runs is not None:
                interrupt_on["prepare_project_workflow_run"] = {
                    "allowed_decisions": ["approve", "reject"],
                    "description": "Prepare this Workflow Run snapshot?",
                }
                interrupt_on["execute_project_workflow_run"] = {
                    "allowed_decisions": ["approve", "reject"],
                    "description": "Execute this Workflow Run?",
                }
        graph = create_deep_agent(
            model=self._model,
            tools=tools,
            system_prompt=_AGENT_SYSTEM_PROMPT,
            interrupt_on=interrupt_on or None,
            permissions=_project_file_permissions(),
            backend=create_project_files_backend(self._project_files, project_id),
            checkpointer=self._checkpointer,
            middleware=(
                [_project_change_notice_middleware(change_notice)]
                if change_notice is not None
                else []
            ),
        )
        agent = AgentHubLangGraphAgent(
            name="agent-hub",
            graph=graph,
            config={"recursion_limit": self._settings.agent_recursion_limit},
            enable_legacy_on_interrupt_event=False,
            emit_interrupt_outcome=True,
        )
        return agent

    def _snapshot_recorder(
        self, project_id: str, thread_id: str | None, run_id: str | None, subject: str | None
    ) -> PluginResultRecorder | None:
        if self._artifacts is None or thread_id is None or run_id is None or subject is None:
            return None
        artifacts = self._artifacts

        async def record(
            manifest: PluginManifest,
            tool: PluginTool,
            arguments: Mapping[str, object],
            result: PluginToolResult,
        ) -> None:
            if result.structured_content is None:
                return
            await artifacts.create_tool_result_snapshot(
                ArtifactMutationAccess(subject=subject, thread_id=thread_id, run_id=run_id),
                project_id,
                plugin_id=manifest.id,
                plugin_version=manifest.version,
                tool_name=tool.name,
                arguments=arguments,
                structured_content=result.structured_content,
            )

        return record

    @staticmethod
    def _artifact_tools(
        artifacts: ArtifactModule,
        project_id: str,
        subject: str,
        thread_id: str | None = None,
        run_id: str | None = None,
    ) -> list[BaseTool]:
        @tool
        async def discover_project_artifacts() -> str:
            """List compact summaries of Artifacts in this Project on demand."""
            documents = await artifacts.discover(ArtifactAccess(subject=subject), project_id)
            return json.dumps(
                [
                    {
                        "id": document.artifact.id.root,
                        "title": document.artifact.title,
                        "type": document.artifact.type,
                        "version": document.artifact.document_version,
                    }
                    for document in documents
                ]
            )

        @tool
        async def load_project_artifact(artifact_id: str) -> str:
            """Load one Project Artifact by ID when its complete document is needed."""
            document = await artifacts.load(
                ArtifactAccess(subject=subject), project_id, artifact_id
            )
            return document.model_dump_json(by_alias=True)

        tools: list[BaseTool] = [discover_project_artifacts, load_project_artifact]
        if thread_id is None or run_id is None:
            return tools

        access = ArtifactMutationAccess(subject=subject, thread_id=thread_id, run_id=run_id)

        @tool
        async def create_project_artifact(
            plugin_id: str, tool_name: str, arguments: dict[str, Any]
        ) -> str:
            """Create an Artifact with an enabled Plugin tool after user approval."""
            document = await artifacts.create_from_plugin(
                access,
                project_id,
                plugin_id=plugin_id,
                tool_name=tool_name,
                arguments=_artifact_arguments(arguments),
            )
            return (
                f"Created Artifact {document.artifact.title} "
                f"({document.artifact.id.root}, v{document.artifact.document_version})."
            )

        @tool
        async def edit_project_artifact(
            artifact_id: str,
            expected_version: int,
            tool_name: str,
            arguments: dict[str, Any],
        ) -> str:
            """Apply a semantic Plugin edit to a current Artifact after user approval."""
            document = await artifacts.apply_plugin_operation(
                access,
                project_id,
                artifact_id,
                expected_version=expected_version,
                tool_name=tool_name,
                arguments=_artifact_arguments(arguments),
            )
            return (
                f"Updated Artifact {document.artifact.title} "
                f"({document.artifact.id.root}, v{document.artifact.document_version})."
            )

        return [*tools, create_project_artifact, edit_project_artifact]

    @staticmethod
    def _dataset_tools(datasets: DatasetModule, project_id: str, subject: str) -> list[BaseTool]:
        access = ProjectAccess(subject=subject)

        @tool
        async def discover_project_datasets() -> str:
            """List Dataset IDs, versions, counts, and up to three original row values.

            Samples are original row values, not the id/sourceKey/value wrappers from the load tool.
            """
            items = await datasets.list_datasets(access, project_id)
            return json.dumps(
                [
                    {
                        "id": dataset.id,
                        "name": dataset.name,
                        "recordCount": len(dataset.records),
                        "version": dataset.version,
                        "sampleRecords": [record.value for record in dataset.records[:3]],
                    }
                    for dataset in items
                ]
            )

        @tool
        async def load_project_dataset(dataset_id: str) -> str:
            """Load one Dataset and its Records shaped as {id, sourceKey, value}.

            Each Record's value is the original row object.
            """
            dataset = await datasets.load_dataset(access, project_id, dataset_id)
            return json.dumps(
                {
                    "id": dataset.id,
                    "name": dataset.name,
                    "version": dataset.version,
                    "filePath": f"/project/.datasets/{dataset.id}.json",
                    "records": [
                        {"id": record.id, "sourceKey": record.source_key, "value": record.value}
                        for record in dataset.records
                    ],
                }
            )

        @tool
        async def create_project_dataset(name: str, records: list[dict[str, Any]]) -> str:
            """Create a Dataset after approval from an array of row objects.

            Each object's fields become that Record's value. Use optional sourceKey
            for a human-readable row identifier; it is stored separately.
            """
            dataset = await datasets.create_dataset(
                access, project_id, name, _dataset_records(records)
            )
            return json.dumps(
                {
                    "created": "dataset",
                    "id": dataset.id,
                    "name": dataset.name,
                    "version": dataset.version,
                    "recordCount": len(dataset.records),
                }
            )

        @tool
        async def delete_project_dataset(dataset_id: str) -> str:
            """Delete one Dataset after user approval."""
            await datasets.delete_dataset(access, project_id, dataset_id)
            return f"Deleted Dataset {dataset_id}."

        @tool
        async def update_project_dataset(
            dataset_id: str,
            expected_version: int,
            name: str,
            records: list[dict[str, Any]],
        ) -> str:
            """Update a Dataset after approval using its loaded document version.

            Each row object's fields become that Record's value; optional sourceKey
            is stored separately.
            """
            dataset = await datasets.update_dataset(
                access,
                project_id,
                dataset_id,
                name,
                _dataset_records(records),
                expected_version=expected_version,
            )
            return json.dumps(
                {
                    "updated": "dataset",
                    "id": dataset.id,
                    "name": dataset.name,
                    "version": dataset.version,
                    "recordCount": len(dataset.records),
                }
            )

        return [
            discover_project_datasets,
            load_project_dataset,
            create_project_dataset,
            delete_project_dataset,
            update_project_dataset,
        ]

    @staticmethod
    def _workflow_tools(
        workflows: WorkflowDefinitionModule,
        workflow_runs: WorkflowRunModule | None,
        project_id: str,
        subject: str,
    ) -> list[BaseTool]:
        access = ProjectAccess(subject=subject)

        @tool
        async def list_project_workflows() -> str:
            """List saved Workflow Definitions in this Project."""
            items = await workflows.list(access, project_id)
            return json.dumps(
                [{"id": item.id, "name": item.name, "version": item.version} for item in items]
            )

        @tool
        async def load_project_workflow(workflow_id: str) -> str:
            """Read one saved Workflow Definition and its graph."""
            item = await workflows.load(access, project_id, workflow_id)
            return json.dumps(
                {
                    "id": item.id,
                    "name": item.name,
                    "version": item.version,
                    "graph": asdict(item.graph),
                }
            )

        @tool
        async def discover_project_file_sources() -> str:
            """List ordinary durable Project Files and versions usable as Workflow inputs."""
            items = await workflows.list_file_sources(access, project_id)
            return json.dumps([{"path": item.path, "version": item.version} for item in items])

        @tool
        async def validate_project_workflow(graph_json: dict[str, Any]) -> str:
            """Preflight a structured Workflow graph before approval when useful.

            Pass graph_json as an object with nodes, edges, outputs, and optional inputs. Do not
            pass a serialized JSON string. Validation does not run Python code or save the graph.
            Create and revise tools validate automatically, so this call is optional.
            """
            try:
                graph = WorkflowGraph.from_json(json.dumps(graph_json))
                await workflows.validate_graph(access, project_id, graph)
            except WorkflowValidationError as error:
                return _tool_error(
                    "workflow_validation",
                    str(error),
                    "Correct the named node, reference, schema, or binding, then create or revise "
                    "the Workflow.",
                )
            return (
                "Workflow graph is structurally valid and its references are current. "
                "Python code was not run; input value compatibility must be checked from "
                "the Function source and output schema. The Workflow has not been saved."
            )

        @tool
        async def create_project_workflow(name: str, graph_json: dict[str, Any]) -> str:
            """Create a Workflow after approval, using snake_case graph fields.

            Reuse discovered source and Function IDs and versions. Keep the graph minimal; a
            dataset-only graph can expose its records directly as an output. This tool validates
            graph_json itself. Pass it as an object, not a serialized JSON string.
            """
            try:
                graph = WorkflowGraph.from_json(json.dumps(graph_json))
                item = await workflows.create(access, project_id, name, graph)
            except WorkflowValidationError as error:
                return _tool_error(
                    "workflow_validation",
                    str(error),
                    "Correct graph_json using the named node, reference, schema, or binding, then "
                    "retry once.",
                )
            return json.dumps({"id": item.id, "name": item.name, "version": item.version})

        @tool
        async def revise_project_workflow(
            workflow_id: str,
            name: str,
            graph_json: dict[str, Any],
            expected_version: int,
        ) -> str:
            """Revise a Workflow after approval; graph_json is validated by this tool."""
            try:
                graph = WorkflowGraph.from_json(json.dumps(graph_json))
                item = await workflows.revise(
                    access,
                    project_id,
                    workflow_id,
                    name,
                    graph,
                    expected_version=expected_version,
                )
            except WorkflowValidationError as error:
                return _tool_error(
                    "workflow_validation",
                    str(error),
                    "Correct graph_json using the named node, reference, schema, or binding, then "
                    "retry once.",
                )
            return json.dumps({"id": item.id, "name": item.name, "version": item.version})

        tools: list[BaseTool] = [
            list_project_workflows,
            load_project_workflow,
            discover_project_file_sources,
            validate_project_workflow,
            create_project_workflow,
            revise_project_workflow,
        ]
        if workflow_runs is not None:

            @tool
            async def prepare_project_workflow_run(
                workflow_id: str,
                expected_version: int,
                idempotency_key: str,
                workflow_inputs: dict[str, Any] | None = None,
            ) -> str:
                """After approval, capture a Workflow Run and declared runtime inputs."""
                try:
                    run = await workflow_runs.prepare(
                        access,
                        project_id,
                        workflow_id,
                        idempotency_key,
                        expected_version=expected_version,
                        workflow_inputs=workflow_inputs or {},
                    )
                except WorkflowValidationError as error:
                    if "version changed" in str(error).lower():
                        return (
                            f"Workflow Run could not be prepared: {error} Reload the Workflow "
                            "and Function, revise the Workflow node to the current Function "
                            "revision, validate it, then prepare a fresh Run with a new "
                            "idempotency key. Do not execute an older Run."
                        )
                    return f"Workflow Run could not be prepared: {error}"
                return json.dumps(
                    {
                        "id": run.id,
                        "workflowId": run.workflow_id,
                        "status": run.status,
                        "definitionVersion": run.definition_version,
                    }
                )

            @tool
            async def load_project_workflow_run(run_id: str) -> str:
                """Inspect captured inputs, node outputs, and detailed failure diagnostics."""
                run = await workflow_runs.load(access, project_id, run_id)
                return json.dumps(
                    {
                        "id": run.id,
                        "status": run.status,
                        "snapshot": _without_image_data(run.snapshot),
                        "execution": _without_image_data(run.execution),
                    }
                )

            @tool
            async def view_image(run_id: str, output_name: str) -> list[dict[str, str]]:
                """View an image saved as a named output in a successful Workflow Run.

                Use when visual inspection would help. To show the image in chat, use the exact
                Markdown image link supplied in the text result.
                """
                try:
                    run = await workflow_runs.load(access, project_id, run_id)
                    image: WorkflowImage = await workflow_runs.load_image(
                        access, project_id, run_id, output_name
                    )
                except WorkflowNotFound:
                    return [
                        {
                            "type": "text",
                            "text": _tool_error(
                                "image_output_unavailable",
                                f"Run '{run_id}' has no viewable image output named "
                                f"'{output_name}'.",
                                "Load the Run to inspect its status and exact output names; "
                                "then call view_image with a successful Run and a named image "
                                "output.",
                            ),
                        }
                    ]
                image_path = (
                    f"/api/projects/{quote(project_id, safe='')}/workflows/"
                    f"{quote(run.workflow_id, safe='')}/runs/{quote(run.id, safe='')}/outputs/"
                    f"{quote(output_name, safe='')}/image"
                )
                markdown_alt = (
                    image.alt_text.replace("\\", "\\\\")
                    .replace("[", "\\[")
                    .replace("]", "\\]")
                    .replace("\r", " ")
                    .replace("\n", " ")
                )
                return [
                    {
                        "type": "text",
                        "text": (
                            f"Viewed image output '{output_name}' from Workflow Run {run.id}. "
                            f"To display it in chat, use exactly: ![{markdown_alt}]({image_path})"
                        ),
                    },
                    {
                        "type": "image",
                        "base64": image.data_base64,
                        "mime_type": image.mime_type,
                    },
                ]

            @tool
            async def execute_project_workflow_run(run_id: str) -> str:
                """After approval, execute or resume a recoverable Workflow Run.

                Inspect the returned execution. If it failed, read the node diagnostic or item
                diagnostics, revise the Function or graph based on that evidence, and do not
                repeat the same failing run unchanged.
                """
                try:
                    run = await workflow_runs.execute(
                        access,
                        project_id,
                        run_id,
                    )
                except WorkflowRunConflict as error:
                    try:
                        run = await workflow_runs.load(access, project_id, run_id)
                    except WorkflowNotFound:
                        return (
                            f"Workflow Run {run_id} is unavailable. Prepare a fresh Run from "
                            "the current validated Workflow."
                        )
                    return json.dumps(
                        {
                            "id": run.id,
                            "status": run.status,
                            "execution": _without_image_data(run.execution),
                            "message": str(error),
                            "nextStep": (
                                "Do not execute this Run again. If it failed, correct and "
                                "validate the Workflow, then prepare a fresh Run with a new "
                                "idempotency key. If it is running, inspect its status later."
                            ),
                        }
                    )
                return json.dumps(
                    {
                        "id": run.id,
                        "status": run.status,
                        "execution": _without_image_data(run.execution),
                    }
                )

            tools.extend(
                [
                    prepare_project_workflow_run,
                    execute_project_workflow_run,
                    load_project_workflow_run,
                    view_image,
                ]
            )
        return tools

    @staticmethod
    def _function_tools(
        functions: FunctionModule,
        project_id: str,
        subject: str,
    ) -> list[BaseTool]:
        access = ProjectAccess(subject=subject)

        @tool
        async def discover_project_functions() -> str:
            """List Python Function IDs, revisions, and declared input/output schemas."""
            definitions = await functions.list(access, project_id)
            return json.dumps(
                [
                    {
                        "id": item.id,
                        "name": item.name,
                        "revision": item.revision,
                        "inputSchema": item.input_schema,
                        "outputSchema": item.output_schema,
                    }
                    for item in definitions
                ]
            )

        @tool
        async def load_project_function(function_id: str) -> str:
            """Load a saved Python Function by UUID, including source and declared contracts."""
            try:
                item = await functions.load(access, project_id, function_id)
            except FunctionNotFound:
                return (
                    f"Function {function_id} is unavailable in this Project. "
                    "Rediscover Functions and use a current ID."
                )
            return json.dumps(
                {
                    "id": item.id,
                    "name": item.name,
                    "source": item.source,
                    "inputSchema": item.input_schema,
                    "outputSchema": item.output_schema,
                    "runtime": item.runtime,
                    "revision": item.revision,
                }
            )

        @tool
        async def create_project_function(
            name: str,
            source: str,
            input_schema: dict[str, Any],
            output_schema: dict[str, Any],
        ) -> str:
            """Create a saved Python Function after approval. It can be used by Workflow nodes.

            source defines transform(inputs, parameters). Pass input_schema and output_schema
            as JSON Schema objects. Workflow edges provide the named inputs.
            """
            try:
                item = await functions.define(
                    access,
                    project_id,
                    name,
                    source,
                    input_schema,
                    output_schema,
                )
            except (ValueError, FunctionValidationError) as error:
                return _tool_error(
                    "function_validation",
                    str(error),
                    "Correct the Python source or JSON Schema contract using this diagnostic, "
                    "then propose the corrected Function for approval.",
                )
            return json.dumps(
                {
                    "created": "python_function",
                    "id": item.id,
                    "name": item.name,
                    "revision": item.revision,
                    "inputSchema": item.input_schema,
                    "outputSchema": item.output_schema,
                }
            )

        @tool
        async def update_project_function(
            function_id: str,
            name: str,
            source: str,
            input_schema: dict[str, Any],
            output_schema: dict[str, Any],
        ) -> str:
            """Revise a saved Python Function after approval and return its current revision."""
            try:
                item = await functions.revise(
                    access,
                    project_id,
                    function_id,
                    name,
                    source,
                    input_schema,
                    output_schema,
                )
            except (ValueError, FunctionNotFound, FunctionValidationError) as error:
                return _tool_error(
                    "function_validation",
                    str(error),
                    "Correct the Python source, schema, or Function ID using this diagnostic, "
                    "then propose the corrected revision for approval.",
                )
            return json.dumps(
                {
                    "updated": "python_function",
                    "id": item.id,
                    "name": item.name,
                    "revision": item.revision,
                    "inputSchema": item.input_schema,
                    "outputSchema": item.output_schema,
                }
            )

        @tool
        async def delete_project_function(function_id: str) -> str:
            """Delete a saved Python Function after user approval."""
            try:
                await functions.delete(access, project_id, function_id)
            except FunctionNotFound:
                return f"Function {function_id} is no longer available; nothing was deleted."
            return f"Deleted Function {function_id}."

        @tool
        async def preview_project_function(
            function_id: str,
            inputs: dict[str, Any],
            parameters: dict[str, Any] | None = None,
        ) -> str:
            """Preview one Function using structured inputs and parameters; no Run is saved.

            Image output is summarized without pixel bytes. View an image from a saved Workflow
            Run when visual inspection is needed.
            """
            try:
                preview = await functions.preview(
                    access,
                    project_id,
                    function_id,
                    inputs,
                    parameters or {},
                )
            except (
                ValueError,
                FunctionNotFound,
                FunctionValidationError,
                FunctionExecutionError,
            ) as error:
                return _tool_error(
                    "function_preview_failed",
                    str(error),
                    "Use the diagnostic to fix the Function source or input shape, revise it, "
                    "and preview again.",
                )
            return json.dumps(
                {
                    "output": _without_image_data(preview.output),
                    "runtime": preview.runtime,
                    "sourceHash": preview.source_hash,
                }
            )

        return [
            discover_project_functions,
            load_project_function,
            create_project_function,
            update_project_function,
            delete_project_function,
            preview_project_function,
        ]

    async def close(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = None
        self._checkpointer = None
        self._model = None

    async def run(
        self, input_data: RunAgentInput, *, project_id: str, subject: str | None = None
    ) -> AsyncIterator[BaseEvent]:
        await self.open()
        change_notice = await self._project_change_notice(input_data, project_id, subject)
        request_agent = (
            await self._agent_for(
                project_id,
                thread_id=input_data.thread_id,
                run_id=input_data.run_id,
                subject=subject,
                change_notice=change_notice,
            )
        ).clone()
        async for event in request_agent.run(input_data):
            yield event

    async def _project_change_notice(
        self, input_data: RunAgentInput, project_id: str, subject: str | None
    ) -> str | None:
        if self._artifacts is None or subject is None:
            return None
        documents = await self._artifacts.discover(ArtifactAccess(subject=subject), project_id)
        changed = [
            document
            for document in documents
            if document.artifact.provenance.last_changed_by.thread_id != input_data.thread_id
        ]
        if not changed:
            return None
        return "; ".join(
            f"{document.artifact.title} ({document.artifact.id.root}, "
            f"v{document.artifact.document_version})"
            for document in changed
        )

    async def load_thread_state(self, thread_id: str, *, project_id: str) -> AgentThreadState:
        await self.open()
        agent = await self._agent_for(project_id)
        state = await agent.graph.aget_state({"configurable": {"thread_id": thread_id}})
        messages = state.values.get("messages", [])
        interrupts = [interrupt for task in state.tasks for interrupt in (task.interrupts or ())]
        return AgentThreadState(
            messages=tuple(langchain_messages_to_agui(messages)),
            interrupts=tuple(map_langchain_interrupts(interrupts, messages)),
        )

    async def load_scratch_file(self, thread_id: str, *, project_id: str, path: str) -> ScratchFile:
        if not _is_scratch_file_path(path):
            raise ScratchFileNotFound
        await self.open()
        agent = await self._agent_for(project_id)
        state = await agent.graph.aget_state({"configurable": {"thread_id": thread_id}})
        files = state.values.get("files")
        if not isinstance(files, dict):
            raise ScratchFileNotFound
        # ``CompositeBackend`` routes ``/scratch/...`` to ``StateBackend`` and
        # stores the route-relative key in LangGraph state (for example,
        # ``/scratch/dummy.md`` is persisted as ``/dummy.md``).
        file_data = files.get(_scratch_state_path(path))
        if not isinstance(file_data, dict):
            raise ScratchFileNotFound
        content = file_data.get("content")
        if isinstance(content, str):
            return ScratchFile(path=path, content=content)
        if isinstance(content, list) and all(isinstance(line, str) for line in content):
            return ScratchFile(path=path, content="".join(content))
        raise ScratchFileNotFound


def _is_scratch_file_path(path: str) -> bool:
    return (
        path.startswith("/scratch/")
        and len(path) <= 1032
        and "\x00" not in path
        and ".." not in path.split("/")
    )


def _scratch_state_path(path: str) -> str:
    """Translate Agent Hub's public scratch path to StateBackend's state key."""
    return path.removeprefix("/scratch")


def _dataset_records(value: list[dict[str, Any]]) -> list[DatasetRecordInput]:
    records: list[DatasetRecordInput] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("Every Dataset Record must be a JSON object.")
        record_value = dict(item)
        source_key = record_value.pop("sourceKey", None)
        if source_key is not None and not isinstance(source_key, str):
            raise ValueError("Dataset Record sourceKey values must be strings.")
        records.append(DatasetRecordInput(record_value, source_key))
    return records


def _argument_mappings(value: str) -> dict[str, str]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError("Argument mappings must be a JSON object.") from error
    if not isinstance(parsed, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in parsed.items()
    ):
        raise ValueError("Argument mappings must map argument names to JSON Pointers.")
    return parsed


def _artifact_arguments(value: dict[str, Any]) -> dict[str, object]:
    if "document" in value:
        raise ValueError("The current Artifact document is supplied by Agent Hub.")
    return value
