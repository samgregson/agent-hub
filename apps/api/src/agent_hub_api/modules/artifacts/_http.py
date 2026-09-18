from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from agent_hub_api.contracts import ArtifactCatalog, ArtifactDocument
from agent_hub_api.modules.artifacts._application import (
    ArtifactAccess,
    ArtifactModule,
    ArtifactNotFound,
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

    @router.get("", response_model=ArtifactCatalog)
    async def discover(project_id: str, context: Context) -> ArtifactCatalog:
        try:
            documents = await artifacts.discover(
                ArtifactAccess(subject=context.subject), project_id
            )
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
                ArtifactAccess(subject=context.subject),
                project_id,
                artifact_id,
            )
        except ArtifactNotFound as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found"
            ) from error

    return router
