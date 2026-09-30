import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime

import pytest

from agent_hub_api.modules.batch_execution import (
    BatchExecutionModule,
    BatchRun,
    BatchRunOrder,
    BatchRunStatus,
    MemoryBatchRunStore,
)
from agent_hub_api.modules.datasets import (
    DatasetModule,
    DatasetRecordInput,
    MemoryDatasetStore,
)
from agent_hub_api.modules.plugin_gateway import PluginToolResult
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module


class ToolSchemas:
    async def input_schema(self, *_: object) -> Mapping[str, object]:
        return {
            "type": "object",
            "required": ["load"],
            "properties": {"load": {"type": "number"}},
        }


class Gateway:
    def __init__(self, fail_loads: set[int] | None = None) -> None:
        self.calls: list[int] = []
        self.fail_loads = fail_loads or set()
        self.active = 0
        self.maximum_active = 0

    async def batch_call(
        self, _access: ProjectAccess, _project_id: str, _plugin_id: str, _tool_name: str,
        arguments: Mapping[str, object],
    ) -> PluginToolResult:
        load = int(arguments["load"])
        self.calls.append(load)
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        await asyncio.sleep(0)
        self.active -= 1
        if load in self.fail_loads:
            raise RuntimeError(f"load {load} failed")
        return PluginToolResult((), {"result": load * 2})


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
            projects, datasets, gateway, MemoryBatchRunStore(), max_concurrency=max_concurrency
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
    failed = await batches.list(
        access, project_id, definition_id, status=BatchRunStatus.failed
    )

    assert newest.items == (second,)
    assert newest.next_offset == 1
    assert oldest.items == (first,)
    assert failed.items == ()


@pytest.mark.asyncio
async def test_repeated_idempotency_key_returns_the_original_run_without_reexecution() -> None:
    gateway = Gateway()
    access, project_id, batches, definition_id = await create_module(gateway)

    first = await batches.start_all(access, project_id, definition_id, "retry-123")
    repeated = await batches.start_all(access, project_id, definition_id, "retry-123")

    assert repeated == first
    assert len(gateway.calls) == 5


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
    await batches._store.create_or_load(  # type: ignore[attr-defined]
        BatchRun(
            "queued-run", project_id, definition_id, BatchRunStatus.queued, {}, (), now, now
        )
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
