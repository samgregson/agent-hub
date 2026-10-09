from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

import pytest

from agent_hub_api.modules.batch_execution import (
    BatchExecutionModule,
    BatchRun,
    BatchRunStatus,
    ResultRecord,
)
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module
from agent_hub_api.modules.transform_inputs import (
    ResultSetSelection,
    TransformInputModule,
    TransformInputValidationError,
)
from agent_hub_api.modules.transforms import (
    MemoryTransformRunStore,
    MemoryTransformStore,
    TransformModule,
    TransformRuntimeIdentity,
)


@pytest.mark.asyncio
async def test_result_set_values_feed_one_transform_with_captured_row_lineage() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="sam")
    project = await projects.create(owner, "Result Set input")
    now = datetime.now(UTC)
    source = BatchRun(
        id="batch-run-1",
        project_id=project.id,
        definition_id="batch-definition-1",
        status=BatchRunStatus.partial,
        definition_snapshot={"name": "Source calculation"},
        records=(
            ResultRecord("row-1", {"beam": "A"}, {"score": 5}),
            ResultRecord("row-2", {"beam": "B"}, error="failed"),
            ResultRecord("row-3", {"beam": "C"}, {"score": 9}),
        ),
        created_at=now,
        updated_at=now,
    )

    class Batches:
        async def load(self, access: ProjectAccess, project_id: str, run_id: str) -> BatchRun:
            assert access == owner
            assert (project_id, run_id) == (project.id, source.id)
            return source

    class Runner:
        async def identity(self) -> TransformRuntimeIdentity:
            return TransformRuntimeIdentity("deno:test;pyodide:test", "a" * 64)

        async def execute(
            self, source: str, inputs: dict[str, object], parameters: dict[str, object]
        ) -> tuple[object, str]:
            assert inputs == {"items": [5]}
            return {"total": 5}, "deno:test;pyodide:test"

    transforms = TransformModule(
        projects, MemoryTransformStore(), Runner(), MemoryTransformRunStore()
    )
    target = await transforms.define(
        owner,
        project.id,
        "Aggregate",
        "def transform(inputs, parameters):\n    return {}\n",
        {"items": "/selection/values"},
        {"type": "object"},
    )
    inputs = TransformInputModule(cast(BatchExecutionModule, Batches()), transforms)
    choice = ResultSetSelection(
        source_run_id=source.id,
        output_path="/score",
        expected_definition_revision=target.revision,
        sort_path=None,
        limit=1,
    )
    plan = await inputs.plan_result_set_selection(owner, project.id, target.id, choice)
    assert plan.selected_count == 1
    assert plan.invocation_count == 1
    assert plan.snapshot()["selectedRecords"] == [
        {"datasetRecordId": "row-1", "position": 0, "input": {"beam": "A"}, "value": 5}
    ]
    assert plan.snapshot()["failedCount"] == 1

    run = await inputs.start_result_set_run(owner, project.id, target.id, choice, {})
    assert run.status == "succeeded"
    assert run.inputs == {"items": [5]}
    snapshot = run.definition_snapshot["selection"]
    assert isinstance(snapshot, Mapping)
    assert snapshot["sourceKind"] == "resultSet"
    assert snapshot["batchRunId"] == source.id
    assert snapshot["selectedRecords"] == plan.snapshot()["selectedRecords"]
    source_output = source.records[0].structured_output
    assert isinstance(source_output, dict)
    source_output["score"] = 999
    reloaded = await transforms.load_run(owner, project.id, run.id)
    assert reloaded.definition_snapshot["selection"] == snapshot
    assert reloaded.inputs == {"items": [5]}

    source = replace(source, status=BatchRunStatus.running)
    with pytest.raises(TransformInputValidationError, match="not complete"):
        await inputs.plan_result_set_selection(owner, project.id, target.id, choice)
