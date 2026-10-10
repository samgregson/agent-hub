"""Project HTTP adapter for cross-source Transform inputs."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from agent_hub_api.modules.identity import (
    IdentityEvidence,
    IdentityModule,
    IdentityUnavailable,
    RequestContext,
)
from agent_hub_api.modules.projects import ProjectAccess
from agent_hub_api.modules.transform_inputs._application import (
    ResultSetSelection,
    TransformInputModule,
    TransformInputValidationError,
)
from agent_hub_api.modules.transforms import (
    TransformExecutionError,
    TransformNotFound,
    TransformValidationError,
)


class _Model(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ResultSetSelectionRequest(_Model):
    source_run_id: str
    output_path: str = ""
    expected_definition_revision: int = Field(ge=1)
    filter_path: str | None = None
    equals: str | int | float | bool | None = None
    sort_path: str | None = None
    descending: bool = False
    limit: int | None = Field(default=None, ge=1, le=100)
    parameters: dict[str, object] = Field(default_factory=dict)


class SelectionPlanResponse(_Model):
    selection: dict[str, object]
    selected_count: int
    invocation_count: int
    output_location: str


class RunReferenceResponse(_Model):
    id: str
    status: str


def _selection(body: ResultSetSelectionRequest) -> ResultSetSelection:
    return ResultSetSelection(
        source_run_id=body.source_run_id,
        output_path=body.output_path,
        expected_definition_revision=body.expected_definition_revision,
        filter_path=body.filter_path,
        equals=body.equals,
        sort_path=body.sort_path,
        descending=body.descending,
        limit=body.limit,
    )


def create_transform_input_router(
    identity: IdentityModule, inputs: TransformInputModule
) -> APIRouter:
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

    def failure(error: Exception) -> HTTPException:
        if isinstance(error, TransformNotFound):
            return HTTPException(status_code=404, detail="Transform not found")
        if isinstance(error, TransformExecutionError):
            code = {
                "timeout": status.HTTP_504_GATEWAY_TIMEOUT,
                "input_limit": status.HTTP_413_CONTENT_TOO_LARGE,
                "output_limit": status.HTTP_413_CONTENT_TOO_LARGE,
                "runner_unavailable": status.HTTP_503_SERVICE_UNAVAILABLE,
                "busy": status.HTTP_503_SERVICE_UNAVAILABLE,
            }.get(error.code, status.HTTP_502_BAD_GATEWAY)
            return HTTPException(status_code=code, detail=error.code)
        return HTTPException(status_code=422, detail=str(error))

    @router.post("/{definition_id}/result-set-selection-plan", response_model=SelectionPlanResponse)
    async def plan(
        project_id: str,
        definition_id: str,
        body: ResultSetSelectionRequest,
        request_context: Context,
    ) -> SelectionPlanResponse:
        try:
            result = await inputs.plan_result_set_selection(
                ProjectAccess(subject=request_context.subject),
                project_id,
                definition_id,
                _selection(body),
                body.parameters,
            )
        except (
            TransformInputValidationError,
            TransformNotFound,
            TransformValidationError,
            TransformExecutionError,
        ) as error:
            raise failure(error) from error
        return SelectionPlanResponse(
            selection=dict(result.snapshot()),
            selected_count=result.selected_count,
            invocation_count=result.invocation_count,
            output_location="Transform Run output",
        )

    @router.post(
        "/{definition_id}/result-set-selection-runs",
        response_model=RunReferenceResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def start(
        project_id: str,
        definition_id: str,
        body: ResultSetSelectionRequest,
        request_context: Context,
    ) -> RunReferenceResponse:
        try:
            run = await inputs.start_result_set_run(
                ProjectAccess(subject=request_context.subject),
                project_id,
                definition_id,
                _selection(body),
                body.parameters,
            )
        except (
            TransformInputValidationError,
            TransformNotFound,
            TransformValidationError,
            TransformExecutionError,
        ) as error:
            raise failure(error) from error
        return RunReferenceResponse(id=run.id, status=run.status)

    return router
