from collections.abc import Mapping
from typing import cast

import pytest
from psycopg import AsyncConnection, OperationalError
from pydantic import PostgresDsn

from agent_hub_api.modules.batch_execution import create_postgres_batch_execution_module
from agent_hub_api.modules.bindings import BindingUnavailable, create_postgres_binding_module
from agent_hub_api.modules.datasets import DatasetRecordInput, create_postgres_dataset_module
from agent_hub_api.modules.plugin_gateway import PluginGatewayModule, PluginToolResult
from agent_hub_api.modules.project_files import create_postgres_project_files
from agent_hub_api.modules.projects import ProjectAccess, create_postgres_project_module
from agent_hub_api.settings import Settings


class TemplateTool:
    async def input_schema(self, *_: object) -> Mapping[str, object]:
        return {
            "type": "object",
            "required": ["template", "value"],
            "properties": {"template": {"type": "string"}, "value": {"type": "number"}},
        }

    async def output_schema(self, *_: object) -> Mapping[str, object]:
        return {
            "type": "object",
            "required": ["rendered"],
            "properties": {"rendered": {"type": "string"}},
        }

    async def batch_call(
        self,
        _access: ProjectAccess,
        _project_id: str,
        _plugin_id: str,
        _tool_name: str,
        arguments: Mapping[str, object],
    ) -> PluginToolResult:
        return PluginToolResult((), {"rendered": str(arguments["template"])})


@pytest.mark.asyncio
async def test_postgres_binding_survives_reload_and_snapshots_file_for_run() -> None:
    settings = Settings(
        environment="test",
        database_url=PostgresDsn("postgresql://agent_hub:agent_hub@127.0.0.1:5432/agent_hub"),
    )
    try:
        connection = await AsyncConnection.connect(str(settings.database_url))
    except OperationalError:
        pytest.skip("Local PostgreSQL is unavailable")
    await connection.close()
    access = ProjectAccess(subject="binding-postgres-integration")
    projects = create_postgres_project_module(settings)
    files = create_postgres_project_files(settings, projects)
    tool = TemplateTool()
    datasets = create_postgres_dataset_module(settings, projects, tool)
    bindings = create_postgres_binding_module(settings, projects, datasets, files)
    batches = create_postgres_batch_execution_module(
        settings, projects, datasets, cast(PluginGatewayModule, tool), bindings=bindings
    )
    project = await projects.create(access, "Binding integration")
    try:
        file = await files.write(project.id, "/template.txt", "value={{value}}")
        data = await datasets.create_dataset(
            access, project.id, "Values", [DatasetRecordInput({"value": 2})]
        )
        definition = await datasets.create_definition(
            access,
            project.id,
            data.id,
            "Render",
            "fixture",
            "render_template_value",
            {"value": "/value"},
            file_argument="template",
        )
        binding = await bindings.bind_file(
            access, project.id, definition.id, file.path, file.version
        )
        reloaded = create_postgres_binding_module(settings, projects, datasets, files)
        assert (await reloaded.load(access, project.id, definition.id)).id == binding.id
        run = await batches.start_all(
            access, project.id, definition.id, idempotency_key="file-bound-run"
        )
        captured_file = run.definition_snapshot["fileBinding"]
        assert isinstance(captured_file, Mapping)
        assert captured_file["content"] == "value={{value}}"
        await files.write(project.id, file.path, "changed")
        replay = await batches.submit_all(
            access, project.id, definition.id, idempotency_key="file-bound-run"
        )
        assert replay.id == run.id
        with pytest.raises(BindingUnavailable, match="changed"):
            await batches.submit_all(access, project.id, definition.id)
        updated = await reloaded.rebind_file(
            access,
            project.id,
            definition.id,
            file.path,
            2,
            expected_binding_version=binding.version,
        )
        assert updated.version == 2
    finally:
        connection = await AsyncConnection.connect(str(settings.database_url))
        async with connection:
            await connection.execute("DELETE FROM projects WHERE id=%s", (project.id,))
