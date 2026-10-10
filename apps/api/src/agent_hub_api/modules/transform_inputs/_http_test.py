from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from agent_hub_api.modules.identity import create_identity_module
from agent_hub_api.modules.transform_inputs import (
    ArtifactSelection,
    ResultSetSelection,
    TransformInputModule,
    create_transform_input_router,
)
from agent_hub_api.settings import Settings


@pytest.mark.asyncio
async def test_retained_selection_plans_and_runs_use_project_routes() -> None:
    class Inputs:
        async def plan_artifact_selection(
            self,
            _access: object,
            _project_id: str,
            _definition_id: str,
            selection: ArtifactSelection,
            _parameters: dict[str, object],
        ) -> object:
            assert selection == ArtifactSelection("artifact-1", 2, "/measurements", 2, limit=1)
            return SimpleNamespace(
                snapshot=lambda: {"sourceKind": "mcpToolResult", "artifactId": "artifact-1"},
                selected_count=1,
                invocation_count=1,
            )

        async def start_artifact_run(
            self,
            _access: object,
            _project_id: str,
            _definition_id: str,
            selection: ArtifactSelection,
            _parameters: dict[str, object],
        ) -> object:
            assert selection.artifact_id == "artifact-1"
            return SimpleNamespace(id="transform-run-2", status="succeeded")

        async def plan_result_set_selection(
            self,
            _access: object,
            _project_id: str,
            _definition_id: str,
            selection: ResultSetSelection,
            _parameters: dict[str, object],
        ) -> object:
            assert selection == ResultSetSelection("batch-1", "/score", 2, limit=1)
            return SimpleNamespace(
                snapshot=lambda: {"sourceKind": "resultSet", "batchRunId": "batch-1"},
                selected_count=1,
                invocation_count=1,
            )

        async def start_result_set_run(
            self,
            _access: object,
            _project_id: str,
            _definition_id: str,
            selection: ResultSetSelection,
            _parameters: dict[str, object],
        ) -> object:
            assert selection.source_run_id == "batch-1"
            return SimpleNamespace(id="transform-run-1", status="succeeded")

    app = FastAPI()
    app.include_router(
        create_transform_input_router(
            create_identity_module(Settings(environment="test", fixed_identity_subject="sam")),
            cast(TransformInputModule, cast(Any, Inputs())),
        ),
        prefix="/api",
    )
    root = "/api/projects/project-1/transforms/transform-1"
    body = {
        "sourceRunId": "batch-1",
        "outputPath": "/score",
        "expectedDefinitionRevision": 2,
        "limit": 1,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        plan = await client.post(f"{root}/result-set-selection-plan", json=body)
        assert plan.status_code == 200
        assert plan.json()["selection"] == {"sourceKind": "resultSet", "batchRunId": "batch-1"}
        assert plan.json()["invocationCount"] == 1
        started = await client.post(f"{root}/result-set-selection-runs", json=body)
        assert started.status_code == 201
        assert started.json() == {"id": "transform-run-1", "status": "succeeded"}
        artifact_body = {
            "artifactId": "artifact-1",
            "expectedArtifactVersion": 2,
            "outputPath": "/measurements",
            "expectedDefinitionRevision": 2,
            "limit": 1,
        }
        plan = await client.post(f"{root}/artifact-selection-plan", json=artifact_body)
        assert plan.status_code == 200
        assert plan.json()["selection"] == {
            "sourceKind": "mcpToolResult",
            "artifactId": "artifact-1",
        }
        started = await client.post(f"{root}/artifact-selection-runs", json=artifact_body)
        assert started.status_code == 201
        assert started.json() == {"id": "transform-run-2", "status": "succeeded"}
