from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

import pytest

from agent_hub_api.modules.artifacts import (
    ArtifactMutationAccess,
    create_memory_artifact_module,
)
from agent_hub_api.modules.batch_execution import (
    BatchExecutionModule,
    BatchRun,
    BatchRunStatus,
    ResultRecord,
)
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module
from agent_hub_api.modules.transform_inputs import (
    ArtifactSelection,
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
