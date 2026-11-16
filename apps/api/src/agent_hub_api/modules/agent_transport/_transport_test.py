import asyncio
from collections.abc import AsyncIterator
from typing import cast

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
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from httpx import ASGITransport, AsyncClient
from starlette.requests import ClientDisconnect

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
from agent_hub_api.modules.identity import RequestContext, create_identity_module
from agent_hub_api.modules.project_files import create_memory_project_files
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


class UnconfiguredRunner(DeterministicRunner):
    async def load_thread_state(self, thread_id: str, *, project_id: str) -> AgentThreadState:
        del thread_id, project_id
        raise RuntimeError("AGENT_HUB_OPENAI_API_KEY is required to run the agent")


class WaitingRunner(DeterministicRunner):
    async def run(
        self, input_data: RunAgentInput, *, project_id: str, subject: str | None = None
    ) -> AsyncIterator[BaseEvent]:
        yield RunStartedEvent(thread_id=input_data.thread_id, run_id=input_data.run_id)
        await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_disconnected_response_closes_run_and_allows_retry() -> None:
    settings = Settings(environment="test", fixed_identity_subject="subject-a")
    projects = create_memory_project_module()
    access = ProjectAccess(subject="subject-a")
    project = await projects.create(access, "Disconnect test")
    thread = await projects.create_thread(access, project.id, "Conversation")
    execution = create_memory_agent_execution(WaitingRunner())
    router = create_agent_transport_router(
        create_identity_module(settings),
        AgentTransportModule(projects, execution, create_memory_project_files(projects)),
    )
    endpoint = next(route.endpoint for route in router.routes if route.path.endswith("/agent"))
    response = cast(
        StreamingResponse,
        await endpoint(
            project.id,
            thread.id,
            RunAgentInput.model_validate(run_body(thread.id)),
            Request({"type": "http", "method": "POST", "path": "/", "headers": []}),
            RequestContext(subject="subject-a", request_id="request-1"),
        ),
    )

    async def send(message: dict[str, object]) -> None:
        if message["type"] == "http.response.body":
            raise OSError("Client disconnected")

    async def receive() -> dict[str, object]:
        await asyncio.Event().wait()
        return {"type": "http.disconnect"}

    with pytest.raises(ClientDisconnect):
        await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
    assert (await execution.list_runs(thread.id))[0].status.value == "cancelled"
    retry = await execution.start(
        RunAgentInput.model_validate(run_body(thread.id, "run-2")),
        project_id=project.id,
        request_id="request-2",
    )
    await anext(retry)
    await retry.aclose()


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
            AgentTransportModule(
                projects,
                create_memory_agent_execution(DeterministicRunner()),
                create_memory_project_files(projects),
            ),
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
            AgentTransportModule(
                projects,
                create_memory_agent_execution(DeterministicRunner()),
                create_memory_project_files(projects),
            ),
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
    assert history.json() == {"interrupts": [], "messages": [], "approvals": []}
    assert unauthorized.status_code == 404


@pytest.mark.asyncio
async def test_new_thread_history_is_empty_without_starting_an_unconfigured_agent() -> None:
    settings = Settings(environment="test", fixed_identity_subject="subject-a")
    projects = create_memory_project_module()
    access = ProjectAccess(subject="subject-a")
    project = await projects.create(access, "First")
    thread = await projects.create_thread(access, project.id, "New Thread 1")
    app = FastAPI()
    app.include_router(
        create_agent_transport_router(
            create_identity_module(settings),
            AgentTransportModule(
                projects,
                create_memory_agent_execution(UnconfiguredRunner()),
                create_memory_project_files(projects),
            ),
        ),
        prefix="/api",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        history = await client.get(f"/api/projects/{project.id}/threads/{thread.id}/history")

    assert history.status_code == 200
    assert history.json() == {"approvals": [], "interrupts": [], "messages": []}


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
                projects,
                create_memory_agent_execution(InterruptedHistoryRunner()),
                create_memory_project_files(projects),
            ),
        ),
        prefix="/api",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            f"/api/projects/{project.id}/threads/{thread.id}/agent",
            json=run_body(thread.id),
            headers={"accept": "text/event-stream"},
        )
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
            AgentTransportModule(
                projects,
                create_memory_agent_execution(runner),
                create_memory_project_files(projects),
            ),
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


@pytest.mark.asyncio
async def test_direct_user_can_save_scratch_to_a_new_project_file() -> None:
    settings = Settings(environment="test", fixed_identity_subject="subject-a")
    projects = create_memory_project_module()
    access = ProjectAccess(subject="subject-a")
    project = await projects.create(access, "First")
    thread = await projects.create_thread(access, project.id, "Conversation")
    files = create_memory_project_files(projects)
    app = FastAPI()
    app.include_router(
        create_agent_transport_router(
            create_identity_module(settings),
            AgentTransportModule(
                projects,
                create_memory_agent_execution(ScratchPreviewRunner()),
                files,
            ),
        ),
        prefix="/api",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        saved = await client.post(
            f"/api/projects/{project.id}/threads/{thread.id}/scratch/save",
            json={
                "destinationPath": "/project/checks/foundation.md",
                "sourcePath": "/scratch/check.md",
            },
        )
        duplicate = await client.post(
            f"/api/projects/{project.id}/threads/{thread.id}/scratch/save",
            json={
                "destinationPath": "/project/checks/foundation.md",
                "sourcePath": "/scratch/check.md",
            },
        )

    assert saved.status_code == 200
    assert saved.json() == {"path": "/project/checks/foundation.md", "version": 1}
    saved_file = await files.load(project.id, "/checks/foundation.md")
    assert saved_file.content == "# Working check\nNot durable"
    assert duplicate.status_code == 409
