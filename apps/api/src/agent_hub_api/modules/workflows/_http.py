"""HTTP adapter for Project Workflow Definitions."""

from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from agent_hub_api.contracts import ArtifactDocument
from agent_hub_api.modules.artifacts import (
    ArtifactDraft,
    ArtifactModule,
    ArtifactNotFound,
    ArtifactUserActionAccess,
)
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
    WorkflowEdge,
    WorkflowGraph,
    WorkflowInput,
    WorkflowNode,
    WorkflowNotFound,
    WorkflowOutput,
    WorkflowValidationError,
    WorkflowVersionConflict,
)
from ._runs import WorkflowRun, WorkflowRunConflict, WorkflowRunModule


class _Model(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class NodeModel(_Model):
    id: str
    kind: str
    ref_id: str
    version: int | str
    shape: str = "single"
    tool_name: str | None = None
    map_input: str | None = None


class EdgeModel(_Model):
    source_node: str | None = None
    source_port: str | None = None
    target_node: str
    target_port: str
    source_kind: str = "node"
    source_input: str | None = None
    source_path: str = ""
    target_path: str = ""
    literal: Any = None


class WorkflowInputModel(_Model):
    name: str
    schema_: dict[str, Any] = Field(alias="schema")
    required: bool = True


class OutputModel(_Model):
    name: str
    node: str
    port: str


class GraphModel(_Model):
    nodes: list[NodeModel]
    edges: list[EdgeModel]
    outputs: list[OutputModel]
    inputs: list[WorkflowInputModel] = Field(default_factory=list)


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


class PrepareRunRequest(_Model):
    idempotency_key: str = Field(min_length=1, max_length=120)
    expected_version: int = Field(ge=1)
    workflow_inputs: dict[str, Any] = Field(default_factory=dict)


class WorkflowRunResponse(_Model):
    id: str
    workflow_id: str
    definition_version: int
    status: str
    snapshot: dict[str, object]
    execution: dict[str, object]
    initiator_subject: str
    created_at: datetime


def _graph(value: GraphModel) -> WorkflowGraph:
    return WorkflowGraph(
        nodes=tuple(WorkflowNode(**node.model_dump(by_alias=False)) for node in value.nodes),
        edges=tuple(WorkflowEdge(**edge.model_dump(by_alias=False)) for edge in value.edges),
        outputs=tuple(
            WorkflowOutput(**output.model_dump(by_alias=False)) for output in value.outputs
        ),
        inputs=tuple(WorkflowInput(**item.model_dump(by_alias=True)) for item in value.inputs),
    )


def _response(value: WorkflowDefinition) -> WorkflowResponse:
    return WorkflowResponse(
        id=value.id,
        name=value.name,
        graph=GraphModel.model_validate(asdict(value.graph)),
        version=value.version,
        created_at=value.created_at,
        updated_at=value.updated_at,
    )


def _run_response(value: WorkflowRun) -> WorkflowRunResponse:
    return WorkflowRunResponse(
        id=value.id,
        workflow_id=value.workflow_id,
        definition_version=value.definition_version,
        status=value.status,
        snapshot=dict(value.snapshot),
        execution=dict(value.execution),
        initiator_subject=value.initiator_subject,
        created_at=value.created_at,
    )


def create_workflow_router(
    identity: IdentityModule,
    workflows: WorkflowDefinitionModule,
    runs: WorkflowRunModule | None = None,
    artifacts: ArtifactModule | None = None,
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

    if runs is not None:

        @router.post(
            "/{workflow_id}/runs/{run_id}/execute",
            response_model=WorkflowRunResponse,
        )
        async def execute_run(
            project_id: str, workflow_id: str, run_id: str, request_context: Context
        ) -> WorkflowRunResponse:
            try:
                existing = await runs.load(
                    ProjectAccess(request_context.subject), project_id, run_id
                )
                if existing.workflow_id != workflow_id:
                    raise WorkflowNotFound
                item = await runs.execute(
                    ProjectAccess(request_context.subject), project_id, run_id
                )
            except WorkflowNotFound as error:
                raise HTTPException(status_code=404, detail="Run is unavailable.") from error
            except WorkflowRunConflict as error:
                raise HTTPException(status_code=409, detail=str(error)) from error
            except WorkflowValidationError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
            return _run_response(item)

        @router.post(
            "/{workflow_id}/runs/prepare",
            response_model=WorkflowRunResponse,
            status_code=status.HTTP_201_CREATED,
        )
        async def prepare_run(
            project_id: str,
            workflow_id: str,
            body: PrepareRunRequest,
            request_context: Context,
        ) -> WorkflowRunResponse:
            try:
                item = await runs.prepare(
                    ProjectAccess(request_context.subject),
                    project_id,
                    workflow_id,
                    body.idempotency_key,
                    expected_version=body.expected_version,
                    workflow_inputs=body.workflow_inputs,
                )
            except WorkflowNotFound as error:
                raise HTTPException(status_code=404, detail="Workflow is unavailable.") from error
            except WorkflowRunConflict as error:
                raise HTTPException(status_code=409, detail=str(error)) from error
            except WorkflowValidationError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
            return _run_response(item)

        @router.get("/{workflow_id}/runs", response_model=list[WorkflowRunResponse])
        async def list_runs(
            project_id: str, workflow_id: str, request_context: Context
        ) -> list[WorkflowRunResponse]:
            try:
                items = await runs.list(
                    ProjectAccess(request_context.subject), project_id, workflow_id
                )
            except WorkflowNotFound as error:
                raise HTTPException(status_code=404, detail="Workflow is unavailable.") from error
            return [_run_response(item) for item in items]

        @router.get("/{workflow_id}/runs/{run_id}", response_model=WorkflowRunResponse)
        async def load_run(
            project_id: str, workflow_id: str, run_id: str, request_context: Context
        ) -> WorkflowRunResponse:
            try:
                item = await runs.load(ProjectAccess(request_context.subject), project_id, run_id)
                if item.workflow_id != workflow_id:
                    raise WorkflowNotFound
            except WorkflowNotFound as error:
                raise HTTPException(status_code=404, detail="Run is unavailable.") from error
            return _run_response(item)

        @router.get("/{workflow_id}/runs/{run_id}/outputs/{output_name}/image")
        async def load_image(
            project_id: str,
            workflow_id: str,
            run_id: str,
            output_name: str,
            request_context: Context,
        ) -> Response:
            try:
                run = await runs.load(ProjectAccess(request_context.subject), project_id, run_id)
                if run.workflow_id != workflow_id:
                    raise WorkflowNotFound
                image = await runs.load_image(
                    ProjectAccess(request_context.subject), project_id, run_id, output_name
                )
            except WorkflowNotFound as error:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Image is unavailable."
                ) from error
            return Response(
                content=image.data,
                media_type=image.mime_type,
                headers={
                    "Cache-Control": "private, no-store",
                    "X-Content-Type-Options": "nosniff",
                },
            )

        if artifacts is not None:

            @router.post(
                "/{workflow_id}/runs/{run_id}/outputs/{output_name}/artifact",
                response_model=ArtifactDocument,
                status_code=status.HTTP_201_CREATED,
            )
            async def save_image_artifact(
                project_id: str,
                workflow_id: str,
                run_id: str,
                output_name: str,
                request_context: Context,
            ) -> ArtifactDocument:
                try:
                    run = await runs.load(
                        ProjectAccess(request_context.subject), project_id, run_id
                    )
                    if run.workflow_id != workflow_id:
                        raise WorkflowNotFound
                    image = await runs.load_image(
                        ProjectAccess(request_context.subject),
                        project_id,
                        run_id,
                        output_name,
                    )
                    return await artifacts.create(
                        ArtifactUserActionAccess(
                            subject=request_context.subject,
                            user_action_id=request_context.request_id,
                        ),
                        project_id,
                        ArtifactDraft(
                            type="agent-hub.image",
                            title=f"Workflow image · {output_name[:80]}",
                            summary=f"{output_name} from Workflow Run {run_id}.",
                            plugin_id="agent-hub",
                            plugin_version="1.0",
                            schema_id="agent-hub.image",
                            schema_version="1.0",
                            payload={
                                "kind": "image",
                                "mimeType": image.mime_type,
                                "dataBase64": image.data_base64,
                                "altText": image.alt_text,
                                "source": {
                                    "kind": "workflowOutput",
                                    "workflowId": workflow_id,
                                    "runId": run_id,
                                    "outputName": output_name,
                                },
                            },
                        ),
                    )
                except WorkflowNotFound as error:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND, detail="Image is unavailable."
                    ) from error
                except ArtifactNotFound as error:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND, detail="Project is unavailable."
                    ) from error

    return router
