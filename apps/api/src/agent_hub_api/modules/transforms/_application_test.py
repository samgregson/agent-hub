import pytest

from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module
from agent_hub_api.modules.transforms import (
    MemoryTransformStore,
    TransformModule,
    TransformNotFound,
    TransformValidationError,
)


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
