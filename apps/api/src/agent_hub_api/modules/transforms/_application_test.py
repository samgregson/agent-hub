from collections.abc import Mapping

import pytest

from agent_hub_api.modules.artifacts import (
    ArtifactAccess,
    ArtifactUserActionAccess,
    create_memory_artifact_module,
)
from agent_hub_api.modules.datasets import (
    DatasetModule,
    DatasetRecordInput,
    MemoryDatasetStore,
)
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module
from agent_hub_api.modules.transforms import (
    DatasetSelection,
    MemoryTransformStore,
    TransformInitiation,
    TransformModule,
    TransformNotFound,
    TransformRuntimeIdentity,
    TransformValidationError,
)


@pytest.mark.asyncio
async def test_dataset_selection_is_reviewed_and_captured_before_one_transform_run() -> None:
    from agent_hub_api.modules.transforms import MemoryTransformRunStore

    projects = create_memory_project_module()
    owner = ProjectAccess(subject="sam")
    project = await projects.create(owner, "Selected values")
    datasets = DatasetModule(projects, MemoryDatasetStore(), _NoToolSchema())
    data = await datasets.create_dataset(
        owner,
        project.id,
        "Inputs",
        [
            DatasetRecordInput({"group": "A", "score": 1}),
            DatasetRecordInput({"group": "B", "score": 9}),
            DatasetRecordInput({"group": "A", "score": 3}),
        ],
    )

    class Runner(_PinnedRunner):
        async def execute(
            self, source: str, inputs: dict[str, object], parameters: dict[str, object]
        ) -> tuple[object, str]:
            assert inputs["items"] == [
                {"group": "A", "score": 3},
                {"group": "A", "score": 1},
            ]
            return {"count": 2}, "deno:2.9.7;pyodide:314.0.7"

    transforms = TransformModule(
        projects, MemoryTransformStore(), Runner(), MemoryTransformRunStore(), datasets
    )
    definition = await transforms.define(
        owner,
        project.id,
        "Summarize selection",
        "def transform(inputs, parameters):\n    return {'count': len(inputs['items'])}\n",
        {"items": "/selection/values"},
        {"type": "object", "required": ["count"]},
    )
    choice = DatasetSelection(
        dataset_id=data.id,
        expected_version=data.version,
        expected_definition_revision=definition.revision,
        filter_path="/group",
        equals="A",
        sort_path="/score",
        descending=True,
        limit=2,
    )
    plan = await transforms.plan_dataset_selection(owner, project.id, definition.id, choice)
    assert plan.selected_count == 2
    assert plan.invocation_count == 1
    assert [item.id for item in plan.records] == [data.records[2].id, data.records[0].id]

    run = await transforms.start_selected_run(
        owner, project.id, definition.id, choice, {}
    )
    assert run.status == "succeeded"
    assert run.output == {"count": 2}
    snapshot = run.definition_snapshot["selection"]
    assert isinstance(snapshot, Mapping)
    assert snapshot["datasetVersion"] == data.version
    assert snapshot["recordIds"] == [
        data.records[2].id,
        data.records[0].id,
    ]
    await datasets.update_dataset(
        owner, project.id, data.id, "Changed",
        [DatasetRecordInput({"group": "A", "score": 100}, id=data.records[0].id)],
        expected_version=data.version,
    )
    assert (await transforms.load_run(owner, project.id, run.id)).output == {"count": 2}
    with pytest.raises(TransformValidationError, match="version"):
        await transforms.start_selected_run(owner, project.id, definition.id, choice, {})
    assert len(await datasets.list_datasets(owner, project.id)) == 1


class _NoToolSchema:
    async def input_schema(self, *_: object) -> dict[str, object]:
        return {"type": "object"}


class _PinnedRunner:
    async def identity(self) -> TransformRuntimeIdentity:
        return TransformRuntimeIdentity("deno:2.9.7;pyodide:314.0.7", "a" * 64)


