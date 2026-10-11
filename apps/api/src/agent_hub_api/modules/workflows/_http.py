"""HTTP adapter for Project Workflow Definitions."""

from dataclasses import asdict
from datetime import datetime
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

from ._application import (
    WorkflowDefinition,
    WorkflowDefinitionModule,
    WorkflowGraph,
    WorkflowNotFound,
    WorkflowValidationError,
    WorkflowVersionConflict,
)


class _Model(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class NodeModel(_Model):
    id: str
    kind: str
    ref_id: str
    version: int | str
    shape: str = "single"
    tool_name: str | None = None


class EdgeModel(_Model):
    source_node: str
    source_port: str
    target_node: str
    target_port: str


class OutputModel(_Model):
    name: str
    node: str
    port: str


class GraphModel(_Model):
    nodes: list[NodeModel]
    edges: list[EdgeModel]
    outputs: list[OutputModel]


class WorkflowRequest(_Model):
    name: str
    graph: GraphModel
    expected_version: int | None = Field(default=None, ge=1)


class WorkflowResponse(_Model):
    id: str
    name: str
    graph: GraphModel
    version: int
    created_at: datetime
    updated_at: datetime


def _graph(value: GraphModel) -> WorkflowGraph:
    return WorkflowGraph.from_json(value.model_dump_json(by_alias=False))


def _response(value: WorkflowDefinition) -> WorkflowResponse:
    return WorkflowResponse(
        id=value.id,
        name=value.name,
        graph=GraphModel.model_validate(asdict(value.graph)),
        version=value.version,
        created_at=value.created_at,
        updated_at=value.updated_at,
    )


def create_workflow_router(
    identity: IdentityModule, workflows: WorkflowDefinitionModule
) -> APIRouter:
    router = APIRouter(prefix="/projects/{project_id}/workflows", tags=["workflows"])

    async def context(request: Request) -> RequestContext:
        try:
            return identity.resolve(IdentityEvidence(headers=request.headers))
        except IdentityUnavailable as error:
            raise HTTPException(
                status_code=401, detail="Authenticated identity is required."
            ) from error

    Context = Annotated[RequestContext, Depends(context)]

    @router.post(
        "",
        response_model=WorkflowResponse,
        response_model_exclude_defaults=True,
        status_code=status.HTTP_201_CREATED,
    )
    async def create(
        project_id: str, body: WorkflowRequest, request_context: Context
    ) -> WorkflowResponse:
        if body.expected_version is not None:
            raise HTTPException(status_code=422, detail="New Workflow has no expected version.")
        try:
            saved = await workflows.create(
                ProjectAccess(request_context.subject), project_id, body.name, _graph(body.graph)
            )
        except WorkflowNotFound as error:
            raise HTTPException(status_code=404, detail="Project is unavailable.") from error
        except WorkflowValidationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return _response(saved)

    @router.get("", response_model=list[WorkflowResponse], response_model_exclude_defaults=True)
    async def list_workflows(project_id: str, request_context: Context) -> list[WorkflowResponse]:
        try:
            items = await workflows.list(ProjectAccess(request_context.subject), project_id)
        except WorkflowNotFound as error:
            raise HTTPException(status_code=404, detail="Project is unavailable.") from error
        return [_response(item) for item in items]

    @router.get(
        "/{workflow_id}", response_model=WorkflowResponse, response_model_exclude_defaults=True
    )
    async def load(project_id: str, workflow_id: str, request_context: Context) -> WorkflowResponse:
        try:
            item = await workflows.load(
                ProjectAccess(request_context.subject), project_id, workflow_id
            )
        except WorkflowNotFound as error:
            raise HTTPException(status_code=404, detail="Workflow is unavailable.") from error
        return _response(item)

    @router.put(
        "/{workflow_id}", response_model=WorkflowResponse, response_model_exclude_defaults=True
    )
    async def revise(
        project_id: str, workflow_id: str, body: WorkflowRequest, request_context: Context
    ) -> WorkflowResponse:
        if body.expected_version is None:
            raise HTTPException(status_code=422, detail="Workflow version is required.")
        try:
            item = await workflows.revise(
                ProjectAccess(request_context.subject),
                project_id,
                workflow_id,
                body.name,
                _graph(body.graph),
                expected_version=body.expected_version,
            )
        except WorkflowNotFound as error:
            raise HTTPException(status_code=404, detail="Workflow is unavailable.") from error
        except WorkflowVersionConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except WorkflowValidationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return _response(item)

    return router
