import hashlib
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from agent_hub_api.modules.identity import create_identity_module
from agent_hub_api.modules.project_files import (
    ProjectFileAccess,
    ReservedProjectFilePath,
    create_document_router,
    create_memory_project_files,
)
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module
from agent_hub_api.settings import Settings

FIXTURES = Path(__file__).parents[6] / "tests/fixtures/documents"


@pytest.mark.asyncio
async def test_pdf_upload_retains_original_and_exposes_searchable_protected_page_text() -> None:
    projects = create_memory_project_module()
    project = await projects.create(ProjectAccess("alice"), "Documents")
    files = create_memory_project_files(projects)
    app = FastAPI()
    app.include_router(
        create_document_router(
            create_identity_module(Settings(environment="test", fixed_identity_subject="alice")),
            files,
        )
    )
    root = f"/projects/{project.id}/files/documents"
    source = (FIXTURES / "bridge.pdf").read_bytes()
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.post(root, params={"filename": "bridge.pdf"}, content=source)
        assert response.status_code == 201, response.text
        document = response.json()
        assert document["pageCount"] == 2
        assert document["status"] == "ready"
        assert document["converter"] == "markitdown:0.1.9"
        assert document["sourceSha256"] == hashlib.sha256(source).hexdigest()
        url = f"{root}/{document['id']}"
        original = await client.get(url + "/original")
        assert original.content == source
        assert original.headers["content-type"] == "application/pdf"
        assert "attachment" in original.headers["content-disposition"]
        image = await client.get(url + "/pages/2/image")
        assert image.status_code == 200
        assert image.content.startswith(b"\x89PNG")
        assert (await client.get(url + "/pages/3/image")).status_code == 422
        text = await files.preview(
            ProjectFileAccess("alice"), project.id, document["textPath"].removeprefix("/project")
        )
        assert "## Page 1" in text.content and "## Page 2" in text.content
        results = await files.search(project.id, "12.5", path="/.documents")
        assert any(m.path.endswith("/pages/001.md") and "12.5" in m.text for m in results.matches)
        for method in ("write", "edit", "delete"):
            path = text.path
            with pytest.raises(ReservedProjectFilePath):
                if method == "write":
                    await files.write(project.id, path, "fabricated source")
                elif method == "edit":
                    await files.edit(project.id, path, "12.5", "100")
                else:
                    await files.delete_visible(ProjectFileAccess("alice"), project.id, path)
        outsider = await projects.create(ProjectAccess("bob"), "Private")
        assert (await client.get(f"/projects/{outsider.id}/files/documents")).status_code == 404
        assert (
            await client.get(f"/projects/{outsider.id}/files/documents/{document['id']}/original")
        ).status_code == 404
        assert (await client.get(root + "/unknown/original")).status_code == 404
        assert (await client.delete(url)).status_code == 204
        assert (await client.get(url + "/original")).status_code == 404
        assert not (await files.search(project.id, "12.5", path="/.documents")).matches


@pytest.mark.asyncio
async def test_docx_and_scanned_pdf_report_extraction_limits_without_invented_text() -> None:
    projects = create_memory_project_module()
    project = await projects.create(ProjectAccess("alice"), "Documents")
    files = create_memory_project_files(projects)
    docs = files.documents
    assert docs is not None
    owner = ProjectFileAccess("alice")
    docx = await docs.upload(
        owner, project.id, "criteria.docx", (FIXTURES / "criteria.docx").read_bytes()
    )
    assert docx["pageCount"] is None
    text = await files.load(project.id, docx["textPath"].removeprefix("/project"))
    assert "imposed load 3 kPa" in text.content
    scan = await docs.upload(owner, project.id, "scan.pdf", (FIXTURES / "scan.pdf").read_bytes())
    assert scan["status"] == "needs_ocr"
    assert "OCR" in scan["warnings"][0]
    assert (await docs.page_image(owner, project.id, scan["id"], 1)).startswith(b"\x89PNG")
    from ._documents import DocumentInvalid

    for name, source in [
        ("bad.pdf", b"not PDF"),
        ("../bridge.pdf", (FIXTURES / "bridge.pdf").read_bytes()),
        ("bad.docx", b"PK\x03\x04broken"),
    ]:
        with pytest.raises(DocumentInvalid):
            await docs.upload(owner, project.id, name, source)
    assert len(await docs.list(owner, project.id)) == 2