@pytest.mark.asyncio
async def test_successful_run_can_be_explicitly_saved_as_project_artifact() -> None:
    from agent_hub_api.modules.transforms import MemoryTransformRunStore

    projects = create_memory_project_module()
    owner = ProjectAccess(subject="sam")
    project = await projects.create(owner, "Bridge")

    class Runner(_PinnedRunner):
        async def execute(
            self, source: str, inputs: dict[str, object], parameters: dict[str, object]
        ) -> tuple[object, str]:
            return {"value": 6}, "deno:2.9.7;pyodide:314.0.7"

    artifacts = create_memory_artifact_module(projects)
    transforms = TransformModule(
        projects, MemoryTransformStore(), Runner(), MemoryTransformRunStore(),
        artifacts=artifacts,
    )
    definition = await transforms.define(
        owner, project.id, "Double", "def transform(inputs, parameters):\n    return {}\n",
        {"load": "/load"}, {"type": "object"},
    )
    run = await transforms.start_run(owner, project.id, definition.id, {"load": 3}, {})
    assert await artifacts.discover(ArtifactAccess(subject="sam"), project.id) == ()

    document = await transforms.save_run_as_artifact(
        ArtifactUserActionAccess(subject="sam", user_action_id="save-1"),
        project.id, run.id, "Checked loads",
    )

    assert document.artifact.title == "Checked loads"
    assert document.payload["output"] == {"value": 6}
    assert document.payload["transformRunId"] == run.id
    assert document.payload["sourceHash"] == run.source_hash
    assert document.artifact.provenance.created_by.user_action_id is not None
    assert document.artifact.provenance.created_by.user_action_id.root == "save-1"
    assert (await artifacts.load(
        ArtifactAccess(subject="sam"), project.id, document.artifact.id.root
    )) == document


@pytest.mark.asyncio
async def test_failed_run_cannot_create_artifact_and_other_project_user_cannot_save() -> None:
    from agent_hub_api.modules.transforms import MemoryTransformRunStore

    projects = create_memory_project_module()
    owner = ProjectAccess(subject="sam")
    project = await projects.create(owner, "Bridge")

    class Runner(_PinnedRunner):
        async def execute(
            self, source: str, inputs: dict[str, object], parameters: dict[str, object]
        ) -> tuple[object, str]:
            return {"wrong": 1}, "deno:2.9.7;pyodide:314.0.7"

    artifacts = create_memory_artifact_module(projects)
    transforms = TransformModule(
        projects, MemoryTransformStore(), Runner(), MemoryTransformRunStore(),
        artifacts=artifacts,
    )
    definition = await transforms.define(
        owner, project.id, "Invalid", "def transform(inputs, parameters):\n    return {}\n",
        {"load": "/load"}, {"type": "object", "required": ["value"]},
    )
    run = await transforms.start_run(owner, project.id, definition.id, {"load": 3}, {})
    assert run.status == "failed"

    with pytest.raises(TransformValidationError, match="successful"):
        await transforms.save_run_as_artifact(
            ArtifactUserActionAccess(subject="sam", user_action_id="save-1"),
            project.id, run.id, "Wrong",
        )
    with pytest.raises(TransformNotFound):
        await transforms.save_run_as_artifact(
            ArtifactUserActionAccess(subject="alex", user_action_id="save-2"),
            project.id, run.id, "Wrong",
        )
    assert await artifacts.discover(ArtifactAccess(subject="sam"), project.id) == ()


@pytest.mark.asyncio
async def test_preview_resolves_selectors_and_validates_runner_output() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="sam")
    outsider = ProjectAccess(subject="alex")
    project = await projects.create(owner, "Bridge")

    class Runner(_PinnedRunner):
        async def execute(
            self, source: str, inputs: dict[str, object], parameters: dict[str, object]
        ) -> tuple[object, str]:
            assert "def transform" in source
            assert inputs == {"load": 3}
            assert parameters == {"factor": 2}
            return {"value": 6}, "deno:2.9.7;pyodide:314.0.7"

    transforms = TransformModule(projects, MemoryTransformStore(), Runner())
    definition = await transforms.define(
        owner, project.id, "Double", "def transform(inputs, parameters):\n    return {}\n",
        {"load": "/load~1value"},
        {"type": "object", "required": ["value"], "properties": {"value": {"type": "number"}}},
    )
    preview = await transforms.preview(
        owner, project.id, definition.id, {"load/value": 3}, {"factor": 2}
    )
    assert preview.output == {"value": 6}
    assert preview.runtime == "deno:2.9.7;pyodide:314.0.7"
    assert preview.source_hash == definition.source_hash
    with pytest.raises(TransformNotFound):
        await transforms.preview(outsider, project.id, definition.id, {"load/value": 3}, {})
    with pytest.raises(TransformValidationError, match="selector"):
        await transforms.preview(owner, project.id, definition.id, {}, {})


@pytest.mark.asyncio
async def test_preview_rejects_output_outside_declared_schema() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="sam")
    project = await projects.create(owner, "Bridge")

    class Runner(_PinnedRunner):
        async def execute(
            self, source: str, inputs: dict[str, object], parameters: dict[str, object]
        ) -> tuple[object, str]:
            return {"value": "wrong"}, "deno:2.9.7;pyodide:314.0.7"

    transforms = TransformModule(projects, MemoryTransformStore(), Runner())
    definition = await transforms.define(
        owner, project.id, "Double", "def transform(inputs, parameters):\n    return {}\n",
        {"load": "/load"},
        {"type": "object", "properties": {"value": {"type": "number"}}},
    )
    with pytest.raises(TransformValidationError, match="output schema"):
        await transforms.preview(owner, project.id, definition.id, {"load": 3}, {})


