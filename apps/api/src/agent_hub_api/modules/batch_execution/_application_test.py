import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import cast

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from agent_hub_api.modules.batch_execution import (
    BatchExecutionModule,
    BatchInitiation,
    BatchRun,
    BatchRunOrder,
    BatchRunStatus,
    MemoryBatchRunStore,
    create_batch_execution_router,
)
from agent_hub_api.modules.datasets import (
    DatasetModule,
    DatasetRecordInput,
    MemoryDatasetStore,
)
from agent_hub_api.modules.identity import create_identity_module
from agent_hub_api.modules.plugin_gateway import PluginGatewayModule, PluginToolResult
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module
from agent_hub_api.modules.transforms import (
    MemoryTransformStore,
    TransformModule,
    TransformRuntimeIdentity,
)
from agent_hub_api.settings import Settings


class ToolSchemas:
    async def input_schema(self, *_: object) -> Mapping[str, object]:
        return {
            "type": "object",
            "required": ["load"],
            "properties": {"load": {"type": "number"}},
        }


class Gateway:
    def __init__(
        self, fail_loads: set[int] | None = None, invalid_loads: set[int] | None = None
    ) -> None:
        self.calls: list[int] = []
        self.fail_loads = fail_loads or set()
        self.invalid_loads = invalid_loads or set()
        self.active = 0
        self.maximum_active = 0

    async def batch_call(
        self,
        _access: ProjectAccess,
        _project_id: str,
        _plugin_id: str,
        _tool_name: str,
        arguments: Mapping[str, object],
    ) -> PluginToolResult:
        raw_load = arguments["load"]
        assert isinstance(raw_load, (int, float))
        load = int(raw_load)
        self.calls.append(load)
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        await asyncio.sleep(0)
        self.active -= 1
        if load in self.fail_loads:
            raise RuntimeError(f"load {load} failed")
        if load in self.invalid_loads:
            return PluginToolResult((), {"unexpected": load})
        return PluginToolResult((), {"result": load * 2})

    async def output_schema(self, *_: object) -> Mapping[str, object]:
        return {
            "type": "object",
            "required": ["result"],
            "properties": {"result": {"type": "number"}},
        }


@pytest.mark.asyncio
async def test_transform_batch_uses_captured_definition_and_first_record_guard() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="sam")
    project = await projects.create(owner, "Bridge")
    datasets = DatasetModule(projects, MemoryDatasetStore(), ToolSchemas())
    dataset = await datasets.create_dataset(
        owner,
        project.id,
        "Loads",
        [DatasetRecordInput({"load": value}) for value in (2, 3, 4)],
    )

    class Runner:
        calls: list[int] = []

        async def identity(self) -> TransformRuntimeIdentity:
            return TransformRuntimeIdentity("deno:test;pyodide:test", "a" * 64)

        async def execute(
            self, source: str, inputs: dict[str, object], parameters: dict[str, object]
        ) -> tuple[object, str]:
            assert parameters == {}
            assert "return {}" in source
            load = cast(int, inputs["load"])
            self.calls.append(load)
            return {"result": load * 2}, "deno:test;pyodide:test"

    runner = Runner()
    transforms = TransformModule(projects, MemoryTransformStore(), runner)
    transform = await transforms.define(
        owner,
        project.id,
        "Double",
        "def transform(inputs, parameters):\n    return {}\n",
        {"load": "/load"},
        {"type": "object", "required": ["result"], "properties": {"result": {"type": "number"}}},
    )
    batches = BatchExecutionModule(
        projects,
        datasets,
        cast(PluginGatewayModule, Gateway()),
        MemoryBatchRunStore(),
        transforms=transforms,
    )
    definition = await batches.define_transform_batch(
        owner,
        project.id,
        dataset.id,
        "Double loads",
        transform.id,
    )
    queued = await batches.submit_all(owner, project.id, definition.id)
    await transforms.revise(
        owner,
        project.id,
        transform.id,
        "Changed",
        "def transform(inputs, parameters):\n    return {'result': 999}\n",
        {"load": "/load"},
        {"type": "object"},
    )
    run = await batches.execute(owner, project.id, queued.id)
    page = await batches.inspect_results(owner, project.id, run.id, limit=2)

    assert run.status is BatchRunStatus.succeeded
    assert runner.calls == [2, 3, 4]
    assert [item.structured_output for item in page.items] == [
        {"result": 4},
        {"result": 6},
    ]
    assert run.definition_snapshot["transformDefinitionId"] == transform.id
    assert run.definition_snapshot["sourceHash"] == transform.source_hash
    assert run.definition_snapshot["packageHash"] == transform.package_hash


