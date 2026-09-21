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
    ScratchFile,
)
from agent_hub_api.modules.project_files import ProjectFile, ProjectFileAccess, ProjectFilesModule
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

    def __init__(
        self,
        projects: ProjectModule,
        execution: AgentExecutionModule,
        project_files: ProjectFilesModule,
    ) -> None:
        self._projects = projects
        self._execution = execution
        self._project_files = project_files

    async def list_runs(self, access: AgentThreadAccess) -> tuple[AgentRun, ...]:
        await self._authorize(access)
        return await self._execution.list_runs(access.thread_id)

    async def load_thread_state(self, access: AgentThreadAccess) -> AgentThreadState:
        await self._authorize(access)
        return await self._execution.load_thread_state(
            access.thread_id, project_id=access.project_id
        )

    async def load_scratch_file(self, access: AgentThreadAccess, path: str) -> ScratchFile:
        await self._authorize(access)
        return await self._execution.load_scratch_file(
            access.thread_id, project_id=access.project_id, path=path
        )

    async def save_scratch_to_project(
        self, access: AgentThreadAccess, source_path: str, destination_path: str
    ) -> ProjectFile:
        """Copy one authorized Thread-local file into a new Project file."""
        scratch = await self.load_scratch_file(access, source_path)
        return await self._project_files.create_visible(
            ProjectFileAccess(subject=access.subject),
            access.project_id,
            destination_path,
            scratch.content,
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
                subject=access.subject,
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
