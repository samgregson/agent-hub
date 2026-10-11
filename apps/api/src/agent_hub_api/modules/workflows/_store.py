"""PostgreSQL adapter for versioned Workflow Definitions."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import datetime
from typing import cast

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from agent_hub_api.modules.datasets import DatasetModule
from agent_hub_api.modules.plugin_gateway import PluginGatewayModule
from agent_hub_api.modules.projects import ProjectModule
from agent_hub_api.modules.transforms import TransformModule
from agent_hub_api.settings import Settings

from ._application import (
    WorkflowDefinition,
    WorkflowDefinitionModule,
    WorkflowGraph,
)


class PostgresWorkflowStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def _connect(self) -> AsyncConnection[dict[str, object]]:
        return await AsyncConnection.connect(
            str(self._settings.database_url),
            connect_timeout=self._settings.database_connect_timeout_seconds,
            row_factory=dict_row,
        )

    async def create(self, definition: WorkflowDefinition) -> WorkflowDefinition:
        connection = await self._connect()
        async with connection:
            await connection.execute(
                """INSERT INTO workflow_definitions
                (project_id,workflow_id,name,graph,version,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (
                    definition.project_id,
                    definition.id,
                    definition.name,
                    json.dumps(asdict(definition.graph)),
                    definition.version,
                    definition.created_at,
                    definition.updated_at,
                ),
            )
        return definition

    async def load(self, project_id: str, definition_id: str) -> WorkflowDefinition | None:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """SELECT * FROM workflow_definitions
                WHERE project_id=%s AND workflow_id=%s""",
                (project_id, definition_id),
            )
            row = await cursor.fetchone()
        return _from_row(row) if row else None

    async def list(self, project_id: str) -> Sequence[WorkflowDefinition]:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """SELECT * FROM workflow_definitions WHERE project_id=%s
                ORDER BY created_at, workflow_id""",
                (project_id,),
            )
            rows = await cursor.fetchall()
        return tuple(_from_row(row) for row in rows)

    async def replace(
        self, definition: WorkflowDefinition, expected_version: int
    ) -> WorkflowDefinition | None:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """UPDATE workflow_definitions
                SET name=%s,graph=%s,version=%s,updated_at=%s
                WHERE project_id=%s AND workflow_id=%s AND version=%s""",
                (
                    definition.name,
                    json.dumps(asdict(definition.graph)),
                    definition.version,
                    definition.updated_at,
                    definition.project_id,
                    definition.id,
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                return None
        return definition


def _from_row(row: Mapping[str, object]) -> WorkflowDefinition:
    raw = row["graph"]
    graph = json.loads(raw) if isinstance(raw, str) else raw
    assert isinstance(graph, dict)
    return WorkflowDefinition(
        id=str(row["workflow_id"]),
        project_id=str(row["project_id"]),
        name=str(row["name"]),
        graph=WorkflowGraph.from_json(json.dumps(graph)),
        version=int(str(row["version"])),
        created_at=cast(datetime, row["created_at"]),
        updated_at=cast(datetime, row["updated_at"]),
    )


def create_postgres_workflow_module(
    settings: Settings,
    projects: ProjectModule,
    datasets: DatasetModule,
    transforms: TransformModule,
    gateway: PluginGatewayModule | None,
) -> WorkflowDefinitionModule:
    return WorkflowDefinitionModule(
        projects, datasets, transforms, gateway, PostgresWorkflowStore(settings)
    )
