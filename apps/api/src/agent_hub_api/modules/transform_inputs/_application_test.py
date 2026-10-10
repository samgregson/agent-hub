from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from agent_hub_api.modules.artifacts import (
    ArtifactMutationAccess,
    create_memory_artifact_module,
)
from agent_hub_api.modules.batch_execution import (
    BatchExecutionModule,
    BatchRun,
    BatchRunStatus,
    MemoryBatchRunStore,
    ResultRecord,
)
from agent_hub_api.modules.datasets import DatasetModule, DatasetRecordInput, MemoryDatasetStore
from agent_hub_api.modules.identity import create_identity_module
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module
from agent_hub_api.modules.transform_inputs import (
    ArtifactSelection,
    ResultSetSelection,
    TransformDatasetMode,
    TransformInputModule,
    TransformInputValidationError,
    create_transform_input_router,
)
from agent_hub_api.modules.transforms import (
    MemoryTransformRunStore,
    MemoryTransformStore,
    TransformModule,
    TransformRun,
    TransformRuntimeIdentity,
)
from agent_hub_api.settings import Settings


@pytest.mark.asyncio
async def test_dataset_wide_plan_does_not_truncate_at_selection_limit() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="sam")
    project = await projects.create(owner, "Whole Dataset")
    datasets = DatasetModule(projects, MemoryDatasetStore(), cast(Any, None))
    dataset = await datasets.create_dataset(
        owner,
        project.id,
        "Small values",
        [DatasetRecordInput({"n": value}) for value in range(101)],
    )

    class Runner:
        async def identity(self) -> TransformRuntimeIdentity:
            return TransformRuntimeIdentity("deno:test;pyodide:test", "a" * 64)

        async def execute(
            self, _source: str, _inputs: dict[str, object], _parameters: dict[str, object]
        ) -> tuple[object, str]:
            return {}, "deno:test;pyodide:test"

    transforms = TransformModule(
        projects, MemoryTransformStore(), Runner(), MemoryTransformRunStore(), datasets
    )
    definition = await transforms.define(
        owner,
        project.id,
        "Count",
        "def transform(inputs, parameters):\n    return {}\n",
        {"values": "/selection/values"},
        {"type": "object"},
    )
    inputs = TransformInputModule(cast(Any, None), transforms, cast(Any, None), datasets)

    plan = await inputs.plan_dataset_run(
        owner, project.id, definition.id, dataset.id, TransformDatasetMode.dataset
    )

    assert plan.snapshot()["invocationCount"] == 1
    assert len(plan.record_ids) == 101