@pytest.mark.asyncio
async def test_transform_batch_stops_when_first_output_breaks_contract() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="sam")
    project = await projects.create(owner, "Bridge")
    datasets = DatasetModule(projects, MemoryDatasetStore(), ToolSchemas())
    dataset = await datasets.create_dataset(
        owner,
        project.id,
        "Loads",
        [DatasetRecordInput({"load": value}) for value in (1, 2, 3)],
    )

    class Runner:
        calls: list[int] = []

        async def identity(self) -> TransformRuntimeIdentity:
            return TransformRuntimeIdentity("deno:test;pyodide:test", "a" * 64)

        async def execute(
            self, source: str, inputs: dict[str, object], parameters: dict[str, object]
        ) -> tuple[object, str]:
            self.calls.append(cast(int, inputs["load"]))
            return {"unexpected": 1}, "deno:test;pyodide:test"

    runner = Runner()
    transforms = TransformModule(projects, MemoryTransformStore(), runner)
    transform = await transforms.define(
        owner,
        project.id,
        "Double",
        "def transform(inputs, parameters):\n    return {}\n",
        {"load": "/load"},
        {"type": "object", "required": ["result"]},
    )
    batches = BatchExecutionModule(
        projects,
        datasets,
        cast(PluginGatewayModule, Gateway()),
        MemoryBatchRunStore(),
        transforms=transforms,
    )
    definition = await batches.define_transform_batch(
        owner,
        project.id,
        dataset.id,
        "Double loads",
        transform.id,
    )

    run = await batches.start_all(owner, project.id, definition.id)

    assert run.status is BatchRunStatus.failed
    assert runner.calls == [1]
    assert run.records[0].error == "Transform output does not match its output schema."


async def create_module(
    gateway: Gateway, max_concurrency: int = 4
) -> tuple[ProjectAccess, str, BatchExecutionModule, str]:
    projects = create_memory_project_module()
    access = ProjectAccess(subject="sam")
    project = await projects.create(access, "Bridge")
    datasets = DatasetModule(projects, MemoryDatasetStore(), ToolSchemas())
    dataset = await datasets.create_dataset(
        access,
        project.id,
        "Load cases",
        [DatasetRecordInput({"load": load}, source_key=f"LC-{load}") for load in range(1, 6)],
    )
    definition = await datasets.create_definition(
        access,
        project.id,
        dataset.id,
        "Double loads",
        "reference-calculation",
        "double_load",
        {"load": "/load"},
    )
    return (
        access,
        project.id,
        BatchExecutionModule(
            projects,
            datasets,
            cast(PluginGatewayModule, gateway),
            MemoryBatchRunStore(),
            max_concurrency=max_concurrency,
        ),
        definition.id,
    )


@pytest.mark.asyncio
async def test_first_failed_record_stops_the_batch_before_fanout() -> None:
    gateway = Gateway({1})
    access, project_id, batches, definition_id = await create_module(gateway)

    run = await batches.start_all(access, project_id, definition_id)

    assert run.status is BatchRunStatus.failed
    assert gateway.calls == [1]
    assert run.records[0].error == "load 1 failed"


@pytest.mark.asyncio
async def test_first_schema_invalid_result_stops_the_batch_before_fanout() -> None:
    gateway = Gateway(invalid_loads={1})
    access, project_id, batches, definition_id = await create_module(gateway)

    run = await batches.start_all(access, project_id, definition_id)

    assert run.status is BatchRunStatus.failed
    assert gateway.calls == [1]
    assert run.records[0].error is not None


@pytest.mark.asyncio
async def test_batch_limits_concurrency_persists_partial_results_and_lists_newest_first() -> None:
    gateway = Gateway({4})
    access, project_id, batches, definition_id = await create_module(gateway, max_concurrency=2)

    run = await batches.start_all(access, project_id, definition_id)
    page = await batches.list(access, project_id, definition_id, limit=1)

    assert run.status is BatchRunStatus.partial
    assert len(run.records) == 5
    assert [record.error for record in run.records if record.error] == ["load 4 failed"]
    assert gateway.maximum_active <= 2
    assert run.definition_snapshot["recordIds"] == [
        record.dataset_record_id for record in run.records
    ]
    assert page.items == (run,)
    assert page.next_offset is None


