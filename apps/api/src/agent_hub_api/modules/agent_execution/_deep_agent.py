import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import AsyncExitStack
from dataclasses import asdict
from typing import Annotated, Any, cast

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
from langchain_core.tools import BaseTool, InjectedToolCallId, tool
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
from agent_hub_api.modules.batch_execution import (
    BatchExecutionModule,
    BatchInitiation,
    BatchRun,
    BatchRunStatus,
)
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
from agent_hub_api.modules.transform_inputs import (
    ArtifactSelection,
    ResultSetSelection,
    TransformDatasetMode,
    TransformInputModule,
)
from agent_hub_api.modules.transforms import (
    OutputSelection,
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
        "and /scratch for Thread-local working files.",
        "Project file writes require user approval before they are persisted. When the "
        "requested Project file name and content are clear, the write can begin. Start "
        "the Project file write without asking for approval in chat first. The approval "
        "card is shown automatically after the tool call. Do not tell the user that they "
        "need to separately grant approval or ask whether you may proceed; wait for the "
        "tool result after their decision.",
        "Creating or changing a Project Artifact also requires user approval. When the "
        "requested Artifact title or status is clear, call the Artifact tool without asking "
        "for approval in chat first; the approval card is shown automatically.",
        "Datasets are registered, typed Project Files under /project/.datasets. "
        "You may read them through Project files or Project Dataset tools. "
        "Use the Project Dataset tools for Dataset mutations; generic file writes cannot "
        "change registered Dataset files. Batch Definitions remain separate Project records. "
        "Dataset and Batch Definition mutations use the approval card automatically. "
        "A queued or running Batch Run has pending results; null output during that state "
        "does not mean its Transform failed. Report outputs only after terminal status.",
        "For a Dataset whose Records already match a permitted repeat-safe MCP tool's "
        "input schema, review plan_project_mcp_map and then start_project_mcp_map. "
        "This explicitly maps the tool over the Records without creating a Batch "
        "Definition. Python Transform code cannot call MCP tools; put MCP calls in "
        "their own operation step.",
        "For one MCP invocation, review plan_project_mcp_call with the exact JSON "
        "arguments, then use start_project_mcp_call. The approval card appears "
        "automatically. Inspect the retained Run result before reporting its output.",
        "To apply a one-input Python Function independently to every Dataset Record, "
        "review plan_project_python_map, then use start_project_python_map after "
        "the automatic approval card. This Map passes each whole Record value to "
        "the Function's named input; Definition JSON pointers are not applied.",
        "Transform Definitions and Runs are durable Project records. Use the Project "
        "Transform tools to inspect or change them; Definition changes, Run starts, and "
        "output saves use the approval card automatically. Transform source is Python "
        "executed by Pyodide and must define transform(inputs, parameters). The "
        "input_selectors_json argument is a JSON object mapping input names to JSON "
        'pointers: {"record":""} selects the whole record and {"value":"/value"} '
        "selects one field. Each input name becomes a key in inputs. "
        "output_schema_json is a JSON Schema object. To run a Transform on a Dataset, "
        "review it with plan_project_dataset_transform_run, then use the single "
        "start_project_dataset_transform_run action with mode dataset (one invocation "
        "over ordered Records, suitable for filtering, sorting, or aggregation) or "
        "perRecord (one invocation per Record with a Batch Result Set). Do not claim "
        "Transforms are limited to one Record at a time. For Dataset-wide "
        'execution, {"values":"/selection/values"} passes the ordered Record values '
        'to inputs["values"]. For perRecord, {"record":""} passes each full '
        'Record value to inputs["record"]. Both modes accept parameters.',
        "Never claim access to the host filesystem. When referring to a virtual file in "
        "a response, link it as Markdown using its absolute /project or /scratch path.",
        "Workflow Definitions are saved Project DAGs. Use list_project_workflows and "
        "load_project_workflow to inspect them, then create_project_workflow or "
        "revise_project_workflow for a user-requested change. graph_json must be an object "
        "with nodes, edges, and outputs arrays. Each node is an object with id, kind, "
        "ref_id, and version (optionally shape and tool_name); node kinds are dataset, file, "
        "python, and mcp. Each edge is an object with source_node, source_port, target_node, "
        "and target_port. Each output is an object with name, node, and port. Do not use "
        "a node map, from/to edge keys, or an outputs map. Dataset source nodes expose "
        "ordered records. Project File nodes use kind file, the absolute /project path as "
        "ref_id, the current integer version, and expose captured text on the content output. "
        "Python Function nodes use kind python, the saved Function ID as ref_id, its revision "
        "as the integer version, and shape single or map; their input ports are the Function's "
        "declared input names and their output port is result. MCP nodes use kind mcp, the "
        "enabled Plugin ID as ref_id, the Plugin version as version, and the selected tool's "
        "name as tool_name. Create or discover these targets before composing the graph. "
        "Creating or revising a "
        "Workflow invokes the approval "
        "card automatically. Use prepare_project_workflow_run when the user wants "
        "to capture exact inputs for a Run, then execute_project_workflow_run to run "
        "a prepared or recoverable interrupted graph. Both actions require an approval card. "
        "Python Functions run through "
        "the host Python runner, and MCP nodes run through the Project-enabled Plugin "
        "Gateway. Completed nodes are reused on resume; an interrupted single MCP call "
        "with unknown outcome is never dispatched again automatically. Inspect the saved "
        "Run to report node outputs and failures.",
    )
)

