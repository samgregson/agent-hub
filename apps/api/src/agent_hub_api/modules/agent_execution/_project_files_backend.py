"""Deep Agents adapter for Agent Hub's Project Files Interface.

This is deliberately owned by Agent Execution: ``BackendProtocol`` is a Deep
Agents implementation detail, while Project Files remains usable without the
agent library.
"""

from __future__ import annotations

import posixpath

from deepagents.backends import BackendProtocol, CompositeBackend, StateBackend
from deepagents.backends.protocol import (
    EditResult,
    FileDownloadResponse,
    FileInfo,
    FileUploadResponse,
    GlobResult,
    GrepResult,
    LsResult,
    ReadResult,
    WriteResult,
)

from agent_hub_api.modules.project_files import (
    InvalidProjectFilePath,
    InvalidProjectFilePattern,
    ProjectFile,
    ProjectFileError,
    ProjectFileNotFound,
    ProjectFilesModule,
)


def create_project_files_backend(
    project_files: ProjectFilesModule, project_id: str
) -> BackendProtocol:
    """Bind one authorized Project's files to Deep Agents' virtual filesystem."""
    return CompositeBackend(
        default=_RestrictedRootBackend(),
        routes={
            "/project/": _ProjectBackend(project_files, project_id),
            "/scratch/": StateBackend(),
        },
    )


def _normalize_directory(path: str) -> str:
    if not path.startswith("/") or "\x00" in path or len(path) > 1024:
        raise InvalidProjectFilePath
    if any(part == ".." for part in path.split("/")):
        raise InvalidProjectFilePath
    normalized = posixpath.normpath(path)
    if normalized == "." or not normalized.startswith("/"):
        raise InvalidProjectFilePath
    return normalized


def _file_info(file: ProjectFile) -> FileInfo:
    return {
        "path": file.path,
        "is_dir": False,
        "size": len(file.content.encode("utf-8")),
        "modified_at": file.updated_at.isoformat(),
    }


def _error_text(error: ProjectFileError) -> str:
    return str(error) or error.__class__.__name__


class _ProjectBackend(BackendProtocol):
    def __init__(self, files: ProjectFilesModule, project_id: str) -> None:
        self._files = files
        self._project_id = project_id

    async def als(self, path: str) -> LsResult:
        try:
            base = _normalize_directory(path)
        except InvalidProjectFilePath:
            return LsResult(error="Error: invalid path")
        entries: list[FileInfo] = []
        directories: set[str] = set()
        prefix = "/" if base == "/" else f"{base}/"
        for file in await self._files.list(self._project_id):
            if not file.path.startswith(prefix):
                continue
            relative = file.path[len(prefix) :]
            if "/" in relative:
                directories.add(f"{prefix}{relative.split('/', 1)[0]}/")
            elif relative:
                entries.append(_file_info(file))
        entries.extend(
            {"path": directory, "is_dir": True, "size": 0} for directory in sorted(directories)
        )
        return LsResult(entries=sorted(entries, key=lambda entry: entry["path"]))

    async def aread(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        try:
            file = await self._files.load(self._project_id, file_path)
        except InvalidProjectFilePath:
            return ReadResult(error="Error: invalid path")
        except ProjectFileNotFound:
            return ReadResult(error=f"Error: File '{file_path}' not found")
        if not file.content or not file.content.strip():
            return ReadResult(file_data={"content": file.content, "encoding": "utf-8"})
        if limit <= 0:
            return ReadResult(
                file_data={"content": "", "encoding": "utf-8"}, no_lines_requested=True
            )
        lines = file.content.splitlines(keepends=True)
        start = max(offset, 0)
        if start >= len(lines):
            return ReadResult(
                error=f"Line offset {offset} exceeds file length ({len(lines)} lines)"
            )
        selected = lines[start : start + limit]
        end = start + len(selected)
        return ReadResult(
            file_data={
                "content": "".join(selected).replace("\r\n", "\n").replace("\r", "\n"),
                "encoding": "utf-8",
            },
            start_line=start + 1,
            end_line=end,
            next_offset=end if end < len(lines) else None,
            total_lines=len(lines),
        )

    async def awrite(self, file_path: str, content: str) -> WriteResult:
        try:
            file = await self._files.write(self._project_id, file_path, content)
            return WriteResult(path=file.path)
        except ProjectFileError as error:
            return WriteResult(error=f"Error: {_error_text(error)}")

    async def aedit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        try:
            file, occurrences = await self._files.edit(
                self._project_id,
                file_path,
                old_string,
                new_string,
                replace_all=replace_all,
            )
            return EditResult(path=file.path, occurrences=occurrences)
        except ProjectFileError as error:
            return EditResult(error=f"Error: {_error_text(error)}")

    async def agrep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
        *,
        max_count: int | None = None,
    ) -> GrepResult:
        try:
            result = await self._files.search(
                self._project_id,
                pattern,
                path=path or "/",
                file_glob=glob,
                max_count=max_count,
            )
            return GrepResult(
                matches=[
                    {"path": match.path, "line": match.line, "text": match.text}
                    for match in result.matches
                ],
                truncated=result.truncated,
            )
        except InvalidProjectFilePath:
            return GrepResult(error="Error: invalid path")

    async def aglob(self, pattern: str, path: str | None = None) -> GlobResult:
        try:
            result = await self._files.glob(self._project_id, pattern, path=path or "/")
            return GlobResult(
                matches=[
                    {
                        "path": entry.path,
                        "is_dir": entry.is_dir,
                        "size": entry.size,
                        "modified_at": entry.modified_at,
                    }
                    for entry in result.matches
                ],
                truncated=result.truncated,
                truncation_reason="budget" if result.truncated else None,
            )
        except (InvalidProjectFilePath, InvalidProjectFilePattern):
            return GlobResult(error="Error: invalid path")

    async def aupload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        responses: list[FileUploadResponse] = []
        for path, content in files:
            try:
                text = content.decode("utf-8")
                await self._files.write(self._project_id, path, text)
                responses.append(FileUploadResponse(path=path))
            except UnicodeDecodeError:
                responses.append(FileUploadResponse(path=path, error="invalid_path"))
            except ProjectFileError as error:
                responses.append(FileUploadResponse(path=path, error=_error_text(error)))
        return responses

    async def adownload_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        responses: list[FileDownloadResponse] = []
        for path in paths:
            try:
                file = await self._files.load(self._project_id, path)
                responses.append(FileDownloadResponse(path=path, content=file.content.encode()))
            except ProjectFileNotFound:
                responses.append(FileDownloadResponse(path=path, error="file_not_found"))
            except InvalidProjectFilePath:
                responses.append(FileDownloadResponse(path=path, error="invalid_path"))
        return responses


class _RestrictedRootBackend(BackendProtocol):
    _ERROR = "Error: files must be stored under /project or /scratch"

    def ls(self, path: str) -> LsResult:
        return LsResult(
            entries=[] if path == "/" else None, error=None if path == "/" else self._ERROR
        )

    async def als(self, path: str) -> LsResult:
        return self.ls(path)

    async def aread(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        return ReadResult(error=self._ERROR)

    async def awrite(self, file_path: str, content: str) -> WriteResult:
        return WriteResult(error=self._ERROR)

    async def aedit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        return EditResult(error=self._ERROR)

    async def agrep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
        *,
        max_count: int | None = None,
    ) -> GrepResult:
        return GrepResult(error=self._ERROR)

    async def aglob(self, pattern: str, path: str | None = None) -> GlobResult:
        return GlobResult(error=self._ERROR)