@pytest.mark.asyncio
async def test_run_retains_immutable_snapshots_after_definition_revision() -> None:
    from agent_hub_api.modules.transforms import MemoryTransformRunStore

    projects = create_memory_project_module()
    owner = ProjectAccess(subject="sam")
    project = await projects.create(owner, "Bridge")

    class Runner(_PinnedRunner):
        async def execute(
            self, source: str, inputs: dict[str, object], parameters: dict[str, object]
        ) -> tuple[object, str]:
            assert isinstance(inputs["load"], int)
            assert isinstance(parameters["factor"], int)
            return {"value": inputs["load"] * parameters["factor"]}, "deno:2.9.7;pyodide:314.0.7"

    transforms = TransformModule(
        projects, MemoryTransformStore(), Runner(), MemoryTransformRunStore()
    )
    definition = await transforms.define(
        owner, project.id, "Double",
        "def transform(inputs, parameters):\n    return {}\n",
        {"load": "/load"},
        {"type": "object", "required": ["value"]},
    )
    run = await transforms.start_run(
        owner, project.id, definition.id, {"load": 3}, {"factor": 2}
    )
    assert run.status == "succeeded"
    assert run.output == {"value": 6}
    assert run.initiator_subject == "sam"
    assert run.input_hash and run.output_manifest["sha256"]
    assert run.package_hash == definition.package_hash == "a" * 64
    assert run.runtime == definition.runtime == "deno:2.9.7;pyodide:314.0.7"
    assert run.definition_snapshot["source"] == definition.source
    await transforms.revise(
        owner, project.id, definition.id, "Triple",
        "def transform(inputs, parameters):\n    return {'value': 3}\n",
        {"load": "/load"}, {"type": "object"},
    )
    loaded = await transforms.load_run(owner, project.id, run.id)
    assert loaded == run
    page = await transforms.list_runs(owner, project.id, limit=1)
    assert page.items == (run,)
    assert page.next_offset is None
    second = await transforms.start_run(
        owner, project.id, definition.id, {"load": 3}, {"factor": 3}
    )
    first_page = await transforms.list_runs(owner, project.id, limit=1)
    assert first_page.items == (second,)
    assert first_page.next_offset == 1
    assert (await transforms.list_runs(owner, project.id, limit=1, offset=1)).items == (run,)
    with pytest.raises(TransformNotFound):
        await transforms.load_run(ProjectAccess(subject="alex"), project.id, run.id)
    with pytest.raises(TransformNotFound):
        await transforms.list_runs(ProjectAccess(subject="alex"), project.id)


@pytest.mark.asyncio
async def test_run_retains_agent_approval_context_and_enforced_runner_limits() -> None:
    from agent_hub_api.modules.transforms import MemoryTransformRunStore

    projects = create_memory_project_module()
    owner = ProjectAccess(subject="sam")
    project = await projects.create(owner, "Bridge")

    class Runner(_PinnedRunner):
        async def identity(self) -> TransformRuntimeIdentity:
            return TransformRuntimeIdentity(
                "deno:2.9.7;pyodide:314.0.7", "a" * 64,
                {"timeoutMs": 10_000, "maxInputBytes": 128_000, "maxOutputBytes": 128_000},
            )

        async def execute(
            self, source: str, inputs: dict[str, object], parameters: dict[str, object]
        ) -> tuple[object, str]:
            return {"value": 6}, "deno:2.9.7;pyodide:314.0.7"

    transforms = TransformModule(
        projects, MemoryTransformStore(), Runner(), MemoryTransformRunStore()
    )
    definition = await transforms.define(
        owner, project.id, "Double", "def transform(inputs, parameters):\n    return {}\n",
        {"load": "/load"}, {"type": "object"},
    )
    run = await transforms.start_run(
        owner, project.id, definition.id, {"load": 3}, {},
        initiation=TransformInitiation(
            kind="agentRun", approval="approved", thread_id="thread-1",
            agent_run_id="agent-run-1",
        ),
    )

    assert run.initiation == {
        "kind": "agentRun", "approval": "approved",
        "threadId": "thread-1", "agentRunId": "agent-run-1",
    }
    assert run.limits["timeoutMs"] == 10_000
    assert (await transforms.load_run(owner, project.id, run.id)) == run