@pytest.mark.asyncio
async def test_dataset_transform_plan_and_start_expose_two_modes() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="sam")
    project = await projects.create(owner, "Dataset Transform")
    datasets = DatasetModule(projects, MemoryDatasetStore(), cast(Any, None))
    dataset = await datasets.create_dataset(
        owner,
        project.id,
        "Loads",
        [DatasetRecordInput({"load": 2}), DatasetRecordInput({"load": 3})],
    )

    class Runner:
        async def identity(self) -> TransformRuntimeIdentity:
            return TransformRuntimeIdentity("deno:test;pyodide:test", "a" * 64)

        async def execute(
            self, _source: str, inputs: dict[str, object], _parameters: dict[str, object]
        ) -> tuple[object, str]:
            if "load" in inputs:
                return {
                    "result": cast(int, inputs["load"]) * cast(int, _parameters["factor"])
                }, "deno:test;pyodide:test"
            values = cast(list[dict[str, object]], inputs["values"])
            return (
                {"total": sum(cast(int, row["load"]) for row in values)},
                "deno:test;pyodide:test",
            )

    transforms = TransformModule(
        projects, MemoryTransformStore(), Runner(), MemoryTransformRunStore(), datasets
    )
    transform = await transforms.define(
        owner,
        project.id,
        "Sum",
        "def transform(inputs, parameters):\n    return {}\n",
        {"values": "/selection/values"},
        {"type": "object"},
    )
    batches = BatchExecutionModule(
        projects, datasets, cast(Any, None), MemoryBatchRunStore(), transforms=transforms
    )
    artifacts = cast(Any, None)
    inputs = TransformInputModule(batches, transforms, artifacts, datasets)

    plan = await inputs.plan_dataset_run(
        owner, project.id, transform.id, dataset.id, TransformDatasetMode.dataset
    )
    run = await inputs.start_dataset_run(
        owner,
        project.id,
        transform.id,
        dataset.id,
        TransformDatasetMode.dataset,
        plan.dataset_version,
        plan.transform_revision,
    )

    assert plan.snapshot()["invocationCount"] == 1
    assert plan.snapshot()["recordIds"] == [row.id for row in dataset.records]
    assert isinstance(run, TransformRun)
    assert run.output == {"total": 5}
    selection = cast(Mapping[str, object], run.definition_snapshot["selection"])
    assert selection["datasetVersion"] == dataset.version

    per_record = await transforms.define(
        owner,
        project.id,
        "Double",
        "def transform(inputs, parameters):\n    return {}\n",
        {"load": "/load"},
        {"type": "object"},
    )
    record_plan = await inputs.plan_dataset_run(
        owner,
        project.id,
        per_record.id,
        dataset.id,
        TransformDatasetMode.per_record,
        {"factor": 3},
    )
    queued = await inputs.start_dataset_run(
        owner,
        project.id,
        per_record.id,
        dataset.id,
        TransformDatasetMode.per_record,
        record_plan.dataset_version,
        record_plan.transform_revision,
        {"factor": 3},
        idempotency_key="call-1",
    )
    completed = await (await batches.enqueue(owner, project.id, queued.id))

    assert record_plan.snapshot()["invocationCount"] == 2
    assert record_plan.snapshot()["outputKind"] == "batchResultSet"
    assert completed.status == BatchRunStatus.succeeded
    assert [record.structured_output for record in completed.records] == [
        {"result": 6},
        {"result": 9},
    ]
    await datasets.update_dataset(
        owner,
        project.id,
        dataset.id,
        "Changed",
        [DatasetRecordInput(record.value, id=record.id) for record in dataset.records],
        expected_version=dataset.version,
    )
    with pytest.raises(TransformInputValidationError, match="changed"):
        await inputs.start_dataset_run(
            owner,
            project.id,
            per_record.id,
            dataset.id,
            TransformDatasetMode.per_record,
            record_plan.dataset_version,
            record_plan.transform_revision,
            {"factor": 3},
            idempotency_key="call-2",
        )


@pytest.mark.asyncio
async def test_dataset_transform_http_plan_and_start_share_the_mode_contract() -> None:
    class Inputs:
        async def plan_dataset_run(self, *_: object) -> object:
            return SimpleNamespace(
                snapshot=lambda: {
                    "datasetVersion": 2,
                    "transformRevision": 3,
                    "recordIds": ["record-1", "record-2"],
                    "mode": "perRecord",
                    "invocationCount": 2,
                    "outputKind": "batchResultSet",
                }
            )

        async def start_dataset_run(self, *args: object, **__: object) -> object:
            assert args[4] == TransformDatasetMode.per_record
            assert args[5:7] == (2, 3)
            return SimpleNamespace(id="batch-1", status="queued")

    app = FastAPI()
    app.include_router(
        create_transform_input_router(
            create_identity_module(Settings(environment="test", fixed_identity_subject="sam")),
            cast(Any, Inputs()),
        )
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        base = "/projects/project-1/transforms/transform-1/dataset-runs"
        planned = await client.post(
            f"{base}/plan", json={"datasetId": "dataset-1", "mode": "perRecord"}
        )
        started = await client.post(
            base,
            json={
                "datasetId": "dataset-1",
                "mode": "perRecord",
                "expectedDatasetVersion": 2,
                "expectedTransformRevision": 3,
            },
        )
    assert planned.status_code == 200
    assert planned.json()["invocationCount"] == 2
    assert started.status_code == 201
    assert started.json() == {"id": "batch-1", "status": "queued", "outputKind": "batchResultSet"}


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
        definition_snapshot={
            "name": "Source calculation",
            "datasetRecords": [
                {"id": "row-1", "sourceKey": "beam-A"},
                {"id": "row-2", "sourceKey": "beam-B"},
                {"id": "row-3", "sourceKey": "beam-C"},
            ],
        },
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
            assert inputs == {
                "items": [5],
                "rows": [
                    {
                        "resultRecordId": "batch-run-1:row-1",
                        "datasetRecordId": "row-1",
                        "sourceKey": "beam-A",
                        "position": 0,
                        "input": {"beam": "A"},
                        "value": 5,
                    }
                ],
            }
            return {"total": 5}, "deno:test;pyodide:test"

    transforms = TransformModule(
        projects, MemoryTransformStore(), Runner(), MemoryTransformRunStore()
    )
    target = await transforms.define(
        owner,
        project.id,
        "Aggregate",
        "def transform(inputs, parameters):\n    return {}\n",
        {"items": "/selection/values", "rows": "/selection/rows"},
        {"type": "object"},
    )
    inputs = TransformInputModule(
        cast(BatchExecutionModule, Batches()), transforms, create_memory_artifact_module(projects)
    )
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
        {
            "resultRecordId": "batch-run-1:row-1",
            "datasetRecordId": "row-1",
            "sourceKey": "beam-A",
            "position": 0,
            "input": {"beam": "A"},
            "value": 5,
        }
    ]
    assert plan.snapshot()["failedCount"] == 1

    run = await inputs.start_result_set_run(owner, project.id, target.id, choice, {})
    assert run.status == "succeeded"
    assert run.inputs == {
        "items": [5],
        "rows": [
            {
                "resultRecordId": "batch-run-1:row-1",
                "datasetRecordId": "row-1",
                "sourceKey": "beam-A",
                "position": 0,
                "input": {"beam": "A"},
                "value": 5,
            }
        ],
    }
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
    assert reloaded.inputs == run.inputs

    source = replace(source, status=BatchRunStatus.running)
    with pytest.raises(TransformInputValidationError, match="not complete"):
        await inputs.plan_result_set_selection(owner, project.id, target.id, choice)


