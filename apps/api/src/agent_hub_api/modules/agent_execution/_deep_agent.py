import json
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import AsyncExitStack
from dataclasses import asdict
from typing import Any, cast

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
from agent_hub_api.modules.plugin_gateway import (
    PluginGatewayModule,
    PluginManifest,
    PluginResultRecorder,
    PluginTool,
    PluginToolResult,
)
from agent_hub_api.modules.project_files import ProjectFilesModule
from agent_hub_api.modules.projects import ProjectAccess
from agent_hub_api.modules.transforms import (
    TransformInitiation,
    TransformModule,
    TransformValidationError,
)
from agent_hub_api.modules.workflows import (
    WorkflowDefinitionModule,
    WorkflowGraph,
    WorkflowRunModule,
    WorkflowValidationError,
)
from agent_hub_api.settings import Settings

_AGENT_SYSTEM_PROMPT = "\n\n".join(
    (
        "Use /project for durable files shared by every Thread in the selected Project "
        "and /scratch for Thread-local working files. Never claim access to the host filesystem. "
        "Link virtual files with absolute /project or /scratch paths.",
        "Project file writes, Dataset changes, Function changes, Workflow changes, and "
        "Workflow execution require approval. Start the appropriate tool action without asking "
        "for approval in chat; the approval card is shown automatically. Wait for its result.",
        "Datasets are registered Project Files under /project/.datasets. Use Dataset tools for "
        "Dataset changes; generic file writes cannot change registered Dataset files.",
        "Python Functions are authored as transform(inputs, parameters). Use Function tools to "
        "discover, inspect, create, revise, delete, or preview them. A preview is transient and "
        "runs against one record; it does not create a durable Run. Function inputs are named "
        "by input_selectors_json, a JSON object mapping each name to a JSON Pointer in that "
        'record; {"record":""} selects the whole record. input_schema_json and '
        "output_schema_json are JSON Schema objects. Use preview_project_function to check a "
        "Function before connecting it to a Workflow.",
        "Workflow is the only durable execution path for Python Functions and MCP tools. "
        "Workflow graphs define data sources, wiring, and whether a Function processes one "
        "value or a collection. Use Workflow tools to create, inspect, revise, prepare, execute, "
        "resume, and inspect Workflow Runs. Report outputs from saved Workflow Runs.",
        "Workflow Definitions are saved Project DAGs. graph_json must be an object with nodes, "
        "edges, and outputs arrays. Each node has id, kind, ref_id, and version (optionally "
        "shape and tool_name); node kinds are dataset, file, python, and mcp. Each edge has "
        "source_node, source_port, target_node, and target_port. Each output has name, node, "
        "and port. Do not use a node map, from/to edge keys, or an outputs map. Dataset sources "
        "expose ordered records. Project File nodes use kind file, the absolute /project path "
        "as ref_id, the current integer version, and expose captured text on content. Call "
        "discover_project_file_sources before composing a graph; never use /scratch paths as "
        "Workflow sources.",
        "Python Function nodes use kind python, the saved Function UUID as ref_id, its revision "
        "as version, and shape single or map. Their input ports are declared input names. The "
        "result output passes the entire value matching the Function output schema; it does not "
        "unwrap object properties. Never put a Function name in ref_id. Inspect Function source "
        "and schemas before wiring adjacent nodes. Workflow output schema properties are inside "
        "the result value, not separate "
        "output ports. MCP nodes use kind mcp, the enabled Plugin ID as ref_id, Plugin version as "
        "version, and selected tool name as tool_name.",
        "Before creating or revising a Workflow, call validate_project_workflow with the complete "
        "graph_json and fix every reported error. Validation does not save or execute the graph. "
        "Then use the approval-gated create or revise tool. Prepare a Workflow Run to capture "
        "its exact inputs, then execute the prepared Run. Completed nodes are reused on resume; "
        "an interrupted single MCP call with unknown outcome is never dispatched again "
        "automatically. Inspect the saved Run for node outputs and failures.",
    )
)


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
        transforms: TransformModule | None = None,
        workflows: WorkflowDefinitionModule | None = None,
        workflow_runs: WorkflowRunModule | None = None,
    ) -> None:
        self._settings = settings
        self._project_files = project_files
        self._plugin_gateway = plugin_gateway
        self._artifacts = artifacts
        self._datasets = datasets
        self._transforms = transforms
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
        transforms = getattr(self, "_transforms", None)
        if transforms is not None and subject is not None:
            tools.extend(self._function_tools(transforms, project_id, subject))
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
        if transforms is not None and subject is not None:
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
            plugin_id: str, tool_name: str, arguments_json: str
        ) -> str:
            """Create an Artifact with an enabled Plugin tool after user approval."""
            document = await artifacts.create_from_plugin(
                access,
                project_id,
                plugin_id=plugin_id,
                tool_name=tool_name,
                arguments=_artifact_arguments(arguments_json),
            )
            return (
                f"Created Artifact {document.artifact.title} "
                f"({document.artifact.id.root}, v{document.artifact.document_version})."
            )

        @tool
        async def edit_project_artifact(
            artifact_id: str, expected_version: int, tool_name: str, arguments_json: str
        ) -> str:
            """Apply a semantic Plugin edit to a current Artifact after user approval."""
            document = await artifacts.apply_plugin_operation(
                access,
                project_id,
                artifact_id,
                expected_version=expected_version,
                tool_name=tool_name,
                arguments=_artifact_arguments(arguments_json),
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
            """List compact Dataset summaries on demand."""
            items = await datasets.list_datasets(access, project_id)
            return json.dumps(
                [
                    {
                        "id": dataset.id,
                        "name": dataset.name,
                        "recordCount": len(dataset.records),
                        "version": dataset.version,
                    }
                    for dataset in items
                ]
            )

        @tool
        async def load_project_dataset(dataset_id: str) -> str:
            """Load one Dataset, including stable Record IDs, when details are needed."""
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
        async def create_project_dataset(name: str, records_json: str) -> str:
            """Create a Dataset from a JSON array of Records after user approval."""
            dataset = await datasets.create_dataset(
                access, project_id, name, _dataset_records(records_json)
            )
            return (
                f"Created Dataset {dataset.name} ({dataset.id}) "
                f"with {len(dataset.records)} Records."
            )

        @tool
        async def delete_project_dataset(dataset_id: str) -> str:
            """Delete one Dataset after user approval."""
            await datasets.delete_dataset(access, project_id, dataset_id)
            return f"Deleted Dataset {dataset_id}."

        @tool
        async def update_project_dataset(
            dataset_id: str, expected_version: int, name: str, records_json: str
        ) -> str:
            """Update a Dataset after approval using its loaded document version."""
            dataset = await datasets.update_dataset(
                access,
                project_id,
                dataset_id,
                name,
                _dataset_records(records_json),
                expected_version=expected_version,
            )
            return f"Updated Dataset {dataset.name} ({dataset.id}, v{dataset.version})."

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
        async def validate_project_workflow(graph_json: str) -> str:
            """Check Workflow references and wiring; this does not run Python code."""
            try:
                graph = WorkflowGraph.from_json(graph_json)
                await workflows.validate_graph(access, project_id, graph)
            except WorkflowValidationError as error:
                return f"Workflow graph is invalid: {error}"
            return (
                "Workflow graph is structurally valid and its references are current. "
                "Python code was not run; input value compatibility must be checked from "
                "the Function source and output schema. The Workflow has not been saved."
            )

        @tool
        async def create_project_workflow(name: str, graph_json: str) -> str:
            """Create a validated Workflow after approval, using snake_case graph fields."""
            try:
                graph = WorkflowGraph.from_json(graph_json)
                item = await workflows.create(access, project_id, name, graph)
            except WorkflowValidationError as error:
                return (
                    f"Workflow graph is invalid: {error} "
                    "Correct graph_json and call this tool again."
                )
            return json.dumps({"id": item.id, "name": item.name, "version": item.version})

        @tool
        async def revise_project_workflow(
            workflow_id: str, name: str, graph_json: str, expected_version: int
        ) -> str:
            """Revise a validated Workflow after approval, using snake_case graph fields."""
            try:
                graph = WorkflowGraph.from_json(graph_json)
                item = await workflows.revise(
                    access,
                    project_id,
                    workflow_id,
                    name,
                    graph,
                    expected_version=expected_version,
                )
            except WorkflowValidationError as error:
                return (
                    f"Workflow graph is invalid: {error} "
                    "Correct graph_json and call this tool again."
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
                workflow_id: str, expected_version: int, idempotency_key: str
            ) -> str:
                """After approval, capture a Workflow Run without executing its graph."""
                run = await workflow_runs.prepare(
                    access,
                    project_id,
                    workflow_id,
                    idempotency_key,
                    expected_version=expected_version,
                )
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
                """Inspect a prepared Workflow Run and its captured sources and targets."""
                run = await workflow_runs.load(access, project_id, run_id)
                return json.dumps(
                    {
                        "id": run.id,
                        "status": run.status,
                        "snapshot": run.snapshot,
                        "execution": run.execution,
                    }
                )

            @tool
            async def execute_project_workflow_run(run_id: str) -> str:
                """After approval, execute or resume a recoverable Workflow Run."""
                run = await workflow_runs.execute(
                    access,
                    project_id,
                    run_id,
                    initiation=TransformInitiation("agent", "approved"),
                )
                return json.dumps({"id": run.id, "status": run.status, "execution": run.execution})

            tools.extend(
                [
                    prepare_project_workflow_run,
                    execute_project_workflow_run,
                    load_project_workflow_run,
                ]
            )
        return tools

    @staticmethod
    def _function_tools(
        functions: TransformModule,
        project_id: str,
        subject: str,
    ) -> list[BaseTool]:
        access = ProjectAccess(subject=subject)

        def object_json(raw: str) -> dict[str, Any]:
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("Expected a JSON object")
            return value

        def selector_json(raw: str) -> dict[str, str]:
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as error:
                raise ValueError("input_selectors_json must be a JSON object") from error
            if not isinstance(value, dict) or any(
                not isinstance(key, str) or not isinstance(pointer, str)
                for key, pointer in value.items()
            ):
                raise ValueError("input_selectors_json must be a JSON object of names to pointers")
            return cast(dict[str, str], value)

        @tool
        async def discover_project_functions() -> str:
            """List saved Python Functions with IDs and revisions."""
            definitions = await functions.list(access, project_id)
            return json.dumps(
                [
                    {"id": item.id, "name": item.name, "revision": item.revision}
                    for item in definitions
                ]
            )

        @tool
        async def load_project_function(function_id: str) -> str:
            """Load a saved Python Function by UUID, including source and declared contracts."""
            item = await functions.load(access, project_id, function_id)
            return json.dumps(
                {
                    "id": item.id,
                    "name": item.name,
                    "source": item.source,
                    "inputSelectors": item.input_selectors,
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
            input_selectors_json: str,
            input_schema_json: str,
            output_schema_json: str,
        ) -> str:
            """Create a saved Python Function after approval. It can be used by Workflow nodes.

            source is Python defining transform(inputs, parameters). input_selectors_json
            maps each declared input to a JSON Pointer in a single input record; an empty
            pointer selects the whole record. input_schema_json and output_schema_json are
            JSON Schema objects.
            """
            try:
                item = await functions.define(
                    access,
                    project_id,
                    name,
                    source,
                    selector_json(input_selectors_json),
                    object_json(output_schema_json),
                    input_schema=object_json(input_schema_json),
                )
            except (ValueError, TransformValidationError) as error:
                return (
                    f"Function was not created: {error}. Propose a corrected change for approval."
                )
            return json.dumps(
                {
                    "created": "python_function",
                    "id": item.id,
                    "name": item.name,
                    "revision": item.revision,
                }
            )

        @tool
        async def update_project_function(
            function_id: str,
            name: str,
            source: str,
            input_selectors_json: str,
            input_schema_json: str,
            output_schema_json: str,
        ) -> str:
            """Revise a saved Python Function after approval."""
            try:
                item = await functions.revise(
                    access,
                    project_id,
                    function_id,
                    name,
                    source,
                    selector_json(input_selectors_json),
                    object_json(output_schema_json),
                    input_schema=object_json(input_schema_json),
                )
            except (ValueError, TransformValidationError) as error:
                return (
                    f"Function was not updated: {error}. Propose a corrected change for approval."
                )
            return f"Updated Function {item.name} ({item.id})."

        @tool
        async def delete_project_function(function_id: str) -> str:
            """Delete a saved Python Function after user approval."""
            await functions.delete(access, project_id, function_id)
            return f"Deleted Function {function_id}."

        @tool
        async def preview_project_function(
            function_id: str,
            record_json: str,
            parameters_json: str = "{}",
        ) -> str:
            """Run one transient preview against a single record; this does not save a Run."""
            try:
                preview = await functions.preview(
                    access,
                    project_id,
                    function_id,
                    object_json(record_json),
                    object_json(parameters_json),
                )
            except (ValueError, TransformValidationError) as error:
                return f"Function preview failed: {error}"
            return json.dumps(
                {
                    "output": preview.output,
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


def _dataset_records(value: str) -> list[DatasetRecordInput]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError("Dataset Records must be a JSON array.") from error
    if not isinstance(parsed, list):
        raise ValueError("Dataset Records must be a JSON array.")
    records: list[DatasetRecordInput] = []
    for item in parsed:
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


def _artifact_arguments(value: str) -> dict[str, object]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError("Plugin arguments must be a JSON object.") from error
    if not isinstance(parsed, dict):
        raise ValueError("Plugin arguments must be a JSON object.")
    if "document" in parsed:
        raise ValueError("The current Artifact document is supplied by Agent Hub.")
    return parsed
