from collections.abc import AsyncIterator

import pytest
from ag_ui.core import (
    AssistantMessage,
    BaseEvent,
    FunctionCall,
    Interrupt,
    RunAgentInput,
    RunFinishedEvent,
    RunStartedEvent,
    ToolCall,
)
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from agent_hub_api.modules.agent_execution import (
    AgentThreadState,
    ScratchFile,
    ScratchFileNotFound,
    create_memory_agent_execution,
)
from agent_hub_api.modules.agent_transport import (
    AgentTransportModule,
    create_agent_transport_router,
)
from agent_hub_api.modules.identity import create_identity_module
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module
from agent_hub_api.settings import Settings


class DeterministicRunner:
    async def load_scratch_file(self, thread_id: str, *, project_id: str, path: str) -> ScratchFile:
        del thread_id, project_id, path
        raise ScratchFileNotFound

    async def load_thread_state(self, thread_id: str, *, project_id: str) -> AgentThreadState:
        del thread_id, project_id
        return AgentThreadState(messages=(), interrupts=())

    async def run(
        self, input_data: RunAgentInput, *, project_id: str, subject: str | None = None
    ) -> AsyncIterator[BaseEvent]:
        del project_id
        yield RunStartedEvent(thread_id=input_data.thread_id, run_id=input_data.run_id)
        yield RunFinishedEvent(thread_id=input_data.thread_id, run_id=input_data.run_id)


class InterruptedHistoryRunner(DeterministicRunner):
    async def load_thread_state(self, thread_id: str, *, project_id: str) -> AgentThreadState:
        del thread_id, project_id
        return AgentThreadState(
            messages=(
                AssistantMessage(
                    id="assistant-1",
                    tool_calls=[
                        ToolCall(
                            id="tool-1",
                            function=FunctionCall(
                                name="foundation_protected_action",
                                arguments='{"note":"test"}',
                            ),
                        )
                    ],
                ),
            ),
            interrupts=(
                Interrupt(
                    id="interrupt-1",
                    reason="tool_call",
                    tool_call_id="tool-1",
                ),
            ),
        )


class ScratchPreviewRunner(DeterministicRunner):
    async def load_scratch_file(self, thread_id: str, *, project_id: str, path: str) -> ScratchFile:
        del thread_id, project_id
        if path == "/scratch/check.md":
            return ScratchFile(path=path, content="# Working check\nNot durable")
        raise ScratchFileNotFound


def run_body(thread_id: str, run_id: str = "run-1") -> dict[str, object]:
    return {
        "threadId": thread_id,
        "runId": run_id,
        "messages": [],
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }


@pytest.mark.asyncio
async def test_agent_stream_requires_owned_matching_thread() -> None:
    settings = Settings(environment="test", fixed_identity_subject="subject-a")
    projects = create_memory_project_module()
    access = ProjectAccess(subject="subject-a")
    project = await projects.create(access, "First")
    thread = await projects.create_thread(access, project.id, "Conversation")
    app = FastAPI()
    app.include_router(
        create_agent_transport_router(
            create_identity_module(settings),
            AgentTransportModule(projects, create_memory_agent_execution(DeterministicRunner())),
        ),
        prefix="/api",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        mismatch = await client.post(
            f"/api/projects/{project.id}/threads/{thread.id}/agent",
            json=run_body("another-thread"),
        )
        streamed = await client.post(
            f"/api/projects/{project.id}/threads/{thread.id}/agent",
            json=run_body(thread.id),
            headers={"accept": "text/event-stream"},
        )
        runs = await client.get(f"/api/projects/{project.id}/threads/{thread.id}/runs")
        history = await client.get(f"/api/projects/{project.id}/threads/{thread.id}/history")

    bob_settings = Settings(environment="test", fixed_identity_subject="subject-b")
    bob_app = FastAPI()
    bob_app.include_router(
        create_agent_transport_router(
            create_identity_module(bob_settings),
            AgentTransportModule(projects, create_memory_agent_execution(DeterministicRunner())),
        ),
        prefix="/api",
    )
    async with AsyncClient(transport=ASGITransport(app=bob_app), base_url="http://test") as bob:
        unauthorized = await bob.post(
            f"/api/projects/{project.id}/threads/{thread.id}/agent",
            json=run_body(thread.id, "run-2"),
        )

    assert mismatch.status_code == 409
    assert streamed.status_code == 200
    assert "RUN_STARTED" in streamed.text
    assert "RUN_FINISHED" in streamed.text
    assert runs.json()[0]["status"] == "succeeded"
    assert history.json() == {"interrupts": [], "messages": []}
    assert unauthorized.status_code == 404


@pytest.mark.asyncio
async def test_history_returns_pending_interrupts_for_approval_restoration() -> None:
    settings = Settings(environment="test", fixed_identity_subject="subject-a")
    projects = create_memory_project_module()
    access = ProjectAccess(subject="subject-a")
    project = await projects.create(access, "First")
    thread = await projects.create_thread(access, project.id, "Conversation")
    app = FastAPI()
    app.include_router(
        create_agent_transport_router(
            create_identity_module(settings),
            AgentTransportModule(
                projects, create_memory_agent_execution(InterruptedHistoryRunner())
            ),
        ),
        prefix="/api",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        history = await client.get(f"/api/projects/{project.id}/threads/{thread.id}/history")

    assert history.status_code == 200
    assert history.json()["interrupts"] == [
        {
            "id": "interrupt-1",
            "reason": "tool_call",
            "toolCallId": "tool-1",
        }
    ]
    assert history.json()["messages"][0]["toolCalls"][0]["id"] == "tool-1"


@pytest.mark.asyncio
async def test_scratch_preview_is_thread_scoped_and_never_uses_project_file_storage() -> None:
    settings = Settings(environment="test", fixed_identity_subject="subject-a")
    projects = create_memory_project_module()
    access = ProjectAccess(subject="subject-a")
    project = await projects.create(access, "First")
    thread = await projects.create_thread(access, project.id, "Conversation")
    runner = ScratchPreviewRunner()
    app = FastAPI()
    app.include_router(
        create_agent_transport_router(
            create_identity_module(settings),
            AgentTransportModule(projects, create_memory_agent_execution(runner)),
        ),
        prefix="/api",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        preview = await client.get(
            f"/api/projects/{project.id}/threads/{thread.id}/scratch",
            params={"path": "/scratch/check.md"},
        )
        wrong_scope = await client.get(
            f"/api/projects/{project.id}/threads/{thread.id}/scratch",
            params={"path": "/project/check.md"},
        )

    assert preview.status_code == 200
    assert preview.json() == {
        "path": "/scratch/check.md",
        "content": "# Working check\nNot durable",
    }
    assert wrong_scope.status_code == 422
