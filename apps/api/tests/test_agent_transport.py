from collections.abc import AsyncIterator

import pytest
from ag_ui.core import BaseEvent, Message, RunAgentInput, RunFinishedEvent, RunStartedEvent
from httpx import ASGITransport, AsyncClient

from agent_hub_api.main import create_app
from agent_hub_api.modules.agent_execution import create_memory_agent_execution
from agent_hub_api.modules.identity import RequestContext, create_identity_module
from agent_hub_api.modules.projects import create_memory_project_module
from agent_hub_api.settings import Settings


class DeterministicRunner:
    async def load_messages(self, thread_id: str) -> tuple[Message, ...]:
        del thread_id
        return ()

    async def run(self, input_data: RunAgentInput) -> AsyncIterator[BaseEvent]:
        yield RunStartedEvent(thread_id=input_data.thread_id, run_id=input_data.run_id)
        yield RunFinishedEvent(thread_id=input_data.thread_id, run_id=input_data.run_id)


async def ready(_: Settings) -> None:
    return None


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
    context = RequestContext(subject="subject-a", request_id="request-1")
    project = await projects.create(context, "First")
    thread = await projects.create_thread(context, project.id, "Conversation")
    app = create_app(
        settings=settings,
        readiness_check=ready,
        identity=create_identity_module(settings),
        projects=projects,
        agent_execution=create_memory_agent_execution(DeterministicRunner()),
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
    bob_app = create_app(
        settings=bob_settings,
        readiness_check=ready,
        identity=create_identity_module(bob_settings),
        projects=projects,
        agent_execution=create_memory_agent_execution(DeterministicRunner()),
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
