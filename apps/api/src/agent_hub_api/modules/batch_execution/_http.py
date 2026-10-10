import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from agent_hub_api.modules.batch_execution._application import (
    BatchExecutionModule,
    BatchRun,
    BatchRunIdempotencyConflict,
    BatchRunNotArchivable,
    BatchRunNotFound,
    BatchRunOrder,
    BatchRunStatus,
)
from agent_hub_api.modules.bindings import BindingUnavailable
from agent_hub_api.modules.identity import (
    IdentityEvidence,
    IdentityModule,
    IdentityUnavailable,
    RequestContext,
)
from agent_hub_api.modules.projects import ProjectAccess
from agent_hub_api.modules.transforms import TransformExecutionError


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
    definition_name: str | None
    initiator_subject: str | None
    initiation: dict[str, object]
    status: str
    record_count: int
    succeeded_count: int
    failed_count: int
    updated_at: str


class BatchRunDetailResponse(BatchRunResponse):
    definition_snapshot: dict[str, object]


class BatchRunPageResponse(_Model):
    items: list[BatchRunResponse]
    next_offset: int | None


class ResultRecordPageResponse(_Model):
    items: list[ResultResponse]
    next_offset: int | None
    summary: "ResultSummaryResponse"


class ResultSummaryResponse(_Model):
    total_count: int
    succeeded_count: int
    failed_count: int
    numeric_count: int
    numeric_sum: float | None
    numeric_min: float | None
    numeric_max: float | None
    numeric_average: float | None


def _response(run: BatchRun) -> BatchRunResponse:
    definition_name = run.definition_snapshot.get("definitionName")
    return BatchRunResponse(
        archived_at=run.archived_at.isoformat() if run.archived_at else None,
        created_at=run.created_at.isoformat(),
        id=run.id,
        definition_id=run.definition_id,
        definition_name=definition_name if isinstance(definition_name, str) else None,
        initiator_subject=run.initiator_subject,
        initiation=dict(run.initiation),
        status=run.status.value,
        record_count=len(run.records),
        succeeded_count=sum(item.structured_output is not None for item in run.records),
        failed_count=sum(item.error is not None for item in run.records),
        updated_at=run.updated_at.isoformat(),
    )


def create_batch_execution_router(
    identity: IdentityModule,
    batches: BatchExecutionModule,
) -> APIRouter:
    router = APIRouter(prefix="/projects/{project_id}/batch-runs", tags=["batch-runs"])

    async def context(request: Request) -> RequestContext:
        try:
            return identity.resolve(
                IdentityEvidence(
                    headers=request.headers, request_id=getattr(request.state, "request_id", None)
                )
            )
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
        except TransformExecutionError as error:
            raise HTTPException(status_code=422, detail=error.code) from error
        except BindingUnavailable as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except BatchRunIdempotencyConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.get("/{run_id}", response_model=BatchRunDetailResponse)
    async def load(
        project_id: str, run_id: str, request_context: Context
    ) -> BatchRunDetailResponse:
        try:
            run = await batches.load(
                ProjectAccess(subject=request_context.subject), project_id, run_id
            )
            return BatchRunDetailResponse(
                **_response(run).model_dump(), definition_snapshot=dict(run.definition_snapshot)
            )
        except BatchRunNotFound as error:
            raise HTTPException(status_code=404, detail="Batch Run not found") from error

    @router.get("/{run_id}/results", response_model=ResultRecordPageResponse)
    async def inspect_results(
        project_id: str,
        run_id: str,
        request_context: Context,
        limit: int = 100,
        offset: int = 0,
        filter_path: str | None = None,
        equals: str | None = None,
        minimum: float | None = None,
        maximum: float | None = None,
        sort_path: str | None = None,
        descending: bool = False,
        aggregate_path: str | None = None,
    ) -> ResultRecordPageResponse:
        try:
            equal_value = json.loads(equals) if equals is not None else None
            if equals is not None and not isinstance(equal_value, (str, int, float, bool)):
                raise ValueError("Equality must be a JSON string, number, or boolean.")
            page = await batches.inspect_results(
                ProjectAccess(subject=request_context.subject),
                project_id,
                run_id,
                limit=limit,
                offset=offset,
                filter_path=filter_path,
                equals=equal_value,
                minimum=minimum,
                maximum=maximum,
                sort_path=sort_path,
                descending=descending,
                aggregate_path=aggregate_path,
            )
        except BatchRunNotFound as error:
            raise HTTPException(status_code=404, detail="Batch Run not found") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return ResultRecordPageResponse(
            items=[
                ResultResponse(
                    dataset_record_id=item.dataset_record_id,
                    input=dict(item.input),
                    structured_output=(
                        dict(item.structured_output) if item.structured_output else None
                    ),
                    error=item.error,
                )
                for item in page.items
            ],
            next_offset=page.next_offset,
            summary=ResultSummaryResponse(
                total_count=page.summary.total_count,
                succeeded_count=page.summary.succeeded_count,
                failed_count=page.summary.failed_count,
                numeric_count=page.summary.numeric_count,
                numeric_sum=page.summary.numeric_sum,
                numeric_min=page.summary.numeric_min,
                numeric_max=page.summary.numeric_max,
                numeric_average=page.summary.numeric_average,
            ),
        )

    @router.post("/{run_id}/archive", response_model=BatchRunResponse)
    async def archive(project_id: str, run_id: str, request_context: Context) -> BatchRunResponse:
        try:
            return _response(
                await batches.archive(
                    ProjectAccess(subject=request_context.subject), project_id, run_id
                )
            )
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
        except TransformExecutionError as error:
            raise HTTPException(status_code=422, detail=error.code) from error
        except BindingUnavailable as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except BatchRunIdempotencyConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    return router
