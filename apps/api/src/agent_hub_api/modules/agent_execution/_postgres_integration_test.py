import os
from typing import cast

import pytest
from ag_ui.core import RunAgentInput
from psycopg import AsyncConnection
from pydantic import PostgresDsn

from agent_hub_api.modules.agent_execution import (
    AgentRunner,
    AgentRunStatus,
    create_postgres_agent_execution,
)
from agent_hub_api.modules.projects import ProjectAccess, create_postgres_project_module
from agent_hub_api.settings import Settings


@pytest.mark.asyncio
async def test_postgres_restart_reconciles_a_running_agent_run() -> None:
    database_url = os.environ.get("AGENT_HUB_ISOLATED_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Requires an explicitly isolated PostgreSQL database")

    settings = Settings(environment="test", database_url=PostgresDsn(database_url))
    projects = create_postgres_project_module(settings)
    access = ProjectAccess(subject="restart-drill")
    project = await projects.create(access, "Restart drill")
    try:
        thread = await projects.create_thread(access, project.id, "Interrupted by restart")
        run_input = RunAgentInput.model_validate(
            {
                "threadId": thread.id,
                "runId": "restart-drill-run",
                "messages": [],
                "tools": [],
                "context": [],
                "forwardedProps": {},
            }
        )
        running = create_postgres_agent_execution(settings, cast(AgentRunner, object()))
        _ = await running.start(
            run_input,
            project_id=project.id,
            request_id="restart-drill-request",
        )

        restarted = create_postgres_agent_execution(settings, cast(AgentRunner, object()))
        assert await restarted.reconcile_non_terminal() == 1
        saved = (await restarted.list_runs(thread.id))[0]
        assert saved.status is AgentRunStatus.FAILED
        assert saved.error is not None
        assert saved.error.code == "RUN_ABANDONED_ON_RESTART"
        assert saved.error.request_id.root == "restart-drill-request"
    finally:
        connection = await AsyncConnection.connect(database_url)
        async with connection:
            await connection.execute("DELETE FROM projects WHERE id=%s", (project.id,))
