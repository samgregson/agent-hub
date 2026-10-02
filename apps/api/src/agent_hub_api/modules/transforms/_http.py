from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from agent_hub_api.modules.artifacts import ArtifactDocument, ArtifactUserActionAccess
from agent_hub_api.modules.datasets import DatasetValidationError
from agent_hub_api.modules.identity import (
    IdentityEvidence,
    IdentityModule,
    IdentityUnavailable,
    RequestContext,
)
from agent_hub_api.modules.projects import ProjectAccess
from agent_hub_api.modules.transforms._application import (
    TransformDefinition,
    TransformExecutionError,
    TransformModule,
    TransformNotFound,
    TransformRun,
    TransformValidationError,
)


class _Model(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class DefinitionRequest(_Model):
    name: str
    source: str
    input_selectors: dict[str, str]
    output_schema: dict[str, object]


class DefinitionResponse(_Model):
    id: str
    name: str
    source: str
    input_selectors: dict[str, str]
    output_schema: dict[str, object]
    runtime: str | None
    package_hash: str | None
    source_hash: str
    revision: int
    created_at: str
    updated_at: str


class PreviewRequest(_Model):
    record: dict[str, object]
    parameters: dict[str, object]


class PreviewResponse(_Model):
    output: object
    runtime: str
    source_hash: str


class RunResponse(_Model):
    id: str
    definition_id: str
    status: str
    definition_snapshot: dict[str, object]
    inputs: dict[str, object]
    parameters: dict[str, object]
    input_hash: str
    source_hash: str
    runtime: str | None
    package_hash: str | None
    output: object | None
    output_manifest: dict[str, object]
    error: str | None
    initiator_subject: str
    initiation: dict[str, object]
    limits: dict[str, object]
    created_at: str
    completed_at: str | None


class RunPageResponse(_Model):
    items: list[RunResponse]
    next_offset: int | None


class SaveDatasetRequest(_Model):
    name: str


class SaveArtifactRequest(_Model):
    title: str


class SaveDatasetResponse(_Model):
    id: str
    name: str
    record_count: int
    source_run_id: str


def _response(definition: TransformDefinition) -> DefinitionResponse:
    return DefinitionResponse(
        id=definition.id,
        name=definition.name,
        source=definition.source,
        input_selectors=dict(definition.input_selectors),
        output_schema=dict(definition.output_schema),
        runtime=definition.runtime,
        package_hash=definition.package_hash,
        source_hash=definition.source_hash,
        revision=definition.revision,
        created_at=definition.created_at.isoformat(),
        updated_at=definition.updated_at.isoformat(),
    )


def _run_response(run: TransformRun) -> RunResponse:
    return RunResponse(
        id=run.id,
        definition_id=run.definition_id,
        status=run.status,
        definition_snapshot=dict(run.definition_snapshot),
        inputs=dict(run.inputs),
        parameters=dict(run.parameters),
        input_hash=run.input_hash,
        source_hash=run.source_hash,
        runtime=run.runtime,
        output=run.output,
        package_hash=run.package_hash,
        output_manifest=dict(run.output_manifest),
        error=run.error,
        initiator_subject=run.initiator_subject,
        created_at=run.created_at.isoformat(),
        initiation=dict(run.initiation),
        limits=dict(run.limits),
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
    )


def create_transform_router(identity: IdentityModule, transforms: TransformModule) -> APIRouter:
    router = APIRouter(prefix="/projects/{project_id}/transforms", tags=["transforms"])

    async def context(request: Request) -> RequestContext:
        try:
            return identity.resolve(
                IdentityEvidence(
                    headers=request.headers, request_id=getattr(request.state, "request_id", None)
                )
            )
        except IdentityUnavailable as error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authenticated platform identity is required",
            ) from error

    Context = Annotated[RequestContext, Depends(context)]

    def access(value: RequestContext) -> ProjectAccess:
        return ProjectAccess(subject=value.subject)

    def failure(error: Exception) -> HTTPException:
        if isinstance(error, TransformNotFound):
            return HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Transform not found"
            )
        if isinstance(error, TransformExecutionError):
            status_code = {
                "timeout": status.HTTP_504_GATEWAY_TIMEOUT,
                "input_limit": status.HTTP_413_CONTENT_TOO_LARGE,
                "output_limit": status.HTTP_413_CONTENT_TOO_LARGE,
                "execution_failed": status.HTTP_422_UNPROCESSABLE_CONTENT,
                "runner_unavailable": status.HTTP_503_SERVICE_UNAVAILABLE,
                "busy": status.HTTP_503_SERVICE_UNAVAILABLE,
            }.get(error.code, status.HTTP_502_BAD_GATEWAY)
            return HTTPException(status_code=status_code, detail=error.code)
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error))

    @router.post("", response_model=DefinitionResponse, status_code=status.HTTP_201_CREATED)
    async def define(
        project_id: str, body: DefinitionRequest, request_context: Context
    ) -> DefinitionResponse:
        try:
            return _response(
                await transforms.define(
                    access(request_context),
                    project_id,
                    body.name,
                    body.source,
                    body.input_selectors,
                    body.output_schema,
                )
            )
        except (TransformNotFound, TransformValidationError) as error:
            raise failure(error) from error

    @router.get("", response_model=list[DefinitionResponse])
    async def list_definitions(
        project_id: str, request_context: Context
    ) -> list[DefinitionResponse]:
        try:
            items = await transforms.list(access(request_context), project_id)
            return [_response(item) for item in items]
        except TransformNotFound as error:
            raise failure(error) from error

    @router.get("/runs", response_model=RunPageResponse)
    async def list_runs(
        project_id: str,
        request_context: Context,
        definition_id: str | None = Query(default=None, alias="definitionId"),
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> RunPageResponse:
        try:
            page = await transforms.list_runs(
                access(request_context), project_id, definition_id, limit, offset
            )
            return RunPageResponse(
                items=[_run_response(run) for run in page.items],
                next_offset=page.next_offset,
            )
        except (TransformNotFound, TransformExecutionError) as error:
            raise failure(error) from error

    @router.get("/{definition_id}", response_model=DefinitionResponse)
    async def load(
        project_id: str, definition_id: str, request_context: Context
    ) -> DefinitionResponse:
        try:
            definition = await transforms.load(access(request_context), project_id, definition_id)
            return _response(definition)
        except TransformNotFound as error:
            raise failure(error) from error

    @router.post("/{definition_id}/preview", response_model=PreviewResponse)
    async def preview(
        project_id: str,
        definition_id: str,
        body: PreviewRequest,
        request_context: Context,
    ) -> PreviewResponse:
        try:
            result = await transforms.preview(
                access(request_context),
                project_id,
                definition_id,
                body.record,
                body.parameters,
            )
            return PreviewResponse(
                output=result.output,
                runtime=result.runtime,
                source_hash=result.source_hash,
            )
        except (TransformNotFound, TransformValidationError, TransformExecutionError) as error:
            raise failure(error) from error

    @router.post(
        "/{definition_id}/runs",
        response_model=RunResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def start_run(
        project_id: str,
        definition_id: str,
        body: PreviewRequest,
        request_context: Context,
    ) -> RunResponse:
        try:
            run = await transforms.start_run(
                access(request_context),
                project_id,
                definition_id,
                body.record,
                body.parameters,
            )
            return _run_response(run)
        except (TransformNotFound, TransformValidationError, TransformExecutionError) as error:
            raise failure(error) from error

    @router.get("/runs/{run_id}", response_model=RunResponse)
    async def load_run(project_id: str, run_id: str, request_context: Context) -> RunResponse:
        try:
            return _run_response(
                await transforms.load_run(access(request_context), project_id, run_id)
            )
        except (TransformNotFound, TransformExecutionError) as error:
            raise failure(error) from error

    @router.post(
        "/runs/{run_id}/save-dataset",
        response_model=SaveDatasetResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def save_dataset(
        project_id: str,
        run_id: str,
        body: SaveDatasetRequest,
        request_context: Context,
    ) -> SaveDatasetResponse:
        try:
            dataset = await transforms.save_run_as_dataset(
                access(request_context), project_id, run_id, body.name
            )
            return SaveDatasetResponse(
                id=dataset.id,
                name=dataset.name,
                record_count=len(dataset.records),
                source_run_id=run_id,
            )
        except (
            TransformNotFound,
            TransformValidationError,
            TransformExecutionError,
            DatasetValidationError,
        ) as error:
            raise failure(error) from error

    @router.post(
        "/runs/{run_id}/save-artifact",
        response_model=ArtifactDocument,
        status_code=status.HTTP_201_CREATED,
    )
    async def save_artifact(
        project_id: str,
        run_id: str,
        body: SaveArtifactRequest,
        request_context: Context,
    ) -> ArtifactDocument:
        try:
            return await transforms.save_run_as_artifact(
                ArtifactUserActionAccess(
                    subject=request_context.subject, user_action_id=str(uuid4())
                ),
                project_id,
                run_id,
                body.title,
            )
        except (TransformNotFound, TransformValidationError, TransformExecutionError) as error:
            raise failure(error) from error

    @router.put("/{definition_id}", response_model=DefinitionResponse)
    async def revise(
        project_id: str,
        definition_id: str,
        body: DefinitionRequest,
        request_context: Context,
    ) -> DefinitionResponse:
        try:
            return _response(
                await transforms.revise(
                    access(request_context),
                    project_id,
                    definition_id,
                    body.name,
                    body.source,
                    body.input_selectors,
                    body.output_schema,
                )
            )
        except (TransformNotFound, TransformValidationError) as error:
            raise failure(error) from error

    @router.delete("/{definition_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete(project_id: str, definition_id: str, request_context: Context) -> None:
        try:
            await transforms.delete(access(request_context), project_id, definition_id)
        except TransformNotFound as error:
            raise failure(error) from error

    return router