@pytest.mark.asyncio
async def test_run_inspection_pages_filters_and_orders_persisted_runs() -> None:
    gateway = Gateway()
    access, project_id, batches, definition_id = await create_module(gateway)
    first = await batches.start_all(access, project_id, definition_id)
    second = await batches.start_all(access, project_id, definition_id)

    newest = await batches.list(access, project_id, definition_id, limit=1)
    oldest = await batches.list(
        access,
        project_id,
        definition_id,
        order=BatchRunOrder.oldest,
        limit=1,
    )
    failed = await batches.list(access, project_id, definition_id, status=BatchRunStatus.failed)

    assert newest.items == (second,)
    assert newest.next_offset == 1
    assert oldest.items == (first,)
    assert failed.items == ()


@pytest.mark.asyncio
async def test_result_set_inspection_pages_records_without_losing_the_run_snapshot() -> None:
    gateway = Gateway()
    access, project_id, batches, definition_id = await create_module(gateway)
    run = await batches.start_all(access, project_id, definition_id)

    first_page = await batches.inspect_results(access, project_id, run.id, limit=2)
    second_page = await batches.inspect_results(access, project_id, run.id, limit=2, offset=2)

    assert [record.input for record in first_page.items] == [{"load": 1}, {"load": 2}]
    assert first_page.next_offset == 2
    assert [record.input for record in second_page.items] == [{"load": 3}, {"load": 4}]
    assert second_page.next_offset == 4


@pytest.mark.asyncio
async def test_result_set_filters_then_sorts_before_pagination() -> None:
    access, project_id, batches, definition_id = await create_module(Gateway())
    run = await batches.start_all(access, project_id, definition_id)

    page = await batches.inspect_results(
        access,
        project_id,
        run.id,
        limit=2,
        filter_path="/structuredOutput/result",
        minimum=4,
        maximum=10,
        sort_path="/structuredOutput/result",
        descending=True,
    )

    assert [record.structured_output for record in page.items] == [
        {"result": 10},
        {"result": 8},
    ]
    assert page.next_offset == 2


@pytest.mark.asyncio
async def test_result_set_equality_and_numeric_summary_use_all_matching_records() -> None:
    access, project_id, batches, definition_id = await create_module(Gateway({4}))
    run = await batches.start_all(access, project_id, definition_id)

    page = await batches.inspect_results(
        access,
        project_id,
        run.id,
        limit=1,
        filter_path="/input/load",
        minimum=2,
        aggregate_path="/structuredOutput/result",
    )
    equal = await batches.inspect_results(
        access,
        project_id,
        run.id,
        filter_path="/input/load",
        equals=3,
    )

    assert page.summary.total_count == 4
    assert page.summary.succeeded_count == 3
    assert page.summary.failed_count == 1
    assert page.summary.numeric_count == 3
    assert page.summary.numeric_sum == 20
    assert page.summary.numeric_min == 4
    assert page.summary.numeric_max == 10
    assert page.summary.numeric_average == pytest.approx(20 / 3)
    assert [record.input for record in equal.items] == [{"load": 3}]


