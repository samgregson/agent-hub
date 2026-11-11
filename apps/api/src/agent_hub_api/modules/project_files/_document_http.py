"""Document uploads and original/page reads; all scoped to the selected Project."""

from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from agent_hub_api.modules.identity import (
    IdentityEvidence,
    IdentityModule,
    IdentityUnavailable,
    RequestContext,
)

from ._application import (
    ProjectFileAccess,
    ProjectFileLimitExceeded,
    ProjectFileNotFound,
    ProjectFilesModule,
)
from ._documents import MAX_DOCUMENT_BYTES, DocumentInvalid


def create_document_router(identity: IdentityModule, files: ProjectFilesModule) -> APIRouter:
    router = APIRouter(prefix="/projects/{project_id}/files/documents", tags=["documents"])
    documents = files.documents
    assert documents is not None

    async def context(request: Request) -> RequestContext:
        try:
            return identity.resolve(IdentityEvidence(headers=request.headers))
        except IdentityUnavailable as error:
            raise HTTPException(401, "Authenticated identity is required.") from error

    Context = Annotated[RequestContext, Depends(context)]

    @router.get("")
    async def list_documents(project_id: str, ctx: Context) -> list[dict[str, Any]]:
        try:
            return await documents.list(ProjectFileAccess(ctx.subject), project_id)
        except ProjectFileNotFound as error:
            raise HTTPException(404, "Project not found.") from error

    @router.post("", status_code=201)
    async def upload(
        project_id: str,
        request: Request,
        ctx: Context,
        filename: Annotated[str, Query(min_length=1, max_length=180)],
    ) -> dict[str, Any]:
        access = ProjectFileAccess(ctx.subject)
        try:
            await documents.authorize(access, project_id)
            source = bytearray()
            async for chunk in request.stream():
                source.extend(chunk)
                if len(source) > MAX_DOCUMENT_BYTES:
                    raise HTTPException(413, "Document exceeds 10000000 bytes.")
            return await documents.upload(access, project_id, filename, bytes(source))
        except ProjectFileNotFound as error:
            raise HTTPException(404, "Project not found.") from error
        except (DocumentInvalid, ProjectFileLimitExceeded) as error:
            raise HTTPException(422, str(error)) from error

    @router.get("/{document_id}")
    async def detail(project_id: str, document_id: str, ctx: Context) -> dict[str, Any]:
        try:
            return (
                await documents.load(ProjectFileAccess(ctx.subject), project_id, document_id)
            ).summary
        except ProjectFileNotFound as error:
            raise HTTPException(404, "Document not found.") from error

    @router.get("/{document_id}/original")
    async def original(project_id: str, document_id: str, ctx: Context) -> Response:
        try:
            record = await documents.load(ProjectFileAccess(ctx.subject), project_id, document_id)
        except ProjectFileNotFound as error:
            raise HTTPException(404, "Document not found.") from error
        return Response(
            record.source,
            media_type=record.summary["mediaType"],
            headers={
                "Content-Disposition": "attachment; filename*=UTF-8''"
                + quote(record.summary["name"], safe=""),
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "default-src 'none'; sandbox",
            },
        )

    @router.get("/{document_id}/pages/{page}/image")
    async def image(project_id: str, document_id: str, page: int, ctx: Context) -> Response:
        try:
            png = await documents.page_image(
                ProjectFileAccess(ctx.subject), project_id, document_id, page
            )
        except ProjectFileNotFound as error:
            raise HTTPException(404, "Document not found.") from error
        except DocumentInvalid as error:
            raise HTTPException(422, str(error)) from error
        return Response(
            png,
            media_type="image/png",
            headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
        )

    @router.delete("/{document_id}", status_code=204)
    async def delete(project_id: str, document_id: str, ctx: Context) -> None:
        try:
            await documents.delete(ProjectFileAccess(ctx.subject), project_id, document_id)
        except ProjectFileNotFound as error:
            raise HTTPException(404, "Document not found.") from error

    return router
