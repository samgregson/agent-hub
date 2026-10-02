from collections.abc import Mapping
from typing import cast

import pytest
from psycopg import AsyncConnection, OperationalError
from pydantic import PostgresDsn

from agent_hub_api.modules.batch_execution import (
    BatchRunStatus,
    create_postgres_batch_execution_module,
)
from agent_hub_api.modules.datasets import DatasetRecordInput, create_postgres_dataset_module
from agent_hub_api.modules.plugin_gateway import PluginGatewayModule, PluginToolResult
from agent_hub_api.modules.projects import ProjectAccess, create_postgres_project_module
from agent_hub_api.modules.transforms import (
    TransformRuntimeIdentity,
    create_postgres_transform_module,
)
from agent_hub_api.settings import Settings


class Gateway:
    async def input_schema(self, *_: object) -> Mapping[str, object]:
        return {"type": "object", "properties": {"load": {"type": "number"}}}

    async def output_schema(self, *_: object) -> Mapping[str, object]:
        return {
            "type": "object",
            "required": ["result"],
            "properties": {"result": {"type": "number"}},
        }

    async def batch_call(
        self, _access: ProjectAccess, _project_id: str, _plugin_id: str,
        _tool_name: str, arguments: Mapping[str, object],
    ) -> PluginToolResult:
        return PluginToolResult((), {"result": arguments["load"]})


@pytest.mark.asyncio
async def test_postgres_transform_batch_definition_retains_result_set() -> None:
    settings = Settings(
        environment="test",
        database_url=PostgresDsn("postgresql://agent_hub:agent_hub@127.0.0.1:5432/agent_hub"),
    )
    try:
        connection = await AsyncConnection.connect(str(settings.database_url))
    except OperationalError:
        pytest.skip("Local PostgreSQL is unavailable")
    await connection.close()

    class Runner:
        async def identity(self) -> TransformRuntimeIdentity:
            return TransformRuntimeIdentity("deno:test;pyodide:test", "a" * 64)

        async def execute(
            self, source: str, inputs: dict[str, object], parameters: dict[str, object]
        ) -> tuple[object, str]:
            return {"result": cast(int, inputs["load"]) * 2}, "deno:test;pyodide:test"

    access = ProjectAccess(subject="transform-batch-postgres-integration")
    projects = create_postgres_project_module(settings)
    gateway = Gateway()
    datasets = create_postgres_dataset_module(settings, projects, gateway)
    transforms = create_postgres_transform_module(settings, projects, Runner())
    batches = create_postgres_batch_execution_module(
        settings, projects, datasets, cast(PluginGatewayModule, gateway), transforms
    )
    project = await projects.create(access, "Transform Batch integration")
    try:
        dataset = await datasets.create_dataset(
            access, project.id, "Loads",
            [DatasetRecordInput({"load": value}) for value in (2, 3)],
        )
        transform = await transforms.define(
            access, project.id, "Double",
            "def transform(inputs, parameters):\n    return {}\n",
            {"load": "/load"},
            {"type": "object", "required": ["result"]},
        )
        definition = await batches.define_transform_batch(
            access, project.id, dataset.id, "Double loads", transform.id
        )
        loaded_definition = await datasets.load_definition(access, project.id, definition.id)
        run = await batches.start_all(access, project.id, definition.id)
        page = await batches.inspect_results(access, project.id, run.id)

        assert loaded_definition.transform_definition_id == transform.id
        assert loaded_definition.plugin_id is None
        assert run.status is BatchRunStatus.succeeded
        assert [item.structured_output for item in page.items] == [
            {"result": 4}, {"result": 6},
        ]
    finally:
        connection = await AsyncConnection.connect(str(settings.database_url))
        async with connection:
            await connection.execute("DELETE FROM projects WHERE id=%s", (project.id,))


@pytest.mark.asyncio
async def test_postgres_batch_run_retains_captured_records_in_dataset_order() -> None:
    settings = Settings(
        environment="test",
        database_url=PostgresDsn("postgresql://agent_hub:agent_hub@127.0.0.1:5432/agent_hub"),
    )
    try:
        connection = await AsyncConnection.connect(str(settings.database_url))
    except OperationalError:
        pytest.skip("Local PostgreSQL is unavailable")
    await connection.close()

    access = ProjectAccess(subject="batch-postgres-integration")
    projects = create_postgres_project_module(settings)
    gateway = Gateway()
    datasets = create_postgres_dataset_module(settings, projects, gateway)
    batches = create_postgres_batch_execution_module(
        settings, projects, datasets, cast(PluginGatewayModule, gateway)
    )
    project = await projects.create(access, "Batch integration")
    try:
        dataset = await datasets.create_dataset(
            access, project.id, "Loads",
            [DatasetRecordInput({"load": value}) for value in (3, 1, 2)],
        )
        definition = await datasets.create_definition(
            access, project.id, dataset.id, "Echo", "fixture", "echo", {"load": "/load"},
        )
        queued = await batches.submit_all(
            access, project.id, definition.id, idempotency_key="same-submission"
        )

        loaded = await batches.load(access, project.id, queued.id)
        repeated = await batches.submit_all(
            access, project.id, definition.id, idempotency_key="same-submission"
        )
        completed = await batches.execute(access, project.id, queued.id)

        assert [record.input for record in loaded.records] == [
            {"load": 3}, {"load": 1}, {"load": 2},
        ]
        assert completed.status is BatchRunStatus.succeeded
        assert repeated.id == queued.id
        assert [record.structured_output for record in completed.records] == [
            {"result": 3}, {"result": 1}, {"result": 2},
        ]
        archived = await batches.archive(access, project.id, queued.id)
        retained = await batches.inspect_results(access, project.id, queued.id, limit=2)
        assert archived.archived_at is not None
        assert [record.input for record in retained.items] == [{"load": 3}, {"load": 1}]
        assert retained.next_offset == 2
        filtered = await batches.inspect_results(
            access, project.id, queued.id, limit=1,
            filter_path="/input/load", minimum=2,
            sort_path="/structuredOutput/result", descending=False,
            aggregate_path="/structuredOutput/result",
        )
        assert [record.input for record in filtered.items] == [{"load": 2}]
        assert filtered.summary.total_count == 2
        assert filtered.summary.numeric_sum == 5
    finally:
        connection = await AsyncConnection.connect(str(settings.database_url))
        async with connection:
            await connection.execute("DELETE FROM projects WHERE id=%s", (project.id,))
