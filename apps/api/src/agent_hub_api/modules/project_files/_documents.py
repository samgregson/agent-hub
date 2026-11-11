"""Original document bytes and protected searchable Project File projections."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from agent_hub_api.modules.projects import ProjectAccess, ProjectModule, ProjectNotFound
from agent_hub_api.settings import Settings

from ._application import (
    ProjectFileAccess,
    ProjectFileLimitExceeded,
    ProjectFileNotFound,
    ProjectFileStore,
)

DOCUMENT_ROOT = "/.documents"
MAX_DOCUMENT_BYTES = 10_000_000


class DocumentInvalid(ValueError):
    """An unsupported, invalid or oversized document/conversion."""


@dataclass(frozen=True)
class DocumentRecord:
    summary: dict[str, Any]
    source: bytes


class DocumentStore(Protocol):
    async def list(self, project_id: str) -> list[dict[str, Any]]: ...
    async def load(self, project_id: str, document_id: str) -> DocumentRecord: ...
    async def create(
        self, project_id: str, record: DocumentRecord, files: dict[str, str], max_files: int
    ) -> None: ...
    async def delete(self, project_id: str, document_id: str) -> None: ...


class DocumentConverter:
    async def run(
        self, source: bytes, extension: str, *, page: int | None = None
    ) -> dict[str, Any]:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "agent_hub_api.modules.project_files._document_worker",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        payload = json.dumps(
            {
                "source": base64.b64encode(source).decode(),
                "extension": extension,
                "action": "convert" if page is None else "render",
                "page": page,
            }
        ).encode()
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(payload), timeout=40)
        except BaseException:
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        try:
            result = json.loads(stdout)
            if not isinstance(result, dict):
                raise DocumentInvalid("Unexpected document conversion response.")
            if process.returncode or "error" in result:
                raise DocumentInvalid(str(result.get("error", "Document conversion failed.")))
            return result
        except (ValueError, TypeError) as error:
            raise DocumentInvalid("Document conversion failed: " + str(error)[:500]) from error


class ProjectDocumentsModule:
    def __init__(
        self,
        projects: ProjectModule,
        store: DocumentStore,
        *,
        max_files: int = 1000,
        max_file_bytes: int = 1_000_000,
        converter: DocumentConverter | None = None,
    ) -> None:
        self._projects, self._store = projects, store
        self._max_files, self._max_file_bytes = max_files, max_file_bytes
        self._converter = converter or DocumentConverter()
        self._conversion_slots = asyncio.Semaphore(2)

    async def authorize(self, access: ProjectFileAccess, project_id: str) -> None:
        try:
            await self._projects.load(ProjectAccess(subject=access.subject), project_id)
        except ProjectNotFound as error:
            raise ProjectFileNotFound from error

    async def list(self, access: ProjectFileAccess, project_id: str) -> list[dict[str, Any]]:
        await self.authorize(access, project_id)
        return await self._store.list(project_id)

    async def load(
        self, access: ProjectFileAccess, project_id: str, document_id: str
    ) -> DocumentRecord:
        await self.authorize(access, project_id)
        return await self._store.load(project_id, document_id)

    async def upload(
        self, access: ProjectFileAccess, project_id: str, name: str, source: bytes
    ) -> dict[str, Any]:
        await self.authorize(access, project_id)
        if not name or len(name) > 180 or any(c in name for c in "/\\\x00\r\n"):
            raise DocumentInvalid(
                "Use a filename without directory components, at most 180 characters."
            )
        extension = "." + name.rsplit(".", 1)[-1].lower()
        if extension not in {".pdf", ".docx"} or not 0 < len(source) <= MAX_DOCUMENT_BYTES:
            raise DocumentInvalid("Upload a PDF or DOCX containing 1–10000000 bytes.")
        if not source.startswith(b"%PDF-" if extension == ".pdf" else b"PK\x03\x04"):
            raise DocumentInvalid("The file contents do not match the document type.")
        async with self._conversion_slots:
            try:
                converted = await self._converter.run(source, extension)
            except TimeoutError as error:
                raise DocumentInvalid("Conversion timed out; split the document.") from error
        document_id = str(uuid4())
        root = f"{DOCUMENT_ROOT}/{document_id}"
        pages = converted["pages"]
        is_pdf = extension == ".pdf"
        summary = {
            "id": document_id,
            "name": name,
            "version": 1,
            "mediaType": "application/pdf"
            if is_pdf
            else "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "sizeBytes": len(source),
            "sourceSha256": hashlib.sha256(source).hexdigest(),
            "pageCount": len(pages) if is_pdf else None,
            "status": (
                ("needs_ocr" if is_pdf else "needs_review")
                if not any(text.strip() for text in pages)
                else "partial"
                if is_pdf and not all(text.strip() for text in pages)
                else "ready"
            ),
            "warnings": converted["warnings"],
            "converter": converted["converter"],
            "filePath": "/project" + root + "/manifest.json",
            "textPath": "/project" + root + "/text.md",
            "originalPath": "/project" + root + "/source" + extension,
            "createdAt": datetime.now(UTC).isoformat(),
        }
        markdown = f"# {name}\n\nSource SHA-256: {summary['sourceSha256']}\n\n"
        markdown += "\n\n".join(
            f"## Page {i + 1}\n\n{text}" if is_pdf else text for i, text in enumerate(pages)
        )
        files = {
            root + "/text.md": markdown,
            root + "/manifest.json": json.dumps(summary, ensure_ascii=False),
        }
        if is_pdf:
            files.update(
                {
                    f"{root}/pages/{i + 1:03}.md": f"# {name} — page {i + 1}\n\n{text}"
                    for i, text in enumerate(pages)
                }
            )
        if any(len(content.encode()) > self._max_file_bytes for content in files.values()):
            raise ProjectFileLimitExceeded(
                "Extracted document exceeds the Project text file limit."
            )
        await self._store.create(
            project_id, DocumentRecord(summary, source), files, self._max_files
        )
        return summary

    async def page_image(
        self, access: ProjectFileAccess, project_id: str, document_id: str, page: int
    ) -> bytes:
        record = await self.load(access, project_id, document_id)
        count = record.summary["pageCount"]
        if count is None or not 1 <= page <= count:
            raise DocumentInvalid("Choose an existing PDF page, starting at 1.")
        async with self._conversion_slots:
            try:
                rendered = await self._converter.run(record.source, ".pdf", page=page)
            except TimeoutError as error:
                raise DocumentInvalid("Page rendering timed out.") from error
        return base64.b64decode(rendered["image"], validate=True)

    async def delete(self, access: ProjectFileAccess, project_id: str, document_id: str) -> None:
        await self.load(access, project_id, document_id)
        await self._store.delete(project_id, document_id)


class MemoryDocumentStore:
    def __init__(self, files: ProjectFileStore) -> None:
        self._files = files
        self._records: dict[tuple[str, str], DocumentRecord] = {}
        self._lock = asyncio.Lock()

    async def list(self, project_id: str) -> list[dict[str, Any]]:
        return [r.summary for (p, _), r in self._records.items() if p == project_id]

    async def load(self, project_id: str, document_id: str) -> DocumentRecord:
        record = self._records.get((project_id, document_id))
        if record is None:
            raise ProjectFileNotFound
        return record

    async def create(
        self, project_id: str, record: DocumentRecord, files: dict[str, str], max_files: int
    ) -> None:
        async with self._lock:
            if len(await self._files.list(project_id)) + len(files) > max_files:
                raise ProjectFileLimitExceeded("Project file count limit exceeded.")
            for path, content in files.items():
                await self._files.create(project_id, path, content, max_files=max_files)
            self._records[(project_id, record.summary["id"])] = record

    async def delete(self, project_id: str, document_id: str) -> None:
        async with self._lock:
            del self._records[(project_id, document_id)]
            prefix = f"{DOCUMENT_ROOT}/{document_id}/"
            for file in await self._files.list(project_id):
                if file.path.startswith(prefix):
                    await self._files.delete(project_id, file.path)


class PostgresDocumentStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def list(self, project_id: str) -> list[dict[str, Any]]:
        async with await AsyncConnection.connect(
            str(self._settings.database_url), row_factory=dict_row
        ) as connection:
            rows = await connection.execute(
                "SELECT metadata FROM project_documents "
                "WHERE project_id=%s ORDER BY created_at DESC",
                (project_id,),
            )
            return [row["metadata"] for row in await rows.fetchall()]

    async def load(self, project_id: str, document_id: str) -> DocumentRecord:
        async with await AsyncConnection.connect(
            str(self._settings.database_url), row_factory=dict_row
        ) as connection:
            cursor = await connection.execute(
                "SELECT metadata, source FROM project_documents "
                "WHERE project_id=%s AND document_id=%s",
                (project_id, document_id),
            )
            row = await cursor.fetchone()
            if row is None:
                raise ProjectFileNotFound
            return DocumentRecord(row["metadata"], bytes(row["source"]))

    async def create(
        self, project_id: str, record: DocumentRecord, files: dict[str, str], max_files: int
    ) -> None:
        async with await AsyncConnection.connect(
            str(self._settings.database_url), row_factory=dict_row
        ) as connection:
            await connection.execute(
                "SELECT id FROM projects WHERE id=%s FOR UPDATE", (project_id,)
            )
            count = await connection.execute(
                "SELECT count(*) AS total FROM project_files WHERE project_id=%s", (project_id,)
            )
            row = await count.fetchone()
            assert row is not None
            if row["total"] + len(files) > max_files:
                raise ProjectFileLimitExceeded("Project file count limit exceeded.")
            await connection.execute(
                "INSERT INTO project_documents (project_id, document_id, source, metadata) "
                "VALUES (%s,%s,%s,%s::jsonb)",
                (project_id, record.summary["id"], record.source, json.dumps(record.summary)),
            )
            for path, content in files.items():
                await connection.execute(
                    "INSERT INTO project_files "
                    "(project_id,path,content,version,created_at,updated_at) "
                    "VALUES (%s,%s,%s,1,now(),now())",
                    (project_id, path, content),
                )

    async def delete(self, project_id: str, document_id: str) -> None:
        async with await AsyncConnection.connect(str(self._settings.database_url)) as connection:
            await connection.execute(
                "SELECT id FROM projects WHERE id=%s FOR UPDATE", (project_id,)
            )
            await connection.execute(
                "DELETE FROM project_documents WHERE project_id=%s AND document_id=%s",
                (project_id, document_id),
            )
            await connection.execute(
                "DELETE FROM project_files WHERE project_id=%s AND path LIKE %s",
                (project_id, f"{DOCUMENT_ROOT}/{document_id}/%"),
            )
