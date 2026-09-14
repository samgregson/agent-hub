from collections.abc import AsyncIterator
from contextlib import AsyncExitStack

from ag_ui.core import BaseEvent, Message, RunAgentInput
from ag_ui_langgraph import LangGraphAgent
from ag_ui_langgraph.utils import langchain_messages_to_agui
from deepagents import create_deep_agent
from langchain_openai import ChatOpenAI

from agent_hub_api.settings import Settings


class PostgresDeepAgentRunner:
    """Lazily owns the Deep Agent and its long-lived PostgreSQL checkpointer."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._stack: AsyncExitStack | None = None
        self._agent: LangGraphAgent | None = None

    async def open(self) -> None:
        if self._agent is not None:
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
        graph = create_deep_agent(model=model, tools=[], checkpointer=checkpointer)
        self._agent = LangGraphAgent(
            name="agent-hub",
            graph=graph,
            config={"recursion_limit": self._settings.agent_recursion_limit},
        )
        self._stack = stack

    async def close(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = None
        self._agent = None

    async def run(self, input_data: RunAgentInput) -> AsyncIterator[BaseEvent]:
        await self.open()
        assert self._agent is not None
        request_agent = self._agent.clone()
        async for event in request_agent.run(input_data):
            yield event

    async def load_messages(self, thread_id: str) -> tuple[Message, ...]:
        await self.open()
        assert self._agent is not None
        state = await self._agent.graph.aget_state({"configurable": {"thread_id": thread_id}})
        messages = state.values.get("messages", [])
        return tuple(langchain_messages_to_agui(messages))
