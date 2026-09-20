from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from agent_hub_api.contracts import ArtifactCatalog, ArtifactDocument
from agent_hub_api.modules.artifacts._application import (
    ArtifactAccess,
    ArtifactAppUnavailable,
    ArtifactModule,
    ArtifactNotFound,
    ArtifactPluginReplacementInvalid,
    ArtifactUserActionAccess,
    ArtifactVersionConflict,
)
from agent_hub_api.modules.identity import (
    IdentityEvidence,
    IdentityModule,
    IdentityUnavailable,
    RequestContext,
)


def create_artifact_router(identity: IdentityModule, artifacts: ArtifactModule) -> APIRouter:
    """Adapt authorized Artifact discovery and document loading to HTTP."""
    router = APIRouter(prefix="/projects/{project_id}/artifacts", tags=["artifacts"])

    async def request_context(request: Request) -> RequestContext:
        try:
            return identity.resolve(IdentityEvidence(headers=request.headers))
        except IdentityUnavailable as error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authenticated platform identity is required",
            ) from error

    Context = Annotated[RequestContext, Depends(request_context)]

    class AppOperationRequest(BaseModel):
        model_config = ConfigDict(alias_generator=to_camel, extra="forbid", populate_by_name=True)

        name: str
        arguments: dict[str, object]
        expected_version: int

    def artifact_access(context: RequestContext) -> ArtifactAccess:
        return ArtifactAccess(subject=context.subject)

    @router.get("", response_model=ArtifactCatalog)
    async def discover(project_id: str, context: Context) -> ArtifactCatalog:
        try:
            documents = await artifacts.discover(artifact_access(context), project_id)
        except ArtifactNotFound as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
            ) from error
        return ArtifactCatalog.model_validate(
            {
                "artifacts": [
                    {
                        "id": document.artifact.id.root,
                        "type": document.artifact.type,
                        "documentVersion": document.artifact.document_version,
                        "title": document.artifact.title,
                        "summary": document.artifact.summary,
                        "pluginId": document.artifact.plugin.id,
                        "pluginVersion": document.artifact.plugin.version,
                    }
                    for document in documents
                ]
            }
        )

    @router.get("/{artifact_id}", response_model=ArtifactDocument)
    async def load(project_id: str, artifact_id: str, context: Context) -> ArtifactDocument:
        try:
            return await artifacts.load(
                artifact_access(context),
                project_id,
                artifact_id,
            )
        except ArtifactNotFound as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found"
            ) from error

    @router.get("/{artifact_id}/app")
    async def app_resource(project_id: str, artifact_id: str, context: Context) -> Response:
        try:
            resource = await artifacts.app_resource(
                artifact_access(context), project_id, artifact_id
            )
        except ArtifactNotFound as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found"
            ) from error
        except ArtifactAppUnavailable as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="A compatible Artifact App is unavailable",
            ) from error
        return Response(
            content=resource.html,
            media_type="text/html",
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": (
                    "default-src 'none'; base-uri 'none'; connect-src 'none'; "
                    "font-src data:; form-action 'none'; frame-ancestors 'self'; "
                    "frame-src 'none'; img-src data:; script-src 'unsafe-inline'; "
                    "style-src 'unsafe-inline'"
                ),
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.post("/{artifact_id}/app/actions", response_model=ArtifactDocument)
    async def app_action(
        project_id: str,
        artifact_id: str,
        operation: AppOperationRequest,
        context: Context,
    ) -> ArtifactDocument:
        try:
            return await artifacts.apply_app_operation(
                ArtifactUserActionAccess(
                    subject=context.subject,
                    user_action_id=str(uuid4()),
                ),
                project_id,
                artifact_id,
                expected_version=operation.expected_version,
                tool_name=operation.name,
                arguments=operation.arguments,
            )
        except ArtifactNotFound as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found"
            ) from error
        except ArtifactVersionConflict as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The Artifact changed; reload before editing.",
            ) from error
        except (ArtifactAppUnavailable, ArtifactPluginReplacementInvalid) as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="The App operation is not permitted.",
            ) from error

    return router
