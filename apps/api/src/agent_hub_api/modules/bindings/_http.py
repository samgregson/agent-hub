from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from agent_hub_api.modules.bindings._application import (
    BindingModule,
    BindingUnavailable,
    FileBinding,
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


class FileBindingRequest(_Model):
    source_path: str = Field(min_length=2, max_length=1024)
    expected_file_version: int = Field(ge=1)
    expected_binding_version: int | None = Field(default=None, ge=1)


class FileBindingResponse(_Model):
    id: str
    definition_id: str
    argument: str
    source_path: str
    expected_file_version: int
    cardinality: str
    version: int


def _response(binding: FileBinding) -> FileBindingResponse:
    return FileBindingResponse(
        id=binding.id,
        definition_id=binding.definition_id,
        argument=binding.argument,
        source_path=f"/project{binding.source_path}",
        expected_file_version=binding.expected_file_version,
        cardinality="scalar-to-selected-records",
        version=binding.version,
    )


def create_binding_router(identity: IdentityModule, bindings: BindingModule) -> APIRouter:
    router = APIRouter(prefix="/projects/{project_id}/batch-definitions", tags=["bindings"])

    async def context(request: Request) -> RequestContext:
        try:
            return identity.resolve(IdentityEvidence(headers=request.headers))
        except IdentityUnavailable as error:
            raise HTTPException(
                status_code=401, detail="Authenticated platform identity is required"
            ) from error

    Context = Annotated[RequestContext, Depends(context)]

    @router.post(
        "/{definition_id}/file-binding",
        response_model=FileBindingResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def bind_file(
        project_id: str,
        definition_id: str,
        body: FileBindingRequest,
        request_context: Context,
    ) -> FileBindingResponse:
        try:
            binding = await bindings.bind_file(
                ProjectAccess(subject=request_context.subject),
                project_id,
                definition_id,
                body.source_path.removeprefix("/project"),
                body.expected_file_version,
            )
        except BindingUnavailable as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return _response(binding)

    @router.get("/{definition_id}/file-binding", response_model=FileBindingResponse)
    async def load_file(
        project_id: str, definition_id: str, request_context: Context
    ) -> FileBindingResponse:
        try:
            binding = await bindings.load(
                ProjectAccess(subject=request_context.subject), project_id, definition_id
            )
        except BindingUnavailable as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return _response(binding)

    @router.put("/{definition_id}/file-binding", response_model=FileBindingResponse)
    async def rebind_file(
        project_id: str,
        definition_id: str,
        body: FileBindingRequest,
        request_context: Context,
    ) -> FileBindingResponse:
        if body.expected_binding_version is None:
            raise HTTPException(status_code=422, detail="Binding version is required.")
        try:
            binding = await bindings.rebind_file(
                ProjectAccess(subject=request_context.subject),
                project_id,
                definition_id,
                body.source_path.removeprefix("/project"),
                body.expected_file_version,
                expected_binding_version=body.expected_binding_version,
            )
        except BindingUnavailable as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return _response(binding)

    return router
