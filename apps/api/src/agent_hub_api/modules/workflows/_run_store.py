"""PostgreSQL storage for prepared Workflow Runs."""

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import cast

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from agent_hub_api.modules.datasets import DatasetModule
from agent_hub_api.modules.plugin_gateway import PluginGatewayModule
from agent_hub_api.modules.transforms import TransformModule
from agent_hub_api.settings import Settings

from ._application import WorkflowDefinitionModule
from ._runs import WorkflowRun, WorkflowRunModule


class PostgresWorkflowRunStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def _connect(self) -> AsyncConnection[dict[str, object]]:
        return await AsyncConnection.connect(
            str(self._settings.database_url),
            connect_timeout=self._settings.database_connect_timeout_seconds,
            row_factory=dict_row,
        )

    async def create_or_load(self, run: WorkflowRun) -> WorkflowRun:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """INSERT INTO workflow_runs
                (project_id,run_id,workflow_id,definition_version,status,snapshot,
                 execution,initiator_subject,idempotency_key,created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (project_id,idempotency_key) DO NOTHING RETURNING *""",
                (
                    run.project_id,
                    run.id,
                    run.workflow_id,
                    run.definition_version,
                    run.status,
                    json.dumps(run.snapshot),
                    json.dumps(run.execution),
                    run.initiator_subject,
                    run.idempotency_key,
                    run.created_at,
                ),
            )
            row = await cursor.fetchone()
            if row is None:
                cursor = await connection.execute(
                    """SELECT * FROM workflow_runs
                    WHERE project_id=%s AND idempotency_key=%s""",
                    (run.project_id, run.idempotency_key),
                )
                row = await cursor.fetchone()
        assert row is not None
        return _from_row(row)

    async def load(self, project_id: str, run_id: str) -> WorkflowRun | None:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                "SELECT * FROM workflow_runs WHERE project_id=%s AND run_id=%s",
                (project_id, run_id),
            )
            row = await cursor.fetchone()
        return _from_row(row) if row else None

    async def by_key(self, project_id: str, key: str) -> WorkflowRun | None:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                "SELECT * FROM workflow_runs WHERE project_id=%s AND idempotency_key=%s",
                (project_id, key),
            )
            row = await cursor.fetchone()
        return _from_row(row) if row else None

    async def list(self, project_id: str, workflow_id: str) -> Sequence[WorkflowRun]:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """SELECT * FROM workflow_runs WHERE project_id=%s AND workflow_id=%s
                ORDER BY created_at DESC, run_id DESC""",
                (project_id, workflow_id),
            )
            rows = await cursor.fetchall()
        return tuple(_from_row(row) for row in rows)

    async def update(self, run: WorkflowRun, expected_status: str) -> WorkflowRun | None:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """UPDATE workflow_runs SET status=%s,execution=%s
                WHERE project_id=%s AND run_id=%s AND status=%s""",
                (
                    run.status,
                    json.dumps(run.execution),
                    run.project_id,
                    run.id,
                    expected_status,
                ),
            )
            if cursor.rowcount != 1:
                return None
        return run


def _from_row(row: Mapping[str, object]) -> WorkflowRun:
    raw = row["snapshot"]
    snapshot = json.loads(raw) if isinstance(raw, str) else raw
    assert isinstance(snapshot, dict)
    return WorkflowRun(
        id=str(row["run_id"]),
        project_id=str(row["project_id"]),
        workflow_id=str(row["workflow_id"]),
        definition_version=int(str(row["definition_version"])),
        status=str(row["status"]),
        snapshot=snapshot,
        execution=_decode(row["execution"]),
        initiator_subject=str(row["initiator_subject"]),
        idempotency_key=str(row["idempotency_key"]),
        created_at=cast(datetime, row["created_at"]),
    )


def _decode(raw: object) -> Mapping[str, object]:
    value = json.loads(raw) if isinstance(raw, str) else raw
    return value if isinstance(value, dict) else {}


def create_postgres_workflow_run_module(
    settings: Settings,
    definitions: WorkflowDefinitionModule,
    datasets: DatasetModule,
    transforms: TransformModule,
    gateway: PluginGatewayModule | None,
) -> WorkflowRunModule:
    return WorkflowRunModule(
        definitions, datasets, transforms, gateway, PostgresWorkflowRunStore(settings)
    )
