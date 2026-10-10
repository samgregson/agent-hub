import json
from collections.abc import Mapping

import pytest
from psycopg import AsyncConnection, OperationalError
from pydantic import PostgresDsn

from agent_hub_api.modules.datasets import DatasetRecordInput, create_postgres_dataset_module
from agent_hub_api.modules.project_files import (
    ProjectFileAccess,
    ReservedProjectFilePath,
    create_postgres_project_files,
)
from agent_hub_api.modules.projects import ProjectAccess, create_postgres_project_module
from agent_hub_api.settings import Settings


class ToolSchemas:
    async def input_schema(self, *_: object) -> Mapping[str, object]:
        return {}


@pytest.mark.asyncio
async def test_dataset_is_a_versioned_project_file_with_dataset_owned_writes() -> None:
    settings = Settings(
        environment="test",
        database_url=PostgresDsn("postgresql://agent_hub:agent_hub@127.0.0.1:5432/agent_hub"),
    )
    try:
        connection = await AsyncConnection.connect(str(settings.database_url))
    except OperationalError:
        pytest.skip("Local PostgreSQL is unavailable")
    await connection.close()

    access = ProjectAccess(subject="dataset-file-integration")
    projects = create_postgres_project_module(settings)
    datasets = create_postgres_dataset_module(settings, projects, ToolSchemas())
    files = create_postgres_project_files(settings, projects)
    project = await projects.create(access, "Dataset file integration")
    try:
        created = await datasets.create_dataset(
            access, project.id, "Cases", [DatasetRecordInput({"load": 2}, "case-1")]
        )
        path = f"/.datasets/{created.id}.json"
        file = await files.preview(ProjectFileAccess(access.subject), project.id, path)
        document = json.loads(file.content)

        assert file.version == 1
        assert document["kind"] == "dataset"
        assert document["id"] == created.id
        assert document["records"] == [
            {
                "id": created.records[0].id,
                "position": 0,
                "sourceKey": "case-1",
                "value": {"load": 2},
            }
        ]
        with pytest.raises(ReservedProjectFilePath):
            await files.write(project.id, path, "{}")
        with pytest.raises(ReservedProjectFilePath):
            await files.delete_visible(ProjectFileAccess(access.subject), project.id, path)

        updated = await datasets.update_dataset(
            access,
            project.id,
            created.id,
            "Cases",
            [DatasetRecordInput({"load": 3}, "case-1", created.records[0].id)],
        )
        assert updated.records[0].id == created.records[0].id
        assert (await files.load(project.id, path)).version == 2
        assert (await datasets.load_dataset(access, project.id, created.id)) == updated
    finally:
        connection = await AsyncConnection.connect(str(settings.database_url))
        async with connection:
            await connection.execute("DELETE FROM projects WHERE id=%s", (project.id,))
