import json
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from typing import Any

from ag_ui.core import BaseEvent, Context, RunAgentInput
from ag_ui_langgraph.utils import langchain_messages_to_agui
from deepagents import create_deep_agent
from deepagents.middleware.filesystem import FilesystemPermission
from langchain.agents.middleware import InterruptOnConfig
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
from agent_hub_api.modules.plugin_gateway import PluginGatewayModule
from agent_hub_api.modules.project_files import ProjectFilesModule
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
        "Never claim access to the host filesystem. When referring to a virtual file in "
        "a response, link it as Markdown using its absolute /project or /scratch path.",
    )
)


@tool
def foundation_protected_action(note: str) -> str:
    """Echo a note after human approval to verify the interrupt transport."""
    return f"Approved foundation action: {note}"


def _project_file_permissions() -> list[FilesystemPermission]:
    """Require an explicit decision before a Deep Agents file tool mutates a Project."""
    return [FilesystemPermission(operations=["write"], paths=["/project/**"], mode="interrupt")]


class PostgresDeepAgentRunner:
    """Lazily owns the Deep Agent and its long-lived PostgreSQL checkpointer."""

    def __init__(
        self,
        settings: Settings,
        project_files: ProjectFilesModule,
        plugin_gateway: PluginGatewayModule | None = None,
        artifacts: ArtifactModule | None = None,
    ) -> None:
        self._settings = settings
        self._project_files = project_files
        self._plugin_gateway = plugin_gateway
        self._artifacts = artifacts
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
    ) -> AgentHubLangGraphAgent:
        assert self._checkpointer is not None
        assert self._model is not None
        tools = [foundation_protected_action] if self._settings.enable_foundation_test_tool else []
        if self._plugin_gateway is not None:
            tools.extend(await self._plugin_gateway.agent_tools(project_id))
        artifacts = getattr(self, "_artifacts", None)
        has_artifact_context = (
            artifacts is not None
            and thread_id is not None
            and run_id is not None
            and subject is not None
        )
        if has_artifact_context:
            assert artifacts is not None
            assert thread_id is not None
            assert run_id is not None
            assert subject is not None
            tools.extend(self._artifact_tools(artifacts, project_id, thread_id, run_id, subject))
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
        if has_artifact_context:
            interrupt_on.update(
                {
                    "create_foundation_status_artifact": {
                        "allowed_decisions": ["approve", "reject"],
                        "description": "Create this Project Artifact?",
                    },
                    "set_foundation_status_artifact_status": {
                        "allowed_decisions": ["approve", "reject"],
                        "description": "Change this Project Artifact?",
                    },
                }
            )
        graph = create_deep_agent(
            model=self._model,
            tools=tools,
            system_prompt=_AGENT_SYSTEM_PROMPT,
            interrupt_on=interrupt_on or None,
            permissions=_project_file_permissions(),
            backend=create_project_files_backend(self._project_files, project_id),
            checkpointer=self._checkpointer,
        )
        agent = AgentHubLangGraphAgent(
            name="agent-hub",
            graph=graph,
            config={"recursion_limit": self._settings.agent_recursion_limit},
            enable_legacy_on_interrupt_event=False,
            emit_interrupt_outcome=True,
        )
        return agent

    @staticmethod
    def _artifact_tools(
        artifacts: ArtifactModule, project_id: str, thread_id: str, run_id: str, subject: str
    ) -> list[BaseTool]:
        access = ArtifactMutationAccess(subject=subject, thread_id=thread_id, run_id=run_id)

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

        @tool
        async def create_foundation_status_artifact(title: str) -> str:
            """Create a Foundation status Artifact in the selected Project."""
            document = await artifacts.create_from_plugin(
                access,
                project_id,
                plugin_id="foundation-fixture",
                tool_name="create_status_artifact",
                arguments={"title": title},
            )
            return (
                f"Created Project Artifact '{document.artifact.title}' "
                f"({document.artifact.id.root})."
            )

        @tool
        async def set_foundation_status_artifact_status(
            artifact_id: str,
            expected_version: int,
            status: str,
        ) -> str:
            """Set a Foundation status Artifact to available or unavailable."""
            document = await artifacts.apply_plugin_operation(
                access,
                project_id,
                artifact_id,
                expected_version=expected_version,
                tool_name="set_status_artifact_status",
                arguments={"status": status},
            )
            return (
                f"Updated Project Artifact '{document.artifact.title}' "
                f"to version {document.artifact.document_version}."
            )

        return [
            discover_project_artifacts,
            load_project_artifact,
            create_foundation_status_artifact,
            set_foundation_status_artifact_status,
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
        enriched = await self._with_change_notices(input_data, project_id, subject)
        request_agent = (
            await self._agent_for(
                project_id,
                thread_id=enriched.thread_id,
                run_id=enriched.run_id,
                subject=subject,
            )
        ).clone()
        async for event in request_agent.run(enriched):
            yield event

    async def _with_change_notices(
        self, input_data: RunAgentInput, project_id: str, subject: str | None
    ) -> RunAgentInput:
        if self._artifacts is None or subject is None:
            return input_data
        documents = await self._artifacts.discover(ArtifactAccess(subject=subject), project_id)
        changed = [
            document
            for document in documents
            if document.artifact.provenance.last_changed_by.thread_id != input_data.thread_id
        ]
        if not changed:
            return input_data
        value = "; ".join(
            f"{document.artifact.title} ({document.artifact.id.root}, "
            f"v{document.artifact.document_version})"
            for document in changed
        )
        return input_data.model_copy(
            update={
                "context": [
                    *input_data.context,
                    Context(description="Project change notices", value=value),
                ]
            }
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
