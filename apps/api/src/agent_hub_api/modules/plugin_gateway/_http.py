from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from agent_hub_api.modules.identity import (
    IdentityEvidence,
    IdentityModule,
    IdentityUnavailable,
    RequestContext,
)
from agent_hub_api.modules.plugin_gateway import (
    PluginGatewayModule,
    PluginNotAvailable,
    PluginSelection,
)
from agent_hub_api.modules.projects import ProjectAccess, ProjectNotFound


class PluginToolResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    name: str
    read_only: bool


class PluginSelectionResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str
    name: str
    version: str
    enabled: bool
    tools: list[PluginToolResponse]


def _selection_response(selection: PluginSelection) -> PluginSelectionResponse:
    manifest = selection.manifest
    return PluginSelectionResponse(
        id=manifest.id,
        name=manifest.name,
        version=manifest.version,
        enabled=selection.enabled,
        tools=[
            PluginToolResponse(name=tool.name, read_only=tool.read_only) for tool in manifest.tools
        ],
    )


def create_plugin_gateway_router(
    identity: IdentityModule,
    gateway: PluginGatewayModule,
) -> APIRouter:
    router = APIRouter(prefix="/projects/{project_id}/plugins", tags=["plugins"])

    async def request_context(request: Request) -> RequestContext:
        try:
            return identity.resolve(IdentityEvidence(headers=request.headers))
        except IdentityUnavailable as error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authenticated platform identity is required",
            ) from error

    Context = Annotated[RequestContext, Depends(request_context)]

    def project_access(context: RequestContext) -> ProjectAccess:
        return ProjectAccess(subject=context.subject)

    @router.get("", response_model=list[PluginSelectionResponse])
    async def list_plugins(project_id: str, context: Context) -> list[PluginSelectionResponse]:
        try:
            selections = await gateway.selections(project_access(context), project_id)
        except ProjectNotFound as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
            ) from error
        return [_selection_response(selection) for selection in selections]

    @router.put("/{plugin_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def enable_plugin(project_id: str, plugin_id: str, context: Context) -> None:
        try:
            await gateway.enable(project_access(context), project_id, plugin_id)
        except ProjectNotFound as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
            ) from error
        except PluginNotAvailable as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Plugin not found"
            ) from error

    @router.delete("/{plugin_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def disable_plugin(project_id: str, plugin_id: str, context: Context) -> None:
        try:
            await gateway.disable(project_access(context), project_id, plugin_id)
        except ProjectNotFound as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
            ) from error
        except PluginNotAvailable as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Plugin not found"
            ) from error

    return router
