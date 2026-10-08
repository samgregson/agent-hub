"""Seed or verify application and LangGraph state around a PostgreSQL restore."""

import asyncio
import os
import sys

from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection

from agent_hub_api.modules.artifacts import (
    ArtifactAccess,
    ArtifactDraft,
    ArtifactMutationAccess,
    create_postgres_artifact_module,
)
from agent_hub_api.modules.projects import ProjectAccess, create_postgres_project_module
from agent_hub_api.settings import Settings

_THREAD_ID = "foundation-restore-drill"
_MARKER = "checkpoint survives restore"
_PROJECT_NAME = "Foundation restore drill"
_SUBJECT = "foundation-restore-drill"


async def run(mode: str) -> None:
    if os.environ.get("AGENT_HUB_ALLOW_RESTORE_DRILL") != "1":
        raise RuntimeError("Restore drill requires an explicitly isolated database")
    settings = Settings()
    database_url = str(settings.database_url)
    projects = create_postgres_project_module(settings)
    artifacts = create_postgres_artifact_module(settings, projects)
    access = ProjectAccess(subject=_SUBJECT)

    if mode == "seed":
        project = await projects.create(access, _PROJECT_NAME)
        first = await projects.create_thread(access, project.id, "First Thread")
        await projects.create_thread(access, project.id, "Second Thread")
        await artifacts.create(
            ArtifactMutationAccess(subject=_SUBJECT, thread_id=first.id, run_id="restore-run"),
            project.id,
            ArtifactDraft(
                type="agent-hub.fixture.status",
                title="Restored status",
                plugin_id="foundation-fixture",
                plugin_version="0.1.0",
                schema_id="agent-hub.fixture.status",
                schema_version="1.0",
                payload={"status": "available"},
            ),
        )

    matching = [project for project in await projects.list(access) if project.name == _PROJECT_NAME]
    assert len(matching) == 1, "Foundation Project was not restored"
    project = matching[0]
    threads = await projects.list_threads(access, project.id)
    assert {thread.title for thread in threads} == {"First Thread", "Second Thread"}
    documents = await artifacts.discover(ArtifactAccess(subject=_SUBJECT), project.id)
    assert len(documents) == 1, "Foundation Artifact was not restored"
    document = documents[0]
    assert document.payload == {"status": "available"}
    assert document.artifact.provenance.created_by.thread_id is not None
    assert document.artifact.provenance.created_by.thread_id.root in {
        thread.id for thread in threads
    }
    assert document.artifact.provenance.created_by.run_id is not None
    assert document.artifact.provenance.created_by.run_id.root == "restore-run"
    connection = await AsyncConnection.connect(database_url)
    async with connection:
        cursor = await connection.execute(
            """
            SELECT action, document_version, actor_kind, actor_id
            FROM artifact_audit_events
            WHERE project_id = %s AND artifact_id = %s
            """,
            (project.id, document.artifact.id.root),
        )
        audit_rows = await cursor.fetchall()
    assert audit_rows == [("created", 1, "agentRun", "restore-run")]

    async with AsyncPostgresSaver.from_conn_string(database_url) as saver:
        if mode == "seed":
            await saver.setup()
            checkpoint = empty_checkpoint()
            checkpoint["channel_values"] = {"restore_marker": _MARKER}
            await saver.aput(
                {"configurable": {"thread_id": _THREAD_ID, "checkpoint_ns": ""}},
                checkpoint,
                {"source": "input", "step": 0, "parents": {}},
                {},
            )
        saved = await saver.aget_tuple(
            {"configurable": {"thread_id": _THREAD_ID, "checkpoint_ns": ""}}
        )
        assert saved is not None, "LangGraph checkpoint was not restored"
        assert saved.checkpoint["channel_values"]["restore_marker"] == _MARKER


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"seed", "verify"}:
        raise SystemExit("usage: foundation-restore-drill.py seed|verify")
    asyncio.run(run(sys.argv[1]))