@pytest.mark.asyncio
async def test_result_set_http_query_returns_a_filtered_page_and_summary() -> None:
    access, project_id, batches, definition_id = await create_module(Gateway())
    run = await batches.start_all(access, project_id, definition_id)
    app = FastAPI()
    app.include_router(
        create_batch_execution_router(
            create_identity_module(Settings(environment="test", fixed_identity_subject="sam")),
            batches,
        ),
        prefix="/api",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        run_response = await client.get(f"/api/projects/{project_id}/batch-runs/{run.id}")
        response = await client.get(
            f"/api/projects/{project_id}/batch-runs/{run.id}/results",
            params={
                "filter_path": "/input/load",
                "minimum": 2,
                "limit": 1,
                "sort_path": "/structuredOutput/result",
                "descending": "true",
                "aggregate_path": "/structuredOutput/result",
            },
        )

    assert response.status_code == 200
    assert run_response.status_code == 200
    assert "records" not in run_response.json()
    assert run_response.json()["recordCount"] == 5
    assert run_response.json()["succeededCount"] == 5
    assert run_response.json()["initiatorSubject"] == "sam"
    assert run_response.json()["initiation"] == {
        "kind": "directUser",
        "approval": "notRequired",
        "threadId": None,
        "agentRunId": None,
        "toolCallId": None,
    }
    assert response.json()["items"][0]["structuredOutput"] == {"result": 10}
    assert response.json()["nextOffset"] == 1
    assert response.json()["summary"]["numericSum"] == 28


@pytest.mark.asyncio
async def test_repeated_idempotency_key_returns_the_original_run_without_reexecution() -> None:
    gateway = Gateway()
    access, project_id, batches, definition_id = await create_module(gateway)

    first = await batches.start_all(access, project_id, definition_id, "retry-123")
    repeated = await batches.start_all(access, project_id, definition_id, "retry-123")

    assert repeated == first
    assert len(gateway.calls) == 5


@pytest.mark.asyncio
async def test_approved_agent_batch_replay_retains_one_run_and_its_initiation() -> None:
    access, project_id, batches, definition_id = await create_module(Gateway())
    initiation = BatchInitiation(
        kind="agentRun",
        approval="approved",
        thread_id="thread-1",
        agent_run_id="agent-run-1",
        tool_call_id="call-1",
    )

    first = await batches.submit_all(
        access, project_id, definition_id, "agent-batch-call-1", initiation=initiation
    )
    replayed = await batches.submit_all(
        access, project_id, definition_id, "agent-batch-call-1", initiation=initiation
    )

    assert replayed.id == first.id
    assert first.initiation == {
        "kind": "agentRun",
        "approval": "approved",
        "threadId": "thread-1",
        "agentRunId": "agent-run-1",
        "toolCallId": "call-1",
    }
    assert (await batches.list(access, project_id)).items == (first,)


@pytest.mark.asyncio
async def test_enqueuing_the_same_batch_run_twice_executes_it_once() -> None:
    gateway = Gateway()
    access, project_id, batches, definition_id = await create_module(gateway)
    queued = await batches.submit_all(access, project_id, definition_id)

    first = await batches.enqueue(access, project_id, queued.id)
    second = await batches.enqueue(access, project_id, queued.id)
    completed = await first

    assert first is second
    assert completed.status is BatchRunStatus.succeeded
    assert gateway.calls == [1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_a_user_can_archive_a_completed_batch_run_without_losing_its_result_set() -> None:
    gateway = Gateway()
    access, project_id, batches, definition_id = await create_module(gateway)
    run = await batches.start_all(access, project_id, definition_id)

    assert run.archived_at is None
    archived = await batches.archive(access, project_id, run.id)

    assert (await batches.list(access, project_id)).items == ()
    assert archived.archived_at is not None
    assert (await batches.load(access, project_id, run.id)) == archived
    assert [record.structured_output for record in archived.records] == [
        {"result": 2},
        {"result": 4},
        {"result": 6},
        {"result": 8},
        {"result": 10},
    ]


@pytest.mark.asyncio
async def test_restart_reconciliation_fails_non_terminal_batch_runs() -> None:
    gateway = Gateway()
    access, project_id, batches, definition_id = await create_module(gateway)
    now = datetime.now(UTC)
    await batches._store.create_or_load(
        BatchRun("queued-run", project_id, definition_id, BatchRunStatus.queued, {}, (), now, now)
    )

    assert await batches.reconcile_non_terminal() == 1
    assert (await batches.load(access, project_id, "queued-run")).status is BatchRunStatus.failed


@pytest.mark.asyncio
async def test_captured_run_can_be_reclaimed_and_completed_after_restart() -> None:
    gateway = Gateway()
    access, project_id, batches, definition_id = await create_module(gateway)
    queued = await batches.submit_all(access, project_id, definition_id)

    recovered = await batches.recover()
    completed = await recovered[0]

    assert len(recovered) == 1
    assert queued.initiator_subject == "sam"
    assert [record.input for record in queued.records] == [
        {"load": 1},
        {"load": 2},
        {"load": 3},
        {"load": 4},
        {"load": 5},
    ]
    assert completed.status is BatchRunStatus.succeeded