@pytest.mark.asyncio
async def test_retained_mcp_output_feeds_one_transform_with_captured_artifact_lineage() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="sam")
    project = await projects.create(owner, "MCP output input")
    artifacts = create_memory_artifact_module(projects)
    snapshot = await artifacts.create_tool_result_snapshot(
        ArtifactMutationAccess("sam", "thread-1", "agent-run-1"),
        project.id,
        plugin_id="fixture",
        plugin_version="1",
        tool_name="measure",
        arguments={"sample": "A"},
        structured_content={
            "measurements": [
                {"name": "A", "score": 9},
                {"name": "B", "score": 4},
                {"name": "C", "score": 7},
            ]
        },
    )

    class Runner:
        async def identity(self) -> TransformRuntimeIdentity:
            return TransformRuntimeIdentity("deno:test;pyodide:test", "a" * 64)

        async def execute(
            self, source: str, inputs: dict[str, object], parameters: dict[str, object]
        ) -> tuple[object, str]:
            assert inputs == {"items": [{"name": "B", "score": 4}, {"name": "C", "score": 7}]}
            return {"count": 2}, "deno:test;pyodide:test"

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
    inputs = TransformInputModule(cast(BatchExecutionModule, object()), transforms, artifacts)
    choice = ArtifactSelection(
        artifact_id=snapshot.artifact.id.root,
        expected_artifact_version=1,
        output_path="/measurements",
        expected_definition_revision=target.revision,
        sort_path="/score",
        limit=2,
    )
    plan = await inputs.plan_artifact_selection(owner, project.id, target.id, choice)
    assert plan.selected_count == 2
    assert plan.snapshot() == {
        "sourceKind": "mcpToolResult",
        "artifactId": snapshot.artifact.id.root,
        "artifactVersion": 1,
        "pluginId": "fixture",
        "toolName": "measure",
        "outputPath": "/measurements",
        "selectedValues": [
            {"position": 1, "value": {"name": "B", "score": 4}},
            {"position": 2, "value": {"name": "C", "score": 7}},
        ],
        "rule": {
            "filterPath": None,
            "equals": None,
            "sortPath": "/score",
            "descending": False,
            "limit": 2,
        },
        "selectedCount": 2,
    }
    run = await inputs.start_artifact_run(owner, project.id, target.id, choice, {})
    assert run.status == "succeeded"
    assert run.inputs == {"items": [{"name": "B", "score": 4}, {"name": "C", "score": 7}]}
    assert run.definition_snapshot["selection"] == plan.snapshot()
    with pytest.raises(TransformInputValidationError, match="changed"):
        await inputs.plan_artifact_selection(
            owner, project.id, target.id, replace(choice, expected_artifact_version=2)
        )