@pytest.mark.asyncio
async def test_run_retains_failure_without_fabricating_output() -> None:
    from agent_hub_api.modules.transforms import (
        MemoryTransformRunStore,
        TransformExecutionError,
    )

    projects = create_memory_project_module()
    owner = ProjectAccess(subject="sam")
    project = await projects.create(owner, "Bridge")

    class Runner(_PinnedRunner):
        async def execute(
            self, source: str, inputs: dict[str, object], parameters: dict[str, object]
        ) -> tuple[object, str]:
            raise TransformExecutionError("timeout")

    transforms = TransformModule(
        projects, MemoryTransformStore(), Runner(), MemoryTransformRunStore()
    )
    definition = await transforms.define(
        owner, project.id, "Slow", "def transform(inputs, parameters):\n    return {}\n",
        {"load": "/load"}, {"type": "object"},
    )
    run = await transforms.start_run(owner, project.id, definition.id, {"load": 3}, {})
    assert run.status == "failed"
    assert run.error == "timeout"
    assert run.output is None
    assert run.output_manifest == {}
    assert run.package_hash == "a" * 64
    assert run.runtime == "deno:2.9.7;pyodide:314.0.7"
    assert await transforms.load_run(owner, project.id, run.id) == run


@pytest.mark.asyncio
async def test_successful_run_output_is_saved_as_dataset_only_on_explicit_command() -> None:
    from agent_hub_api.modules.transforms import MemoryTransformRunStore

    projects = create_memory_project_module()
    owner = ProjectAccess(subject="sam")
    project = await projects.create(owner, "Bridge")

    class ToolSchemas:
        async def input_schema(
            self, access: ProjectAccess, project_id: str, plugin_id: str, tool_name: str
        ) -> dict[str, object]:
            return {}

    class Runner(_PinnedRunner):
        async def execute(
            self, source: str, inputs: dict[str, object], parameters: dict[str, object]
        ) -> tuple[object, str]:
            return [{"value": 2}, {"value": 4}], "deno:2.9.7;pyodide:314.0.7"

    datasets = DatasetModule(projects, MemoryDatasetStore(), ToolSchemas())
    transforms = TransformModule(
        projects, MemoryTransformStore(), Runner(), MemoryTransformRunStore(), datasets
    )
    definition = await transforms.define(
        owner, project.id, "Values", "def transform(inputs, parameters):\n    return []\n",
        {"load": "/load"}, {"type": "array"},
    )
    run = await transforms.start_run(owner, project.id, definition.id, {"load": 3}, {})
    assert await datasets.list_datasets(owner, project.id) == ()
    dataset = await transforms.save_run_as_dataset(owner, project.id, run.id, "Values")
    assert [record.value for record in dataset.records] == [{"value": 2}, {"value": 4}]
    assert [record.source_key for record in dataset.records] == [
        f"transform-run:{run.id}:0", f"transform-run:{run.id}:1"
    ]
    assert (await transforms.load_run(owner, project.id, run.id)) == run


@pytest.mark.asyncio
async def test_definition_is_project_scoped_and_revisions_keep_identity() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="sam")
    other = ProjectAccess(subject="alex")
    project = await projects.create(owner, "Bridge")
    transforms = TransformModule(projects, MemoryTransformStore())

    definition = await transforms.define(
        owner,
        project.id,
        name="Double loads",
        source="def transform(inputs, parameters):\n    return {'value': inputs['loads'] * 2}\n",
        input_selectors={"loads": "/load"},
        output_schema={"type": "object", "required": ["value"]},
    )
    revised = await transforms.revise(
        owner,
        project.id,
        definition.id,
        name="Triple loads",
        source="def transform(inputs, parameters):\n    return {'value': inputs['loads'] * 3}\n",
        input_selectors={"loads": "/load"},
        output_schema={"type": "object", "required": ["value"]},
    )

    assert definition.source_hash != revised.source_hash
    assert revised.id == definition.id
    assert revised.revision == 2
    assert revised.runtime is None
    assert [item.id for item in await transforms.list(owner, project.id)] == [definition.id]
    with pytest.raises(TransformNotFound):
        await transforms.load(other, project.id, definition.id)

    await transforms.delete(owner, project.id, definition.id)
    with pytest.raises(TransformNotFound):
        await transforms.load(owner, project.id, definition.id)


@pytest.mark.asyncio
async def test_definition_rejects_invalid_contracts_before_storage() -> None:
    projects = create_memory_project_module()
    access = ProjectAccess(subject="sam")
    project = await projects.create(access, "Bridge")
    transforms = TransformModule(projects, MemoryTransformStore())

    with pytest.raises(TransformValidationError, match="source"):
        await transforms.define(access, project.id, "Bad", " ", {"load": "/load"}, {})
    with pytest.raises(TransformValidationError, match="selector"):
        await transforms.define(access, project.id, "Bad", "pass", {"load": "load"}, {})
    with pytest.raises(TransformValidationError, match="output schema"):
        await transforms.define(
            access, project.id, "Bad", "pass", {"load": "/load"}, {"type": "wat"}
        )
