from collections.abc import Mapping
from typing import cast

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from agent_hub_api.modules.batch_execution import (
    BatchExecutionModule,
    MemoryBatchRunStore,
    create_batch_execution_router,
)
from agent_hub_api.modules.bindings import (
    BindingModule,
    MemoryBindingStore,
    create_binding_router,
)
from agent_hub_api.modules.datasets import (
    DatasetModule,
    MemoryDatasetStore,
    create_dataset_router,
)
from agent_hub_api.modules.identity import create_identity_module
from agent_hub_api.modules.plugin_gateway import PluginGatewayModule, PluginToolResult
from agent_hub_api.modules.project_files import create_memory_project_files
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module
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
async def test_manual_binding_route_rejects_stale_source_and_exposes_run_capture() -> None:
    projects = create_memory_project_module()
    access = ProjectAccess(subject="sam")
    project = await projects.create(access, "Templates")
    files = create_memory_project_files(projects)
    file = await files.write(project.id, "/template.txt", "value={{value}}")
    tool = TemplateTool()
    datasets = DatasetModule(projects, MemoryDatasetStore(), tool)
    bindings = BindingModule(projects, datasets, files, MemoryBindingStore())
    batches = BatchExecutionModule(
        projects,
        datasets,
        cast(PluginGatewayModule, tool),
        MemoryBatchRunStore(),
        bindings=bindings,
    )
    identity = create_identity_module(Settings(environment="test", fixed_identity_subject="sam"))
    app = FastAPI()
    app.include_router(create_dataset_router(identity, datasets), prefix="/api")
    app.include_router(create_binding_router(identity, bindings), prefix="/api")
    app.include_router(create_batch_execution_router(identity, batches), prefix="/api")
    root = f"/api/projects/{project.id}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        dataset_response = await client.post(
            f"{root}/datasets",
            json={"name": "Values", "records": [{"value": {"value": 2}}]},
        )
        definition_response = await client.post(
            f"{root}/batch-definitions",
            json={
                "datasetId": dataset_response.json()["id"],
                "name": "Render",
                "pluginId": "fixture",
                "toolName": "render_template_value",
                "argumentMappings": {"value": "/value"},
                "fileArgument": "template",
            },
        )
        assert definition_response.status_code == 201
        definition_id = definition_response.json()["id"]
        binding_url = f"{root}/batch-definitions/{definition_id}/file-binding"
        first = await client.post(
            binding_url,
            json={"sourcePath": "/project/template.txt", "expectedFileVersion": 1},
        )
        assert first.status_code == 201
        assert first.json()["version"] == 1
        await files.write(project.id, file.path, "changed")
        stale = await client.post(f"{root}/batch-runs/all", json={"definitionId": definition_id})
        assert stale.status_code == 409
        conflict = await client.put(
            binding_url,
            json={
                "sourcePath": "/project/template.txt",
                "expectedFileVersion": 2,
                "expectedBindingVersion": 0,
            },
        )
        assert conflict.status_code == 422
        rebound = await client.put(
            binding_url,
            json={
                "sourcePath": "/project/template.txt",
                "expectedFileVersion": 2,
                "expectedBindingVersion": 1,
            },
        )
        assert rebound.status_code == 200
        assert rebound.json()["version"] == 2
        started = await client.post(f"{root}/batch-runs/all", json={"definitionId": definition_id})
        assert started.status_code == 201
        detail = await client.get(f"{root}/batch-runs/{started.json()['id']}")
        results = await client.get(f"{root}/batch-runs/{started.json()['id']}/results")
        assert detail.json()["definitionSnapshot"]["fileBinding"]["content"] == "changed"
        assert results.json()["items"][0]["input"] == {"template": "changed", "value": 2}
