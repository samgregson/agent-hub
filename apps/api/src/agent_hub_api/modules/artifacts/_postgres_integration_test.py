import os

import pytest
from psycopg import AsyncConnection
from pydantic import PostgresDsn

from agent_hub_api.modules.artifacts import (
    ArtifactAccess,
    ArtifactDraft,
    ArtifactMutationAccess,
    create_postgres_artifact_module,
)
from agent_hub_api.modules.projects import ProjectAccess, create_postgres_project_module
from agent_hub_api.settings import Settings


@pytest.mark.asyncio
async def test_postgres_artifact_mutations_write_payload_free_audit_events() -> None:
    database_url = os.environ.get("AGENT_HUB_ISOLATED_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Requires an explicitly isolated PostgreSQL database")

    settings = Settings(environment="test", database_url=PostgresDsn(database_url))
    projects = create_postgres_project_module(settings)
    artifacts = create_postgres_artifact_module(settings, projects)
    access = ProjectAccess(subject="artifact-audit-drill")
    project = await projects.create(access, "Audit drill")
    try:
        first = await projects.create_thread(access, project.id, "First")
        second = await projects.create_thread(access, project.id, "Second")
        created = await artifacts.create(
            ArtifactMutationAccess(subject=access.subject, thread_id=first.id, run_id="run-a"),
            project.id,
            ArtifactDraft(
                type="agent-hub.fixture.status",
                title="Status",
                plugin_id="foundation-fixture",
                plugin_version="0.1.0",
                schema_id="agent-hub.fixture.status",
                schema_version="1.0",
                payload={"secretFixturePayload": "never-in-audit", "status": "available"},
            ),
        )
        await artifacts.replace(
            ArtifactMutationAccess(subject=access.subject, thread_id=second.id, run_id="run-b"),
            project.id,
            created.artifact.id.root,
            expected_version=1,
            replacement=created.model_copy(update={"payload": {"status": "unavailable"}}),
        )
        restarted = create_postgres_artifact_module(settings, projects)
        loaded = await restarted.load(
            ArtifactAccess(subject=access.subject), project.id, created.artifact.id.root
        )
        assert loaded.artifact.document_version == 2
        await restarted.delete(
            ArtifactAccess(subject=access.subject), project.id, created.artifact.id.root
        )

        connection = await AsyncConnection.connect(database_url)
        async with connection:
            cursor = await connection.execute(
                """
                SELECT action, document_version, actor_kind, actor_id
                FROM artifact_audit_events
                WHERE project_id = %s AND artifact_id = %s
                ORDER BY occurred_at, action
                """,
                (project.id, created.artifact.id.root),
            )
            rows = await cursor.fetchall()
        assert set(rows) == {
            ("created", 1, "agentRun", "run-a"),
            ("replaced", 2, "agentRun", "run-b"),
            ("deleted", 2, "subject", access.subject),
        }
        assert "never-in-audit" not in str(rows)
    finally:
        connection = await AsyncConnection.connect(database_url)
        async with connection:
            await connection.execute("DELETE FROM projects WHERE id=%s", (project.id,))
