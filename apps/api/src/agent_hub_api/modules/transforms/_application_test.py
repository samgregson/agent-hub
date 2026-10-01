import pytest

from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module
from agent_hub_api.modules.transforms import (
    MemoryTransformStore,
    TransformModule,
    TransformNotFound,
    TransformRuntimeIdentity,
    TransformValidationError,
)


class _PinnedRunner:
    async def identity(self) -> TransformRuntimeIdentity:
        return TransformRuntimeIdentity("deno:2.9.7;pyodide:314.0.7", "a" * 64)


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
    with pytest.raises(TransformNotFound):
        await transforms.load_run(ProjectAccess(subject="alex"), project.id, run.id)


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
