from collections.abc import Mapping

import pytest

from agent_hub_api.modules.datasets import (
    DatasetModule,
    DatasetNotFound,
    DatasetRecordInput,
    DatasetValidationError,
    MemoryDatasetStore,
)
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module


class ToolSchemas:
    async def input_schema(self, *_: object) -> Mapping[str, object]:
        return {
            "type": "object",
            "required": ["length_m", "tip_load_kn"],
            "properties": {
                "length_m": {"type": "number"},
                "tip_load_kn": {"type": "number"},
            },
        }


async def create_module() -> tuple[ProjectAccess, str, DatasetModule]:
    projects = create_memory_project_module()
    access = ProjectAccess(subject="sam")
    project = await projects.create(access, "Bridge")
    return access, project.id, DatasetModule(projects, MemoryDatasetStore(), ToolSchemas())


@pytest.mark.asyncio
async def test_dataset_records_are_project_scoped_ordered_and_host_identified() -> None:
    access, project_id, datasets = await create_module()
    dataset = await datasets.create_dataset(
        access,
        project_id,
        "  Load cases  ",
        [
            DatasetRecordInput({"length": 1.5, "load": 12.5}, source_key="LC-1"),
            DatasetRecordInput({"length": 2, "load": 20}, source_key="LC-2"),
        ],
    )

    assert dataset.name == "Load cases"
    assert [record.position for record in dataset.records] == [0, 1]
    assert len({record.id for record in dataset.records}) == 2
    assert [record.source_key for record in dataset.records] == ["LC-1", "LC-2"]
    updated = await datasets.update_dataset(
        access,
        project_id,
        dataset.id,
        "Load cases",
        [
            DatasetRecordInput(
                {"length": 1.5, "load": 15}, source_key="LC-1", id=dataset.records[0].id
            )
        ],
    )
    assert updated.records[0].id == dataset.records[0].id


@pytest.mark.asyncio
async def test_dataset_rejects_non_json_objects_and_foreign_record_ids() -> None:
    access, project_id, datasets = await create_module()
    with pytest.raises(DatasetValidationError, match="JSON objects"):
        await datasets.create_dataset(
            access, project_id, "Bad", [DatasetRecordInput({"number": float("nan")})]
        )
    dataset = await datasets.create_dataset(
        access, project_id, "Good", [DatasetRecordInput({"number": 1})]
    )
    with pytest.raises(DatasetValidationError, match="issued by Agent Hub"):
        await datasets.update_dataset(
            access,
            project_id,
            dataset.id,
            "Good",
            [DatasetRecordInput({"number": 2}, id="not-a-host-id")],
        )


@pytest.mark.asyncio
async def test_batch_definition_validates_each_dataset_record_against_tool_schema() -> None:
    access, project_id, datasets = await create_module()
    dataset = await datasets.create_dataset(
        access,
        project_id,
        "Load cases",
        [DatasetRecordInput({"length": 1.5, "load": 12.5})],
    )
    definition = await datasets.create_definition(
        access,
        project_id,
        dataset.id,
        "Tip load calculation",
        "reference-calculation",
        "calculate_cantilever_tip_load",
        {"length_m": "/length", "tip_load_kn": "/load"},
    )

    assert definition.argument_mappings == {"length_m": "/length", "tip_load_kn": "/load"}
    with pytest.raises(DatasetValidationError, match="input schema"):
        await datasets.create_definition(
            access,
            project_id,
            dataset.id,
            "Bad mapping",
            "reference-calculation",
            "calculate_cantilever_tip_load",
            {"length_m": "/load"},
        )


@pytest.mark.asyncio
async def test_definition_declares_file_argument_without_dataset_placeholder() -> None:
    class TemplateSchemas:
        async def input_schema(self, *_: object) -> Mapping[str, object]:
            return {
                "type": "object",
                "required": ["template", "tip_load_kn"],
                "properties": {
                    "template": {"type": "string"},
                    "tip_load_kn": {"type": "number"},
                },
            }

    projects = create_memory_project_module()
    access = ProjectAccess(subject="sam")
    project = await projects.create(access, "Bridge")
    project_id = project.id
    datasets = DatasetModule(projects, MemoryDatasetStore(), TemplateSchemas())
    dataset = await datasets.create_dataset(
        access, project_id, "Loads", [DatasetRecordInput({"load": 12.5})]
    )
    definition = await datasets.create_definition(
        access,
        project_id,
        dataset.id,
        "With file input",
        "reference-calculation",
        "calculate_cantilever_tip_load",
        {"tip_load_kn": "/load"},
        file_argument="template",
    )
    assert definition.file_argument == "template"
    with pytest.raises(DatasetValidationError, match="file argument"):
        await datasets.create_definition(
            access,
            project_id,
            dataset.id,
            "Duplicate",
            "reference-calculation",
            "calculate_cantilever_tip_load",
            {"tip_load_kn": "/load", "template": "/load"},
            file_argument="template",
        )


@pytest.mark.asyncio
async def test_deleting_a_dataset_keeps_its_definition_visible_but_unavailable() -> None:
    access, project_id, datasets = await create_module()
    dataset = await datasets.create_dataset(
        access,
        project_id,
        "Load cases",
        [DatasetRecordInput({"length": 1.5, "load": 12.5})],
    )
    definition = await datasets.create_definition(
        access,
        project_id,
        dataset.id,
        "Tip load calculation",
        "reference-calculation",
        "calculate_cantilever_tip_load",
        {"length_m": "/length", "tip_load_kn": "/load"},
    )
    await datasets.delete_dataset(access, project_id, dataset.id)

    assert await datasets.list_definitions(access, project_id) == (definition,)
    with pytest.raises(DatasetNotFound):
        await datasets.load_dataset(access, project_id, dataset.id)
