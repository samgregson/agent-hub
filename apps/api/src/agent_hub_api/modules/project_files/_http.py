from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from agent_hub_api.contracts import ProjectFilePreview
from agent_hub_api.modules.identity import (
    IdentityEvidence,
    IdentityModule,
    IdentityUnavailable,
    RequestContext,
)
from agent_hub_api.modules.project_files._application import (
    InvalidProjectFilePath,
    ProjectFileAccess,
    ProjectFileNotFound,
    ProjectFilesModule,
)


def create_project_files_router(
    identity: IdentityModule,
    project_files: ProjectFilesModule,
) -> APIRouter:
    router = APIRouter(prefix="/projects/{project_id}/files", tags=["project-files"])

    async def request_context(request: Request) -> RequestContext:
        try:
            return identity.resolve(IdentityEvidence(headers=request.headers))
        except IdentityUnavailable as error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authenticated platform identity is required",
            ) from error

    Context = Annotated[RequestContext, Depends(request_context)]

    @router.get("", response_model=ProjectFilePreview)
    async def preview_file(
        project_id: str,
        context: Context,
        path: Annotated[str, Query(min_length=10, max_length=1032)],
    ) -> ProjectFilePreview:
        if not path.startswith("/project/"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Project file previews require a /project/ path",
            )
        try:
            file = await project_files.preview(
                ProjectFileAccess(subject=context.subject),
                project_id,
                path.removeprefix("/project"),
            )
        except (InvalidProjectFilePath, ProjectFileNotFound) as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Project file not found"
            ) from error
        return ProjectFilePreview(
            path=f"/project{file.path}", content=file.content, version=file.version
        )

    return router
