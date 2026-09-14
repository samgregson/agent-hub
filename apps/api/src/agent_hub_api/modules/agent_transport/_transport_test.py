from collections.abc import AsyncIterator

import pytest
from ag_ui.core import BaseEvent, Message, RunAgentInput, RunFinishedEvent, RunStartedEvent
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from agent_hub_api.modules.agent_execution import create_memory_agent_execution
from agent_hub_api.modules.agent_transport import (
    AgentTransportModule,
    create_agent_transport_router,
)
from agent_hub_api.modules.identity import create_identity_module
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module
from agent_hub_api.settings import Settings


class DeterministicRunner:
    async def load_messages(self, thread_id: str) -> tuple[Message, ...]:
        del thread_id
        return ()

    async def run(self, input_data: RunAgentInput) -> AsyncIterator[BaseEvent]:
        yield RunStartedEvent(thread_id=input_data.thread_id, run_id=input_data.run_id)
        yield RunFinishedEvent(thread_id=input_data.thread_id, run_id=input_data.run_id)


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
    assert history.json() == {"messages": []}
    assert unauthorized.status_code == 404
