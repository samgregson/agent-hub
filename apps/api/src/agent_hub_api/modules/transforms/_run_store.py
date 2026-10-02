"""PostgreSQL adapter for immutable Transform Run records."""

import json
from collections.abc import Mapping
from datetime import datetime
from typing import cast

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from agent_hub_api.modules.transforms._application import (
    TransformExecutionError,
    TransformRun,
    TransformRunPage,
)
from agent_hub_api.settings import Settings


class PostgresTransformRunStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def _connect(self) -> AsyncConnection[dict[str, object]]:
        return await AsyncConnection.connect(
            str(self._settings.database_url),
            connect_timeout=self._settings.database_connect_timeout_seconds,
            row_factory=dict_row,
        )

    async def create(self, run: TransformRun) -> TransformRun:
        connection = await self._connect()
        async with connection:
            await connection.execute(
                """INSERT INTO transform_runs
                (project_id,transform_run_id,transform_definition_id,status,definition_snapshot,
                inputs,parameters,input_hash,source_hash,runtime,package_hash,output,output_manifest,error,
                initiator_subject,initiation,limits,created_at,completed_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                _values(run),
            )
        return run

    async def complete(self, run: TransformRun) -> TransformRun:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """UPDATE transform_runs SET status=%s,runtime=%s,output=%s,
                output_manifest=%s,error=%s,completed_at=%s
                WHERE project_id=%s AND transform_run_id=%s AND status='running'""",
                (
                    run.status, run.runtime, json.dumps(run.output),
                    json.dumps(run.output_manifest), run.error, run.completed_at,
                    run.project_id, run.id,
                ),
            )
            if cursor.rowcount != 1:
                raise TransformExecutionError("run_already_completed")
        return run

    async def load(self, project_id: str, run_id: str) -> TransformRun | None:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """SELECT * FROM transform_runs
                WHERE project_id=%s AND transform_run_id=%s""",
                (project_id, run_id),
            )
            row = await cursor.fetchone()
        return _from_row(row) if row else None

    async def list(
        self, project_id: str, definition_id: str | None, limit: int, offset: int
    ) -> TransformRunPage:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """SELECT * FROM transform_runs WHERE project_id=%s
                AND (%s::text IS NULL OR transform_definition_id=%s)
                ORDER BY created_at DESC, transform_run_id DESC LIMIT %s OFFSET %s""",
                (project_id, definition_id, definition_id, limit + 1, offset),
            )
            rows = await cursor.fetchall()
        return TransformRunPage(
            tuple(_from_row(row) for row in rows[:limit]),
            offset + limit if len(rows) > limit else None,
        )

    async def reconcile_running(self, now: datetime) -> int:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """UPDATE transform_runs SET status='failed',error='interrupted',completed_at=%s
                WHERE status='running'""",
                (now,),
            )
            return cursor.rowcount


def _values(run: TransformRun) -> tuple[object, ...]:
    return (
        run.project_id, run.id, run.definition_id, run.status,
        json.dumps(run.definition_snapshot), json.dumps(run.inputs),
        json.dumps(run.parameters), run.input_hash, run.source_hash,
        run.runtime, run.package_hash, json.dumps(run.output), json.dumps(run.output_manifest),
        run.error, run.initiator_subject, json.dumps(run.initiation),
        json.dumps(run.limits), run.created_at, run.completed_at,
    )


def _json(value: object) -> object:
    return json.loads(value) if isinstance(value, str) else value


def _from_row(row: Mapping[str, object]) -> TransformRun:
    return TransformRun(
        id=str(row["transform_run_id"]),
        project_id=str(row["project_id"]),
        definition_id=str(row["transform_definition_id"]),
        status=str(row["status"]),
        definition_snapshot=cast(Mapping[str, object], _json(row["definition_snapshot"])),
        inputs=cast(Mapping[str, object], _json(row["inputs"])),
        parameters=cast(Mapping[str, object], _json(row["parameters"])),
        input_hash=str(row["input_hash"]),
        source_hash=str(row["source_hash"]),
        runtime=str(row["runtime"]) if row["runtime"] is not None else None,
        package_hash=str(row["package_hash"]) if row["package_hash"] is not None else None,
        output=_json(row["output"]),
        output_manifest=cast(Mapping[str, object], _json(row["output_manifest"])),
        error=str(row["error"]) if row["error"] is not None else None,
        initiator_subject=str(row["initiator_subject"]),
        initiation=cast(Mapping[str, object], _json(row["initiation"])),
        limits=cast(Mapping[str, object], _json(row["limits"])),
        created_at=cast(datetime, row["created_at"]),
        completed_at=cast(datetime | None, row["completed_at"]),
    )
