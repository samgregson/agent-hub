"""Read-only document discovery and visual inspection through Project Files."""

import base64
import json

from langchain_core.tools import BaseTool, tool

from agent_hub_api.modules.project_files import (
    DocumentInvalid,
    ProjectDocumentsModule,
    ProjectFileAccess,
    ProjectFileNotFound,
)


def document_tools(
    documents: ProjectDocumentsModule, project_id: str, subject: str
) -> list[BaseTool]:
    access = ProjectFileAccess(subject=subject)

    @tool
    async def list_project_documents(query: str = "", offset: int = 0, limit: int = 20) -> str:
        """Discover uploaded PDF/DOCX sources, Markdown paths and extraction warnings.

        Read filePath for full warnings; search textPath and sibling pages/NNN.md files.
        Originals are binary; view PDF pages with view_project_document_page.
        """
        if offset < 0 or not 1 <= limit <= 50:
            raise ValueError("Use offset >= 0 and limit between 1 and 50.")
        records = [
            item
            for item in await documents.list(access, project_id)
            if query.casefold() in item["name"].casefold()
        ]
        selected = records[offset : offset + limit]
        return json.dumps(
            {
                "documents": [
                    {key: value for key, value in item.items() if key != "warnings"}
                    | {"warningCount": len(item["warnings"])}
                    for item in selected
                ],
                "total": len(records),
                "nextOffset": offset + limit if offset + limit < len(records) else None,
            }
        )

    @tool
    async def view_project_document_page(document_id: str, page: int) -> list[dict[str, str]]:
        """Visually inspect one original PDF page (1-based) for tables and drawings.

        Does not perform OCR or modify the source. Cite the filename and page.
        DOCX has no stable PDF pages; its original remains downloadable.
        """
        try:
            record = await documents.load(access, project_id, document_id)
            png = await documents.page_image(access, project_id, document_id, page)
        except (ProjectFileNotFound, DocumentInvalid) as error:
            return [
                {
                    "type": "text",
                    "text": f"Document page unavailable: {error}. "
                    "Discover current documents and choose an existing PDF page.",
                }
            ]
        return [
            {
                "type": "text",
                "text": f"{record.summary['name']}, page {page}. "
                f"Source SHA-256: {record.summary['sourceSha256']}.",
            },
            {"type": "image", "base64": base64.b64encode(png).decode(), "mime_type": "image/png"},
        ]

    return [list_project_documents, view_project_document_page]
