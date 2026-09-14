from collections.abc import AsyncIterator
from dataclasses import dataclass

from ag_ui.core import BaseEvent, Message, RunAgentInput

from agent_hub_api.modules.agent_execution import (
    AgentExecutionModule,
    AgentRun,
    DuplicateAgentRun,
)
from agent_hub_api.modules.projects import ProjectAccess, ProjectModule, ThreadNotFound


@dataclass(frozen=True, slots=True)
class AgentThreadAccess:
    """The authorized Project and request scope for one Thread operation."""

    subject: str
    request_id: str
    project_id: str
    thread_id: str


class AgentThreadNotFound(Exception):
    """No Thread is visible in the supplied Project and identity scope."""


class DuplicateAgentTransportRun(Exception):
    """The supplied Run ID already belongs to a durable Agent Run."""


class AgentTransportModule:
    """Own project authorization and durable execution behind the AG-UI seam."""

    def __init__(self, projects: ProjectModule, execution: AgentExecutionModule) -> None:
        self._projects = projects
        self._execution = execution

    async def list_runs(self, access: AgentThreadAccess) -> tuple[AgentRun, ...]:
        await self._authorize(access)
        return await self._execution.list_runs(access.thread_id)

    async def load_messages(self, access: AgentThreadAccess) -> tuple[Message, ...]:
        await self._authorize(access)
        return await self._execution.load_messages(access.thread_id)

    async def start(
        self, access: AgentThreadAccess, input_data: RunAgentInput
    ) -> AsyncIterator[BaseEvent]:
        await self._authorize(access)
        try:
            return await self._execution.start(input_data, request_id=access.request_id)
        except DuplicateAgentRun as error:
            raise DuplicateAgentTransportRun from error

    async def _authorize(self, access: AgentThreadAccess) -> None:
        try:
            await self._projects.load_thread(
                ProjectAccess(subject=access.subject), access.project_id, access.thread_id
            )
        except ThreadNotFound as error:
            raise AgentThreadNotFound from error
