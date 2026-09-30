from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from agent_hub_api.modules.batch_execution._application import (
    BatchExecutionModule,
    BatchRun,
    BatchRunNotArchivable,
    BatchRunNotFound,
    BatchRunOrder,
    BatchRunStatus,
)
from agent_hub_api.modules.identity import (
    IdentityEvidence,
    IdentityModule,
    IdentityUnavailable,
    RequestContext,
)
from agent_hub_api.modules.projects import ProjectAccess


class _Model(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class StartRequest(_Model):
    definition_id: str
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)
    record_id: str | None = None


class ResultResponse(_Model):
    dataset_record_id: str
    input: dict[str, object]
    structured_output: dict[str, object] | None
    error: str | None


class BatchRunResponse(_Model):
    archived_at: str | None
    created_at: str
    id: str
    definition_id: str
    status: str
    records: list[ResultResponse]
    updated_at: str


class BatchRunPageResponse(_Model):
    items: list[BatchRunResponse]
    next_offset: int | None


def _response(run: BatchRun) -> BatchRunResponse:
    return BatchRunResponse(
        archived_at=run.archived_at.isoformat() if run.archived_at else None,
        created_at=run.created_at.isoformat(),
        id=run.id,
        definition_id=run.definition_id,
        status=run.status.value,
        records=[
            ResultResponse(
                dataset_record_id=item.dataset_record_id,
                input=dict(item.input),
                structured_output=dict(item.structured_output) if item.structured_output else None,
                error=item.error,
            )
            for item in run.records
        ],
        updated_at=run.updated_at.isoformat(),
    )


def create_batch_execution_router(
    identity: IdentityModule,
    batches: BatchExecutionModule,
) -> APIRouter:
    router = APIRouter(prefix="/projects/{project_id}/batch-runs", tags=["batch-runs"])

    async def context(request: Request) -> RequestContext:
        try:
            return identity.resolve(IdentityEvidence(headers=request.headers))
        except IdentityUnavailable as error:
            raise HTTPException(
                status_code=401, detail="Authenticated platform identity is required"
            ) from error

    Context = Annotated[RequestContext, Depends(context)]
    StatusFilter = Annotated[BatchRunStatus | None, Query(alias="status")]

    @router.get("", response_model=BatchRunPageResponse)
    async def list_runs(
        project_id: str,
        request_context: Context,
        definition_id: str | None = None,
        status_filter: StatusFilter = None,
        order: BatchRunOrder = BatchRunOrder.newest,
        limit: int = 10,
        offset: int = 0,
        include_archived: bool = False,
    ) -> BatchRunPageResponse:
        try:
            page = await batches.list(
                ProjectAccess(subject=request_context.subject),
                project_id,
                definition_id,
                status_filter,
                order,
                limit,
                offset,
                include_archived,
            )
            return BatchRunPageResponse(
                items=[_response(run) for run in page.items],
                next_offset=page.next_offset,
            )
        except BatchRunNotFound as error:
            raise HTTPException(status_code=404, detail="Project not found") from error

    @router.post("", response_model=BatchRunResponse, status_code=status.HTTP_201_CREATED)
    async def start(
        project_id: str, body: StartRequest, request_context: Context
    ) -> BatchRunResponse:
        try:
            request_access = ProjectAccess(subject=request_context.subject)
            run = await batches.submit_one(
                request_access,
                project_id,
                body.definition_id,
                body.record_id or "",
                body.idempotency_key,
            )
            await batches.enqueue(request_access, project_id, run.id)
            return _response(run)
        except BatchRunNotFound as error:
            raise HTTPException(status_code=404, detail="Batch Run target not found") from error

    @router.get("/{run_id}", response_model=BatchRunResponse)
    async def load(project_id: str, run_id: str, request_context: Context) -> BatchRunResponse:
        try:
            return _response(
                await batches.load(
                    ProjectAccess(subject=request_context.subject), project_id, run_id
                )
            )
        except BatchRunNotFound as error:
            raise HTTPException(status_code=404, detail="Batch Run not found") from error

    @router.post("/{run_id}/archive", response_model=BatchRunResponse)
    async def archive(
        project_id: str, run_id: str, request_context: Context
    ) -> BatchRunResponse:
        try:
            return _response(await batches.archive(
                ProjectAccess(subject=request_context.subject), project_id, run_id
            ))
        except BatchRunNotFound as error:
            raise HTTPException(status_code=404, detail="Batch Run not found") from error
        except BatchRunNotArchivable as error:
            raise HTTPException(status_code=409, detail="Batch Run is still active") from error

    @router.post("/all", response_model=BatchRunResponse, status_code=status.HTTP_201_CREATED)
    async def start_all(
        project_id: str, body: StartRequest, request_context: Context
    ) -> BatchRunResponse:
        try:
            request_access = ProjectAccess(subject=request_context.subject)
            run = await batches.submit_all(
                request_access, project_id, body.definition_id, body.idempotency_key
            )
            await batches.enqueue(request_access, project_id, run.id)
            return _response(run)
        except BatchRunNotFound as error:
            raise HTTPException(status_code=404, detail="Batch Run target not found") from error

    return router
