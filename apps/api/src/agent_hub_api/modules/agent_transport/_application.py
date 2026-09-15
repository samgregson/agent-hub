from collections.abc import AsyncIterator
from dataclasses import dataclass

from ag_ui.core import BaseEvent, RunAgentInput

from agent_hub_api.modules.agent_execution import (
    AgentExecutionModule,
    AgentRun,
    AgentRunAlreadyActive,
    AgentThreadState,
    DuplicateAgentRun,
    InvalidAgentRunResume,
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


class AgentTransportRunAlreadyActive(Exception):
    """The Thread already has an active Agent Run."""


class InvalidAgentTransportResume(Exception):
    """The supplied responses do not match the pending Thread interrupts."""


class AgentTransportModule:
    """Own project authorization and durable execution behind the AG-UI seam."""

    def __init__(self, projects: ProjectModule, execution: AgentExecutionModule) -> None:
        self._projects = projects
        self._execution = execution

    async def list_runs(self, access: AgentThreadAccess) -> tuple[AgentRun, ...]:
        await self._authorize(access)
        return await self._execution.list_runs(access.thread_id)

    async def load_thread_state(self, access: AgentThreadAccess) -> AgentThreadState:
        await self._authorize(access)
        return await self._execution.load_thread_state(
            access.thread_id, project_id=access.project_id
        )

    async def start(
        self, access: AgentThreadAccess, input_data: RunAgentInput
    ) -> AsyncIterator[BaseEvent]:
        await self._authorize(access)
        try:
            return await self._execution.start(
                input_data,
                project_id=access.project_id,
                request_id=access.request_id,
            )
        except DuplicateAgentRun as error:
            raise DuplicateAgentTransportRun from error
        except AgentRunAlreadyActive as error:
            raise AgentTransportRunAlreadyActive from error
        except InvalidAgentRunResume as error:
            raise InvalidAgentTransportResume from error

    async def _authorize(self, access: AgentThreadAccess) -> None:
        try:
            await self._projects.load_thread(
                ProjectAccess(subject=access.subject), access.project_id, access.thread_id
            )
        except ThreadNotFound as error:
            raise AgentThreadNotFound from error
