from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from typing import Any

from ag_ui.core import BaseEvent, RunAgentInput
from ag_ui_langgraph.utils import langchain_messages_to_agui
from deepagents import create_deep_agent
from langchain.agents.middleware import InterruptOnConfig
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.base import BaseCheckpointSaver

from agent_hub_api.modules.agent_execution._ag_ui import (
    AgentHubLangGraphAgent,
    map_langchain_interrupts,
)
from agent_hub_api.modules.agent_execution._execution import AgentThreadState
from agent_hub_api.modules.agent_execution._project_files_backend import (
    create_project_files_backend,
)
from agent_hub_api.modules.project_files import ProjectFilesModule
from agent_hub_api.settings import Settings


@tool
def foundation_protected_action(note: str) -> str:
    """Echo a note after human approval to verify the interrupt transport."""
    return f"Approved foundation action: {note}"


class PostgresDeepAgentRunner:
    """Lazily owns the Deep Agent and its long-lived PostgreSQL checkpointer."""

    def __init__(self, settings: Settings, project_files: ProjectFilesModule) -> None:
        self._settings = settings
        self._project_files = project_files
        self._stack: AsyncExitStack | None = None
        self._agents: dict[str, AgentHubLangGraphAgent] = {}
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

    def _agent_for(self, project_id: str) -> AgentHubLangGraphAgent:
        existing = self._agents.get(project_id)
        if existing is not None:
            return existing
        assert self._checkpointer is not None
        assert self._model is not None
        tools = [foundation_protected_action] if self._settings.enable_foundation_test_tool else []
        interrupt_on: dict[str, bool | InterruptOnConfig] | None = (
            {
                "foundation_protected_action": {
                    "allowed_decisions": ["approve", "reject"],
                    "description": "Run the harmless foundation approval test action?",
                }
            }
            if self._settings.enable_foundation_test_tool
            else None
        )
        graph = create_deep_agent(
            model=self._model,
            tools=tools,
            system_prompt=(
                "Use /project for durable files shared by every Thread in the selected "
                "Project and /scratch for Thread-local working files. Never claim access "
                "to the host filesystem. When referring to a durable file in a response, "
                "link it as Markdown using its absolute /project path."
            ),
            interrupt_on=interrupt_on,
            backend=create_project_files_backend(self._project_files, project_id),
            checkpointer=self._checkpointer,
        )
        agent = AgentHubLangGraphAgent(
            name="agent-hub",
            graph=graph,
            config={"recursion_limit": self._settings.agent_recursion_limit},
            emit_interrupt_outcome=True,
        )
        self._agents[project_id] = agent
        return agent

    async def close(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = None
        self._agents.clear()
        self._checkpointer = None
        self._model = None

    async def run(self, input_data: RunAgentInput, *, project_id: str) -> AsyncIterator[BaseEvent]:
        await self.open()
        request_agent = self._agent_for(project_id).clone()
        async for event in request_agent.run(input_data):
            yield event

    async def load_thread_state(self, thread_id: str, *, project_id: str) -> AgentThreadState:
        await self.open()
        agent = self._agent_for(project_id)
        state = await agent.graph.aget_state({"configurable": {"thread_id": thread_id}})
        messages = state.values.get("messages", [])
        interrupts = [interrupt for task in state.tasks for interrupt in (task.interrupts or ())]
        return AgentThreadState(
            messages=tuple(langchain_messages_to_agui(messages)),
            interrupts=tuple(map_langchain_interrupts(interrupts, messages)),
        )