_AGENT_BATCH_WAIT_SECONDS = 30.0


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
        batches: BatchExecutionModule | None = None,
        transforms: TransformModule | None = None,
        transform_inputs: TransformInputModule | None = None,
        workflows: WorkflowDefinitionModule | None = None,
        workflow_runs: WorkflowRunModule | None = None,
    ) -> None:
        self._settings = settings
        self._project_files = project_files
        self._plugin_gateway = plugin_gateway
        self._artifacts = artifacts
        self._datasets = datasets
        self._batches = batches
        self._transforms = transforms
        self._transform_inputs = transform_inputs
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
        batches = getattr(self, "_batches", None)
        if batches is not None and subject is not None and thread_id and run_id:
            tools.extend(self._batch_tools(batches, project_id, subject, thread_id, run_id))
        transforms = getattr(self, "_transforms", None)
        if transforms is not None and subject is not None:
            tools.extend(self._transform_tools(transforms, project_id, subject, thread_id, run_id))
        transform_inputs = getattr(self, "_transform_inputs", None)
        if transform_inputs is not None and subject is not None:
            tools.extend(
                self._transform_input_tools(
                    transform_inputs, project_id, subject, thread_id, run_id
                )
            )
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
                    "create_project_batch_definition": {
                        "allowed_decisions": ["approve", "reject"],
                        "description": "Create the proposed Batch Definition?",
                    },
                    "delete_project_batch_definition": {
                        "allowed_decisions": ["approve", "reject"],
                        "description": "Delete the proposed Batch Definition?",
                    },
                    "update_project_batch_definition": {
                        "allowed_decisions": ["approve", "reject"],
                        "description": "Update the proposed Batch Definition?",
                    },
                }
            )
        if batches is not None and subject is not None and thread_id and run_id:
            interrupt_on["start_project_batch_run"] = {
                "allowed_decisions": ["approve", "reject"],
                "description": "Start the proposed Batch Run?",
            }
            interrupt_on["start_project_mcp_map"] = {
                "allowed_decisions": ["approve", "reject"],
                "description": "Map this MCP tool over the reviewed Dataset Records?",
            }
            interrupt_on["start_project_mcp_call"] = {
                "allowed_decisions": ["approve", "reject"],
                "description": "Run this MCP tool with the reviewed arguments?",
            }
            interrupt_on["start_project_python_map"] = {
                "allowed_decisions": ["approve", "reject"],
                "description": "Map this Python Function over the reviewed Dataset Records?",
            }
        if transforms is not None and subject is not None:
            interrupt_on.update(
                {
                    "create_project_transform": {
                        "allowed_decisions": ["approve", "reject"],
                        "description": "Create the proposed Transform Definition?",
                    },
                    "update_project_transform": {
                        "allowed_decisions": ["approve", "reject"],
                        "description": "Update the proposed Transform Definition?",
                    },
                    "delete_project_transform": {
                        "allowed_decisions": ["approve", "reject"],
                        "description": "Delete the proposed Transform Definition?",
                    },
                    "start_project_transform_run": {
                        "allowed_decisions": ["approve", "reject"],
                        "description": "Start the proposed Transform Run?",
                    },
                    "start_project_function_call": {
                        "allowed_decisions": ["approve", "reject"],
                        "description": "Run this Python Function with the reviewed named inputs?",
                    },
                    "save_project_transform_run_as_dataset": {
                        "allowed_decisions": ["approve", "reject"],
                        "description": "Save this Transform Run output as a Dataset?",
                    },
                }
            )
            if thread_id is not None and run_id is not None:
                interrupt_on["save_project_transform_run_as_artifact"] = {
                    "allowed_decisions": ["approve", "reject"],
                    "description": "Save this Transform Run output as an Artifact?",
                }
            interrupt_on["start_project_transform_output_selection_run"] = {
                "allowed_decisions": ["approve", "reject"],
                "description": "Run the reviewed Transform output selection?",
            }
        if transform_inputs is not None and subject is not None:
            interrupt_on["start_project_dataset_transform_run"] = {
                "allowed_decisions": ["approve", "reject"],
                "description": "Run the reviewed Transform on this Dataset?",
            }
            interrupt_on["start_project_transform_result_set_selection_run"] = {
                "allowed_decisions": ["approve", "reject"],
                "description": "Run the reviewed Result Set selection through this Transform?",
            }
            interrupt_on["start_project_transform_artifact_selection_run"] = {
                "allowed_decisions": ["approve", "reject"],
                "description": "Run the reviewed MCP output selection through this Transform?",
            }
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
            """List compact Dataset and Batch Definition summaries on demand."""
            available = {dataset.id for dataset in await datasets.list_datasets(access, project_id)}
            definitions = await datasets.list_definitions(access, project_id)
            return json.dumps(
                {
                    "datasets": [
                        {
                            "id": dataset.id,
                            "name": dataset.name,
                            "recordCount": len(dataset.records),
                            "version": dataset.version,
                        }
                        for dataset in await datasets.list_datasets(access, project_id)
                    ],
                    "batchDefinitions": [
                        {
                            "id": definition.id,
                            "name": definition.name,
                            "datasetId": definition.dataset_id,
                            "datasetAvailable": definition.dataset_id in available,
                            "tool": f"{definition.plugin_id}.{definition.tool_name}",
                        }
                        for definition in definitions
                    ],
                }
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
        async def load_project_batch_definition(definition_id: str) -> str:
            """Load one Batch Definition when its Dataset mapping or target tool is needed."""
            definition = await datasets.load_definition(access, project_id, definition_id)
            return json.dumps(
                {
                    "id": definition.id,
                    "name": definition.name,
                    "datasetId": definition.dataset_id,
                    "pluginId": definition.plugin_id,
                    "toolName": definition.tool_name,
                    "transformDefinitionId": definition.transform_definition_id,
                    "argumentMappings": definition.argument_mappings,
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
            """Delete one Dataset after user approval; dependent Definitions become unavailable."""
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

        @tool
        async def create_project_batch_definition(
            dataset_id: str,
            name: str,
            plugin_id: str,
            tool_name: str,
            argument_mappings_json: str,
        ) -> str:
            """Create a schema-validated Batch Definition after user approval."""
            try:
                mappings = json.loads(argument_mappings_json)
            except json.JSONDecodeError as error:
                raise ValueError("Argument mappings must be a JSON object.") from error
            if not isinstance(mappings, dict) or not all(
                isinstance(key, str) and isinstance(value, str) for key, value in mappings.items()
            ):
                raise ValueError("Argument mappings must map argument names to JSON Pointers.")
            definition = await datasets.create_definition(
                access,
                project_id,
                dataset_id,
                name,
                plugin_id,
                tool_name,
                mappings,
            )
            return f"Created Batch Definition {definition.name} ({definition.id})."

        @tool
        async def delete_project_batch_definition(definition_id: str) -> str:
            """Delete one Batch Definition after user approval."""
            await datasets.delete_definition(access, project_id, definition_id)
            return f"Deleted Batch Definition {definition_id}."

        @tool
        async def update_project_batch_definition(
            definition_id: str,
            dataset_id: str,
            name: str,
            plugin_id: str,
            tool_name: str,
            argument_mappings_json: str,
        ) -> str:
            """Update a schema-validated Batch Definition after user approval."""
            definition = await datasets.update_definition(
                access,
                project_id,
                definition_id,
                dataset_id,
                name,
                plugin_id,
                tool_name,
                _argument_mappings(argument_mappings_json),
            )
            return f"Updated Batch Definition {definition.name} ({definition.id})."

        return [
            discover_project_datasets,
            load_project_dataset,
            load_project_batch_definition,
            create_project_dataset,
            delete_project_dataset,
            update_project_dataset,
            create_project_batch_definition,
            delete_project_batch_definition,
            update_project_batch_definition,
        ]

    @staticmethod
    def _batch_tools(
        batches: BatchExecutionModule,
        project_id: str,
        subject: str,
        thread_id: str,
        agent_run_id: str,
    ) -> list[BaseTool]:
        access = ProjectAccess(subject=subject)

        @tool
        async def plan_project_python_map(
            definition_id: str, dataset_id: str, parameters_json: str = "{}"
        ) -> str:
            """Review one Python Function call per ordered Dataset Record.

            The Function must declare exactly one named item input. The plan shows
            every captured Record, target revision, invocation count, and output kind.
            """
            parameters = json.loads(parameters_json)
            if not isinstance(parameters, dict):
                raise ValueError("parameters_json must be a JSON object")
            plan = await batches.plan_python_dataset_map(
                access, project_id, definition_id, dataset_id, parameters
            )
            return json.dumps(plan.snapshot())

        @tool
        async def start_project_python_map(
            definition_id: str,
            dataset_id: str,
            expected_dataset_version: int,
            expected_definition_revision: int,
            tool_call_id: Annotated[str, InjectedToolCallId],
            parameters_json: str = "{}",
        ) -> str:
            """Start the reviewed Python Function Map after user approval."""
            parameters = json.loads(parameters_json)
            if not isinstance(parameters, dict):
                raise ValueError("parameters_json must be a JSON object")
            key = hashlib.sha256(
                f"agent-python-map:{thread_id}:{tool_call_id}".encode()
            ).hexdigest()
            run = await batches.submit_python_dataset_map(
                access,
                project_id,
                definition_id,
                dataset_id,
                expected_dataset_version,
                expected_definition_revision,
                key,
                initiation=BatchInitiation(
                    kind="agentRun",
                    approval="approved",
                    thread_id=thread_id,
                    agent_run_id=agent_run_id,
                    tool_call_id=tool_call_id,
                ),
                parameters=parameters,
            )
            task = await batches.enqueue(access, project_id, run.id)
            try:
                completed = await asyncio.wait_for(
                    asyncio.shield(task), timeout=_AGENT_BATCH_WAIT_SECONDS
                )
            except TimeoutError:
                return (
                    f"Python Map {run.id} is still running. Outputs are pending; "
                    "inspect the Result Set later."
                )
            succeeded = sum(record.structured_output is not None for record in completed.records)
            failed = sum(record.error is not None for record in completed.records)
            return (
                f"Python Map {run.id} {completed.status}: {succeeded} of "
                f"{len(completed.records)} Records produced outputs; {failed} failed."
            )

        @tool
        async def plan_project_mcp_call(plugin_id: str, tool_name: str, arguments_json: str) -> str:
            """Review one permitted MCP call and its exact JSON arguments."""
            arguments = json.loads(arguments_json)
            if not isinstance(arguments, dict):
                raise ValueError("arguments_json must be a JSON object")
            plan = await batches.plan_mcp_call(access, project_id, plugin_id, tool_name, arguments)
            return json.dumps(plan.snapshot())

        @tool
        async def start_project_mcp_call(
            plugin_id: str,
            tool_name: str,
            arguments_json: str,
            expected_plugin_version: str,
            tool_call_id: Annotated[str, InjectedToolCallId],
        ) -> str:
            """Start the reviewed durable MCP call after user approval."""
            arguments = json.loads(arguments_json)
            if not isinstance(arguments, dict):
                raise ValueError("arguments_json must be a JSON object")
            key = hashlib.sha256(f"agent-mcp-call:{thread_id}:{tool_call_id}".encode()).hexdigest()
            run = await batches.submit_mcp_call(
                access,
                project_id,
                plugin_id,
                tool_name,
                arguments,
                expected_plugin_version,
                key,
                initiation=BatchInitiation(
                    kind="agentRun",
                    approval="approved",
                    thread_id=thread_id,
                    agent_run_id=agent_run_id,
                    tool_call_id=tool_call_id,
                ),
            )
            task = await batches.enqueue(access, project_id, run.id)
            try:
                completed = await asyncio.wait_for(
                    asyncio.shield(task), timeout=_AGENT_BATCH_WAIT_SECONDS
                )
            except TimeoutError:
                return f"MCP Call {run.id} is still running; inspect its result later."
            result = completed.records[0]
            outcome = (
                json.dumps(result.structured_output)
                if result.structured_output is not None
                else result.error
            )
            return f"MCP Call {run.id} {completed.status}: {outcome}"

        @tool
        async def plan_project_mcp_map(dataset_id: str, plugin_id: str, tool_name: str) -> str:
            """Review a direct MCP Map over tool-ready Dataset Records.

            Every Record must satisfy the permitted repeat-safe tool's input schema.
            Returns exact ordered inputs, Dataset version, target, and invocation count.
            """
            plan = await batches.plan_mcp_dataset(
                access, project_id, plugin_id, tool_name, dataset_id
            )
            return json.dumps(plan.snapshot())

        @tool
        async def start_project_mcp_map(
            dataset_id: str,
            plugin_id: str,
            tool_name: str,
            expected_dataset_version: int,
            expected_plugin_version: str,
            tool_call_id: Annotated[str, InjectedToolCallId],
        ) -> str:
            """Start the reviewed MCP Map after approval using its Dataset and Plugin versions."""
            key = hashlib.sha256(f"agent-mcp-map:{thread_id}:{tool_call_id}".encode()).hexdigest()
            run = await batches.submit_mcp_dataset(
                access,
                project_id,
                plugin_id,
                tool_name,
                dataset_id,
                expected_dataset_version,
                expected_plugin_version,
                key,
                initiation=BatchInitiation(
                    kind="agentRun",
                    approval="approved",
                    thread_id=thread_id,
                    agent_run_id=agent_run_id,
                    tool_call_id=tool_call_id,
                ),
            )
            task = await batches.enqueue(access, project_id, run.id)
            try:
                completed = await asyncio.wait_for(
                    asyncio.shield(task), timeout=_AGENT_BATCH_WAIT_SECONDS
                )
            except TimeoutError:
                return (
                    f"Batch Run {run.id} is still running. Outputs are pending; "
                    "check its status before interpreting Result Records."
                )
            succeeded = sum(record.structured_output is not None for record in completed.records)
            failed = sum(record.error is not None for record in completed.records)
            return (
                f"Batch Run {run.id} {completed.status}: {succeeded} of "
                f"{len(completed.records)} records produced outputs; {failed} failed."
            )

        @tool
        async def start_project_batch_run(
            definition_id: str,
            tool_call_id: Annotated[str, InjectedToolCallId],
            record_id: str | None = None,
        ) -> str:
            """Start one or all Records after approval; wait briefly for final results.

            If the Run remains active, report that outputs are pending. Inspect results
            only after the Run reaches succeeded, failed, or partial status.
            """
            key = hashlib.sha256(f"agent-batch:{thread_id}:{tool_call_id}".encode()).hexdigest()
            initiation = BatchInitiation(
                kind="agentRun",
                approval="approved",
                thread_id=thread_id,
                agent_run_id=agent_run_id,
                tool_call_id=tool_call_id,
            )
            if record_id is None:
                run = await batches.submit_all(
                    access, project_id, definition_id, key, initiation=initiation
                )
            else:
                run = await batches.submit_one(
                    access,
                    project_id,
                    definition_id,
                    record_id,
                    key,
                    initiation=initiation,
                )
            task = await batches.enqueue(access, project_id, run.id)
            try:
                completed = await asyncio.wait_for(
                    asyncio.shield(task), timeout=_AGENT_BATCH_WAIT_SECONDS
                )
            except TimeoutError:
                return (
                    f"Batch Run {run.id} is still running. Outputs are pending; "
                    "check its status before interpreting Result Records."
                )
            succeeded = sum(record.structured_output is not None for record in completed.records)
            failed = sum(record.error is not None for record in completed.records)
            return (
                f"Batch Run {run.id} {completed.status}: {succeeded} of "
                f"{len(completed.records)} records produced outputs; {failed} failed."
            )

        @tool
        async def list_project_batch_runs(
            definition_id: str | None = None,
            limit: int = 10,
            offset: int = 0,
        ) -> str:
            """List compact durable Batch Run summaries for the selected Project."""
            if not 1 <= limit <= 20:
                raise ValueError("Choose a Batch Run page size from 1 to 20.")
            page = await batches.list(
                access,
                project_id,
                definition_id=definition_id,
                limit=limit,
                offset=offset,
            )
            return json.dumps(
                {
                    "items": [
                        {
                            "id": run.id,
                            "definitionId": run.definition_id,
                            "status": run.status,
                            "recordCount": len(run.records),
                            "succeededCount": sum(
                                record.structured_output is not None for record in run.records
                            ),
                            "failedCount": sum(record.error is not None for record in run.records),
                            "archived": run.archived_at is not None,
                        }
                        for run in page.items
                    ],
                    "nextOffset": page.next_offset,
                }
            )

        @tool
        async def inspect_project_batch_results(
            run_id: str,
            limit: int = 20,
            offset: int = 0,
            filter_path: str | None = None,
            equals: str | int | float | bool | None = None,
            minimum: float | None = None,
            maximum: float | None = None,
            sort_path: str | None = None,
            descending: bool = False,
            aggregate_path: str | None = None,
        ) -> str:
            """Read a completed Result Set page with optional scalar query and summary.

            Queued or running records have pending outputs, not failed outputs.
            """
            if not 1 <= limit <= 20:
                raise ValueError("Choose a Result Set page size from 1 to 20.")
            run = await batches.load(access, project_id, run_id)
            if run.status in {BatchRunStatus.queued, BatchRunStatus.running}:
                return json.dumps({"runId": run_id, "status": run.status, "resultsReady": False})
            page = await batches.inspect_results(
                access,
                project_id,
                run_id,
                limit=limit,
                offset=offset,
                filter_path=filter_path,
                equals=equals,
                minimum=minimum,
                maximum=maximum,
                sort_path=sort_path,
                descending=descending,
                aggregate_path=aggregate_path,
            )
            return json.dumps(
                {
                    "items": [
                        {
                            "datasetRecordId": record.dataset_record_id,
                            "input": record.input,
                            "structuredOutput": record.structured_output,
                            "error": record.error,
                        }
                        for record in page.items
                    ],
                    "nextOffset": page.next_offset,
                    "summary": {
                        "totalCount": page.summary.total_count,
                        "succeededCount": page.summary.succeeded_count,
                        "failedCount": page.summary.failed_count,
                        "numericCount": page.summary.numeric_count,
                        "numericSum": page.summary.numeric_sum,
                        "numericMin": page.summary.numeric_min,
                        "numericMax": page.summary.numeric_max,
                        "numericAverage": page.summary.numeric_average,
                    },
                }
            )

        return [
            start_project_batch_run,
            list_project_batch_runs,
            inspect_project_batch_results,
            plan_project_python_map,
            start_project_python_map,
            plan_project_mcp_call,
            start_project_mcp_call,
            plan_project_mcp_map,
            start_project_mcp_map,
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
        async def create_project_workflow(name: str, graph_json: str) -> str:
            """Create a Workflow after approval; graph_json uses snake_case graph fields."""
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
            """Revise a Workflow after approval; graph_json uses snake_case graph fields."""
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
    def _transform_tools(
        transforms: TransformModule,
        project_id: str,
        subject: str,
        thread_id: str | None = None,
        agent_run_id: str | None = None,
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

        def output_selection(raw: str) -> OutputSelection:
            value = object_json(raw)
            try:
                return OutputSelection(**value)
            except TypeError as error:
                raise ValueError("Transform output selection fields are invalid.") from error

        @tool
        async def discover_project_transforms() -> str:
            """List the saved Transform Definitions in this Project."""
            definitions = await transforms.list(access, project_id)
            return json.dumps(
                [
                    {"id": item.id, "name": item.name, "revision": item.revision}
                    for item in definitions
                ]
            )

        @tool
        async def load_project_transform(definition_id: str) -> str:
            """Load one Transform Definition, including source and declared contracts."""
            item = await transforms.load(access, project_id, definition_id)
            return json.dumps(
                {
                    "id": item.id,
                    "name": item.name,
                    "source": item.source,
                    "inputSelectors": item.input_selectors,
                    "outputSchema": item.output_schema,
                    "runtime": item.runtime,
                    "revision": item.revision,
                }
            )

        @tool
        async def list_project_transform_runs(definition_id: str | None = None) -> str:
            """List recent durable Transform Runs and their outcomes."""
            page = await transforms.list_runs(access, project_id, definition_id)
            return json.dumps(
                [
                    {
                        "id": run.id,
                        "definitionId": run.definition_id,
                        "status": run.status,
                        "createdAt": run.created_at.isoformat(),
                    }
                    for run in page.items
                ]
            )

        @tool
        async def load_project_transform_run(run_id: str) -> str:
            """Inspect a Transform Run's captured inputs, output, and provenance."""
            run = await transforms.load_run(access, project_id, run_id)
            return json.dumps(
                {
                    "id": run.id,
                    "status": run.status,
                    "inputs": run.inputs,
                    "parameters": run.parameters,
                    "output": run.output,
                    "error": run.error,
                    "runtime": run.runtime,
                    "packageHash": run.package_hash,
                    "sourceHash": run.source_hash,
                    "selection": run.definition_snapshot.get("selection"),
                }
            )

        @tool
        async def create_project_transform(
            name: str, source: str, input_selectors_json: str, output_schema_json: str
        ) -> str:
            """Create a Project Transform Definition after approval.

            source is Python defining transform(inputs, parameters). input_selectors_json
            is a JSON object such as {"record":""} for the whole input record or
            {"value":"/value"} for one field. output_schema_json is a JSON Schema object.
            """
            try:
                item = await transforms.define(
                    access,
                    project_id,
                    name,
                    source,
                    selector_json(input_selectors_json),
                    object_json(output_schema_json),
                )
            except (ValueError, TransformValidationError) as error:
                return (
                    f"Transform Definition was not created: {error}. "
                    "Propose a corrected change for approval."
                )
            return f"Created Transform Definition {item.name} ({item.id})."

        @tool
        async def update_project_transform(
            definition_id: str,
            name: str,
            source: str,
            input_selectors_json: str,
            output_schema_json: str,
        ) -> str:
            """Revise a Project Transform Definition after approval.

            source is Python defining transform(inputs, parameters). input_selectors_json
            maps names to JSON pointers; an empty pointer selects the whole record.
            """
            try:
                item = await transforms.revise(
                    access,
                    project_id,
                    definition_id,
                    name,
                    source,
                    selector_json(input_selectors_json),
                    object_json(output_schema_json),
                )
            except (ValueError, TransformValidationError) as error:
                return (
                    f"Transform Definition was not updated: {error}. "
                    "Propose a corrected change for approval."
                )
            return f"Updated Transform Definition {item.name} ({item.id})."

        @tool
        async def delete_project_transform(definition_id: str) -> str:
            """Delete a Transform Definition after user approval; retained Runs remain."""
            await transforms.delete(access, project_id, definition_id)
            return f"Deleted Transform Definition {definition_id}."

        @tool
        async def start_project_transform_run(
            definition_id: str, record_json: str, parameters_json: str = "{}"
        ) -> str:
            """Start a durable Transform Run after user approval."""
            run = await transforms.start_run(
                access,
                project_id,
                definition_id,
                object_json(record_json),
                object_json(parameters_json),
                initiation=TransformInitiation(
                    kind="agentRun",
                    approval="approved",
                    thread_id=thread_id,
                    agent_run_id=agent_run_id,
                ),
            )
            return f"Transform Run {run.id} {run.status}."

        @tool
        async def plan_project_function_call(
            definition_id: str, inputs_json: str, parameters_json: str = "{}"
        ) -> str:
            """Review one Python Function call with named JSON inputs and parameters.

            The input names must match the Transform Definition's declared names.
            This call does not apply its JSON Pointer selectors.
            """
            plan = await transforms.plan_function_call(
                access,
                project_id,
                definition_id,
                object_json(inputs_json),
                object_json(parameters_json),
            )
            return json.dumps(plan.snapshot())

        @tool
        async def start_project_function_call(
            definition_id: str,
            inputs_json: str,
            expected_revision: int,
            parameters_json: str = "{}",
        ) -> str:
            """Start one durable Python Function Run after reviewing inputs and approval."""
            run = await transforms.start_function_call(
                access,
                project_id,
                definition_id,
                object_json(inputs_json),
                object_json(parameters_json),
                expected_revision=expected_revision,
                initiation=TransformInitiation(
                    kind="agentRun",
                    approval="approved",
                    thread_id=thread_id,
                    agent_run_id=agent_run_id,
                ),
            )
            return f"Transform Run {run.id} {run.status}."

        @tool
        async def plan_project_transform_output_selection(
            definition_id: str, selection_json: str, parameters_json: str = "{}"
        ) -> str:
            """Review a bounded selection from a completed Transform Run output."""
            plan = await transforms.plan_output_selection(
                access,
                project_id,
                definition_id,
                output_selection(selection_json),
                object_json(parameters_json),
            )
            return json.dumps(plan.snapshot())

        @tool
        async def start_project_transform_output_selection_run(
            definition_id: str, selection_json: str, parameters_json: str = "{}"
        ) -> str:
            """Run a reviewed Transform output selection after user approval."""
            run = await transforms.start_output_selected_run(
                access,
                project_id,
                definition_id,
                output_selection(selection_json),
                object_json(parameters_json),
                initiation=TransformInitiation(
                    kind="agentRun",
                    approval="approved",
                    thread_id=thread_id,
                    agent_run_id=agent_run_id,
                ),
            )
            return f"Transform Run {run.id} {run.status}."

        @tool
        async def save_project_transform_run_as_dataset(run_id: str, name: str) -> str:
            """Save a successful Transform Run output as a Dataset after user approval."""
            dataset = await transforms.save_run_as_dataset(access, project_id, run_id, name)
            return f"Saved Dataset {dataset.name} ({dataset.id}) from Transform Run {run_id}."

        tools = [
            discover_project_transforms,
            load_project_transform,
            list_project_transform_runs,
            load_project_transform_run,
            create_project_transform,
            update_project_transform,
            delete_project_transform,
            start_project_transform_run,
            plan_project_function_call,
            start_project_function_call,
            plan_project_transform_output_selection,
            start_project_transform_output_selection_run,
            save_project_transform_run_as_dataset,
        ]
        if thread_id is not None and agent_run_id is not None:

            @tool
            async def save_project_transform_run_as_artifact(run_id: str, title: str) -> str:
                """Save a successful Transform Run output as an Artifact after approval."""
                document = await transforms.save_run_as_artifact(
                    ArtifactMutationAccess(
                        subject=subject, thread_id=thread_id, run_id=agent_run_id
                    ),
                    project_id,
                    run_id,
                    title,
                )
                return (
                    f"Saved Artifact {document.artifact.title} "
                    f"({document.artifact.id.root}) from Transform Run {run_id}."
                )

            tools.append(save_project_transform_run_as_artifact)
        return tools

    @staticmethod
    def _transform_input_tools(
        inputs: TransformInputModule,
        project_id: str,
        subject: str,
        thread_id: str | None = None,
        agent_run_id: str | None = None,
    ) -> list[BaseTool]:
        access = ProjectAccess(subject=subject)

        def parse_selection(raw: str) -> ResultSetSelection:
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("Expected a JSON object")
            try:
                return ResultSetSelection(**value)
            except TypeError as error:
                raise ValueError("Result Set selection fields are invalid.") from error

        def parse_artifact_selection(raw: str) -> ArtifactSelection:
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("Expected a JSON object")
            try:
                return ArtifactSelection(**value)
            except TypeError as error:
                raise ValueError("MCP output selection fields are invalid.") from error

        def parse_parameters(raw: str) -> dict[str, Any]:
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("Expected a JSON object")
            return value

        @tool
        async def plan_project_dataset_transform_run(
            definition_id: str,
            dataset_id: str,
            mode: str,
            parameters_json: str = "{}",
        ) -> str:
            """Review a Transform on all ordered Dataset Records before a durable Run.

            mode is dataset for one invocation over the collection, or perRecord for
            independent invocations and a Batch Result Set. Returns versions, Record
            IDs, invocation count, and output kind for the approval proposal.
            """
            plan = await inputs.plan_dataset_run(
                access,
                project_id,
                definition_id,
                dataset_id,
                TransformDatasetMode(mode),
                parse_parameters(parameters_json),
            )
            return json.dumps(plan.snapshot())

        @tool
        async def start_project_dataset_transform_run(
            definition_id: str,
            dataset_id: str,
            mode: str,
            expected_dataset_version: int,
            expected_transform_revision: int,
            tool_call_id: Annotated[str, InjectedToolCallId],
            parameters_json: str = "{}",
        ) -> str:
            """Start the reviewed Dataset Transform in dataset or perRecord mode after approval."""
            key = hashlib.sha256(
                f"agent-dataset-transform:{thread_id}:{tool_call_id}".encode()
            ).hexdigest()
            run = await inputs.start_dataset_run(
                access,
                project_id,
                definition_id,
                dataset_id,
                TransformDatasetMode(mode),
                expected_dataset_version,
                expected_transform_revision,
                parse_parameters(parameters_json),
                TransformInitiation("agentRun", "approved", thread_id, agent_run_id),
                key,
            )
            if isinstance(run, BatchRun):
                return (
                    f"Batch Run {run.id} {run.status}; Result Records are pending "
                    "until the Run reaches a terminal status."
                )
            return f"Transform Run {run.id} {run.status}."

        @tool
        async def plan_project_transform_result_set_selection(
            definition_id: str, selection_json: str, parameters_json: str = "{}"
        ) -> str:
            """Review selected values from a completed Batch Result Set for one Transform.

            selection_json uses source_run_id, output_path (JSON Pointer, empty for
            the whole structured output), expected_definition_revision, and optional
            filter_path, equals, sort_path, descending, and limit.
            """
            plan = await inputs.plan_result_set_selection(
                access,
                project_id,
                definition_id,
                parse_selection(selection_json),
                parse_parameters(parameters_json),
            )
            return json.dumps(plan.snapshot())

        @tool
        async def start_project_transform_result_set_selection_run(
            definition_id: str, selection_json: str, parameters_json: str = "{}"
        ) -> str:
            """Start a reviewed Result Set selection Transform Run after approval."""
            run = await inputs.start_result_set_run(
                access,
                project_id,
                definition_id,
                parse_selection(selection_json),
                parse_parameters(parameters_json),
                initiation=TransformInitiation(
                    kind="agentRun",
                    approval="approved",
                    thread_id=thread_id,
                    agent_run_id=agent_run_id,
                ),
            )
            return f"Transform Run {run.id} {run.status}."

        @tool
        async def plan_project_transform_artifact_selection(
            definition_id: str, selection_json: str, parameters_json: str = "{}"
        ) -> str:
            """Review retained MCP Tool Result Snapshot values for one Transform.

            selection_json uses artifact_id, expected_artifact_version, output_path
            (JSON Pointer into structured output), expected_definition_revision,
            and optional filter_path, equals, sort_path, descending, and limit.
            """
            plan = await inputs.plan_artifact_selection(
                access,
                project_id,
                definition_id,
                parse_artifact_selection(selection_json),
                parse_parameters(parameters_json),
            )
            return json.dumps(plan.snapshot())

        @tool
        async def start_project_transform_artifact_selection_run(
            definition_id: str, selection_json: str, parameters_json: str = "{}"
        ) -> str:
            """Start a reviewed MCP output selection Transform Run after approval."""
            run = await inputs.start_artifact_run(
                access,
                project_id,
                definition_id,
                parse_artifact_selection(selection_json),
                parse_parameters(parameters_json),
                initiation=TransformInitiation(
                    kind="agentRun",
                    approval="approved",
                    thread_id=thread_id,
                    agent_run_id=agent_run_id,
                ),
            )
            return f"Transform Run {run.id} {run.status}."

        return [
            plan_project_dataset_transform_run,
            start_project_dataset_transform_run,
            plan_project_transform_result_set_selection,
            start_project_transform_result_set_selection_run,
            plan_project_transform_artifact_selection,
            start_project_transform_artifact_selection_run,
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
