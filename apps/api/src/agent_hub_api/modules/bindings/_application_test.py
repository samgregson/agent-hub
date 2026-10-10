from collections.abc import Mapping

import pytest

from agent_hub_api.modules.bindings import (
    BindingModule,
    BindingUnavailable,
    MemoryBindingStore,
)
from agent_hub_api.modules.datasets import DatasetModule, DatasetRecordInput, MemoryDatasetStore
from agent_hub_api.modules.project_files import create_memory_project_files
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module


class TemplateSchema:
    async def input_schema(self, *_: object) -> Mapping[str, object]:
        return {
            "type": "object",
            "required": ["template", "value"],
            "properties": {"template": {"type": "string"}, "value": {"type": "number"}},
        }


@pytest.mark.asyncio
async def test_binding_captures_exact_file_and_rejects_stale_or_foreign_source() -> None:
    projects = create_memory_project_module()
    access = ProjectAccess(subject="sam")
    other = ProjectAccess(subject="other")
    project = await projects.create(access, "One")
    foreign = await projects.create(other, "Two")
    files = create_memory_project_files(projects)
    datasets = DatasetModule(projects, MemoryDatasetStore(), TemplateSchema())
    data = await datasets.create_dataset(
        access, project.id, "Values", [DatasetRecordInput({"value": 2})]
    )
    definition = await datasets.create_definition(
        access,
        project.id,
        data.id,
        "Render",
        "fixture",
        "render",
        {"value": "/value"},
        file_argument="template",
    )
    file = await files.write(project.id, "/template.txt", "value = {{value}}")
    bindings = BindingModule(projects, datasets, files, MemoryBindingStore())
    binding = await bindings.bind_file(
        access, project.id, definition.id, "/template.txt", file.version
    )
    captured = await bindings.capture(access, project.id, definition)
    assert captured is not None
    assert captured.binding_id == binding.id
    assert captured.content == "value = {{value}}"
    assert captured.version == file.version
    assert len(captured.sha256) == 64

    await files.write(project.id, "/template.txt", "changed")
    with pytest.raises(BindingUnavailable, match="changed"):
        await bindings.capture(access, project.id, definition)
    with pytest.raises(BindingUnavailable, match="version"):
        await bindings.rebind_file(
            access,
            project.id,
            definition.id,
            "/template.txt",
            2,
            expected_binding_version=0,
        )
    rebound = await bindings.rebind_file(
        access,
        project.id,
        definition.id,
        "/template.txt",
        2,
        expected_binding_version=binding.version,
    )
    assert rebound.version == 2
    refreshed = await bindings.capture(access, project.id, definition)
    assert refreshed is not None
    assert refreshed.content == "changed"
    with pytest.raises(BindingUnavailable):
        await bindings.bind_file(other, project.id, definition.id, "/template.txt", 2)
    with pytest.raises(BindingUnavailable):
        await bindings.bind_file(access, foreign.id, definition.id, "/template.txt", 2)
