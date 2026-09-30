from __future__ import annotations

import fnmatch
import posixpath
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from agent_hub_api.modules.projects import ProjectAccess, ProjectModule, ProjectNotFound
from agent_hub_api.settings import Settings

ARTIFACT_ROOT = "/.artifacts"


@dataclass(frozen=True, slots=True)
class ProjectFile:
    project_id: str
    path: str
    content: str
    version: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ProjectFileAccess:
    """Identity scope required to read a Project file through the user-facing Interface."""

    subject: str


@dataclass(frozen=True, slots=True)
class ProjectFileSearchMatch:
    path: str
    line: int
    text: str


@dataclass(frozen=True, slots=True)
class ProjectFileSearchResult:
    matches: tuple[ProjectFileSearchMatch, ...]
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class ProjectFileGlobEntry:
    path: str
    is_dir: bool
    size: int
    modified_at: str


@dataclass(frozen=True, slots=True)
class ProjectFileGlobResult:
    matches: tuple[ProjectFileGlobEntry, ...]
    truncated: bool = False


class ProjectFileError(Exception):
    """Base expected Project Files failure."""


class InvalidProjectFilePath(ProjectFileError):
    """The requested virtual path is not a safe canonical absolute path."""


class InvalidProjectFilePattern(ProjectFileError):
    """The requested Project file search or glob pattern is not safe."""


class ProjectFileLimitExceeded(ProjectFileError):
    """A configured Project file or content limit would be exceeded."""


class ProjectFileNotFound(ProjectFileError):
    """The requested Project file does not exist."""


class ProjectFileConflict(ProjectFileError):
    """An exact-string edit could not be applied to the current content."""


class ProjectFileAlreadyExists(ProjectFileError):
    """A direct user save cannot replace an existing Project file."""


class ReservedProjectFilePath(ProjectFileError):
    """Only the Artifact Module may mutate the reserved Artifact namespace."""


class ProjectFileStore(Protocol):
    async def list(self, project_id: str) -> Sequence[ProjectFile]: ...

    async def load(self, project_id: str, path: str) -> ProjectFile | None: ...

    async def write(
        self, project_id: str, path: str, content: str, *, max_files: int
    ) -> ProjectFile: ...

    async def create(
        self, project_id: str, path: str, content: str, *, max_files: int
    ) -> ProjectFile: ...

    async def edit(
        self,
        project_id: str,
        path: str,
        old_string: str,
        new_string: str,
        *,
        max_bytes: int,
        replace_all: bool,
    ) -> tuple[ProjectFile, int]: ...

    async def delete(self, project_id: str, path: str) -> bool: ...


def _normalize_path(path: str) -> str:
    if not path.startswith("/") or "\x00" in path or len(path) > 1024:
        raise InvalidProjectFilePath(
            "Path must be an absolute virtual path of at most 1024 characters"
        )
    if any(part == ".." for part in path.split("/")):
        raise InvalidProjectFilePath("Path traversal with '..' is not allowed")
    normalized = posixpath.normpath(path)
    if normalized == "." or not normalized.startswith("/"):
        raise InvalidProjectFilePath("Path is not a valid absolute virtual path")
    return normalized


def _normalize_file_path(path: str) -> str:
    normalized = _normalize_path(path)
    if normalized == "/":
        raise InvalidProjectFilePath("The virtual filesystem root is a directory")
    return normalized


def _require_mutable(path: str) -> None:
    if path == ARTIFACT_ROOT or path.startswith(f"{ARTIFACT_ROOT}/"):
        raise ReservedProjectFilePath(
            "Artifact paths can only be changed through the Artifact Module"
        )


def _replacement(
    content: str, old_string: str, new_string: str, *, replace_all: bool
) -> tuple[str, int]:
    if old_string == new_string:
        raise ProjectFileConflict("old_string and new_string must differ")
    occurrences = content.count(old_string)
    if occurrences == 0:
        raise ProjectFileConflict("old_string was not found in the current file")
    if occurrences > 1 and not replace_all:
        raise ProjectFileConflict(
            f"old_string appears {occurrences} times; set replace_all to replace every occurrence"
        )
    count = occurrences if replace_all else 1
    return content.replace(old_string, new_string, count), count


class ProjectFilesModule:
    """Owns safe, limited, Project-scoped file behavior behind one Interface."""

    def __init__(
        self,
        store: ProjectFileStore,
        projects: ProjectModule,
        *,
        max_bytes: int,
        max_files: int,
        search_max_matches: int,
    ) -> None:
        self._store = store
        self._projects = projects
        self._max_bytes = max_bytes
        self._max_files = max_files
        self._search_max_matches = search_max_matches

    async def list(self, project_id: str) -> tuple[ProjectFile, ...]:
        return tuple(await self._store.list(project_id))

    async def load(self, project_id: str, path: str) -> ProjectFile:
        normalized = _normalize_file_path(path)
        file = await self._store.load(project_id, normalized)
        if file is None:
            raise ProjectFileNotFound
        return file

    async def preview(
        self, access: ProjectFileAccess, project_id: str, path: str
    ) -> ProjectFile:
        """Load a Project file only after confirming the caller can see its Project."""
        try:
            await self._projects.load(ProjectAccess(subject=access.subject), project_id)
        except ProjectNotFound as error:
            raise ProjectFileNotFound from error
        return await self.load(project_id, path)

    async def list_visible(
        self, access: ProjectFileAccess, project_id: str
    ) -> tuple[ProjectFile, ...]:
        try:
            await self._projects.load(ProjectAccess(subject=access.subject), project_id)
        except ProjectNotFound as error:
            raise ProjectFileNotFound from error
        return tuple(
            file
            for file in await self.list(project_id)
            if not (file.path == ARTIFACT_ROOT or file.path.startswith(f"{ARTIFACT_ROOT}/"))
        )

    async def write(self, project_id: str, path: str, content: str) -> ProjectFile:
        normalized = _normalize_file_path(path)
        _require_mutable(normalized)
        self._check_content(content)
        return await self._store.write(project_id, normalized, content, max_files=self._max_files)

    async def create_visible(
        self, access: ProjectFileAccess, project_id: str, path: str, content: str
    ) -> ProjectFile:
        """Create a new Project file after user authorization, never replacing one."""
        try:
            await self._projects.load(ProjectAccess(subject=access.subject), project_id)
        except ProjectNotFound as error:
            raise ProjectFileNotFound from error
        normalized = _normalize_file_path(path)
        _require_mutable(normalized)
        self._check_content(content)
        return await self._store.create(
            project_id, normalized, content, max_files=self._max_files
        )

    async def delete_visible(
        self, access: ProjectFileAccess, project_id: str, path: str
    ) -> None:
        """Delete one ordinary Project File after user authorization."""
        try:
            await self._projects.load(ProjectAccess(subject=access.subject), project_id)
        except ProjectNotFound as error:
            raise ProjectFileNotFound from error
        normalized = _normalize_file_path(path)
        _require_mutable(normalized)
        if not await self._store.delete(project_id, normalized):
            raise ProjectFileNotFound

    async def edit(
        self,
        project_id: str,
        path: str,
        old_string: str,
        new_string: str,
        *,
        replace_all: bool = False,
    ) -> tuple[ProjectFile, int]:
        normalized = _normalize_file_path(path)
        _require_mutable(normalized)
        if not old_string:
            raise ProjectFileConflict("old_string must not be empty")
        current = await self.load(project_id, normalized)
        replacement, _ = _replacement(
            current.content, old_string, new_string, replace_all=replace_all
        )
        self._check_content(replacement)
        return await self._store.edit(
            project_id,
            normalized,
            old_string,
            new_string,
            max_bytes=self._max_bytes,
            replace_all=replace_all,
        )

    async def search(
        self,
        project_id: str,
        pattern: str,
        *,
        path: str = "/",
        file_glob: str | None = None,
        max_count: int | None = None,
    ) -> ProjectFileSearchResult:
        base = _normalize_path(path)
        matches: list[ProjectFileSearchMatch] = []
        requested = self._search_max_matches if max_count is None else max(max_count, 0)
        cap = min(requested, self._search_max_matches)
        for file in await self._store.list(project_id):
            if not _is_beneath(file.path, base) or not _matches_glob(file.path, file_glob):
                continue
            for number, line in enumerate(file.content.splitlines(), start=1):
                if pattern in line:
                    if len(matches) == cap:
                        return ProjectFileSearchResult(tuple(matches), truncated=True)
                    matches.append(ProjectFileSearchMatch(file.path, number, line))
        return ProjectFileSearchResult(tuple(matches))

    async def glob(
        self, project_id: str, pattern: str, *, path: str = "/"
    ) -> ProjectFileGlobResult:
        base = _normalize_path(path)
        if any(part == ".." for part in pattern.split("/")):
            raise InvalidProjectFilePattern("glob pattern cannot contain '..'")
        matches = [
            ProjectFileGlobEntry(
                path=file.path,
                is_dir=False,
                size=len(file.content.encode("utf-8")),
                modified_at=file.updated_at.isoformat(),
            )
            for file in await self._store.list(project_id)
            if _is_beneath(file.path, base) and _matches_glob(file.path, pattern, base=base)
        ]
        truncated = len(matches) > self._search_max_matches
        return ProjectFileGlobResult(
            tuple(matches[: self._search_max_matches]), truncated=truncated
        )

    def _check_content(self, content: str) -> None:
        if len(content.encode("utf-8")) > self._max_bytes:
            raise ProjectFileLimitExceeded(
                f"Project file exceeds the configured {self._max_bytes}-byte limit"
            )


def _is_beneath(path: str, base: str) -> bool:
    return base == "/" or path == base or path.startswith(f"{base.rstrip('/')}/")


def _matches_glob(path: str, pattern: str | None, *, base: str = "/") -> bool:
    if pattern is None:
        return True
    relative = path.removeprefix(base.rstrip("/")).lstrip("/")
    if "/" not in pattern.lstrip("/"):
        return fnmatch.fnmatch(posixpath.basename(path), pattern)
    return fnmatch.fnmatch(relative, pattern.lstrip("/"))


class MemoryProjectFileStore:
    def __init__(self) -> None:
        self._files: dict[tuple[str, str], ProjectFile] = {}

    async def list(self, project_id: str) -> Sequence[ProjectFile]:
        return tuple(
            sorted(
                (file for (owner, _), file in self._files.items() if owner == project_id),
                key=lambda file: file.path,
            )
        )

    async def load(self, project_id: str, path: str) -> ProjectFile | None:
        return self._files.get((project_id, path))

    async def write(
        self, project_id: str, path: str, content: str, *, max_files: int
    ) -> ProjectFile:
        key = (project_id, path)
        existing = self._files.get(key)
        if existing is None and len(await self.list(project_id)) >= max_files:
            raise ProjectFileLimitExceeded("Project file-count limit reached")
        now = datetime.now(UTC)
        saved = (
            ProjectFile(project_id, path, content, 1, now, now)
            if existing is None
            else replace(existing, content=content, version=existing.version + 1, updated_at=now)
        )
        self._files[key] = saved
        return saved

    async def create(
        self, project_id: str, path: str, content: str, *, max_files: int
    ) -> ProjectFile:
        if (project_id, path) in self._files:
            raise ProjectFileAlreadyExists
        if len(await self.list(project_id)) >= max_files:
            raise ProjectFileLimitExceeded("Project file-count limit reached")
        now = datetime.now(UTC)
        saved = ProjectFile(project_id, path, content, 1, now, now)
        self._files[(project_id, path)] = saved
        return saved

    async def edit(
        self,
        project_id: str,
        path: str,
        old_string: str,
        new_string: str,
        *,
        max_bytes: int,
        replace_all: bool,
    ) -> tuple[ProjectFile, int]:
        existing = await self.load(project_id, path)
        if existing is None:
            raise ProjectFileNotFound
        content, occurrences = _replacement(
            existing.content, old_string, new_string, replace_all=replace_all
        )
        if len(content.encode("utf-8")) > max_bytes:
            raise ProjectFileLimitExceeded(
                f"Project file exceeds the configured {max_bytes}-byte limit"
            )
        saved = replace(
            existing,
            content=content,
            version=existing.version + 1,
            updated_at=datetime.now(UTC),
        )
        self._files[(project_id, path)] = saved
        return saved, occurrences

    async def delete(self, project_id: str, path: str) -> bool:
        return self._files.pop((project_id, path), None) is not None


class PostgresProjectFileStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def _connect(self) -> AsyncConnection[dict[str, object]]:
        return await AsyncConnection.connect(
            str(self._settings.database_url),
            connect_timeout=self._settings.database_connect_timeout_seconds,
            row_factory=dict_row,
        )

    @staticmethod
    def _file(row: dict[str, object]) -> ProjectFile:
        return ProjectFile(**row)  # type: ignore[arg-type]

    async def list(self, project_id: str) -> Sequence[ProjectFile]:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """
                SELECT project_id, path, content, version, created_at, updated_at
                FROM project_files WHERE project_id = %s ORDER BY path
                """,
                (project_id,),
            )
            return tuple(self._file(row) for row in await cursor.fetchall())

    async def load(self, project_id: str, path: str) -> ProjectFile | None:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """
                SELECT project_id, path, content, version, created_at, updated_at
                FROM project_files WHERE project_id = %s AND path = %s
                """,
                (project_id, path),
            )
            row = await cursor.fetchone()
            return None if row is None else self._file(row)

    async def delete(self, project_id: str, path: str) -> bool:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                "DELETE FROM project_files WHERE project_id = %s AND path = %s",
                (project_id, path),
            )
            return cursor.rowcount == 1

    async def write(
        self, project_id: str, path: str, content: str, *, max_files: int
    ) -> ProjectFile:
        connection = await self._connect()
        async with connection:
            # Serialize new-file quota checks per Project. The Project row is a
            # stable lock target even when this write creates the first file.
            project = await connection.execute(
                "SELECT 1 FROM projects WHERE id = %s FOR UPDATE", (project_id,)
            )
            if await project.fetchone() is None:
                raise ProjectFileNotFound
            exists = await connection.execute(
                "SELECT 1 FROM project_files WHERE project_id = %s AND path = %s",
                (project_id, path),
            )
            if await exists.fetchone() is None:
                count = await connection.execute(
                    "SELECT count(*) AS count FROM project_files WHERE project_id = %s",
                    (project_id,),
                )
                count_row = await count.fetchone()
                assert count_row is not None
                count_value = count_row["count"]
                assert isinstance(count_value, int)
                if count_value >= max_files:
                    raise ProjectFileLimitExceeded("Project file-count limit reached")
            now = datetime.now(UTC)
            cursor = await connection.execute(
                """
                INSERT INTO project_files
                    (project_id, path, content, version, created_at, updated_at)
                VALUES (%s, %s, %s, 1, %s, %s)
                ON CONFLICT (project_id, path) DO UPDATE
                SET content = EXCLUDED.content,
                    version = project_files.version + 1,
                    updated_at = EXCLUDED.updated_at
                RETURNING project_id, path, content, version, created_at, updated_at
                """,
                (project_id, path, content, now, now),
            )
            row = await cursor.fetchone()
            assert row is not None
            return self._file(row)

    async def create(
        self, project_id: str, path: str, content: str, *, max_files: int
    ) -> ProjectFile:
        connection = await self._connect()
        async with connection:
            project = await connection.execute(
                "SELECT 1 FROM projects WHERE id = %s FOR UPDATE", (project_id,)
            )
            if await project.fetchone() is None:
                raise ProjectFileNotFound
            existing = await connection.execute(
                "SELECT 1 FROM project_files WHERE project_id = %s AND path = %s",
                (project_id, path),
            )
            if await existing.fetchone() is not None:
                raise ProjectFileAlreadyExists
            count = await connection.execute(
                "SELECT count(*) AS count FROM project_files WHERE project_id = %s",
                (project_id,),
            )
            count_row = await count.fetchone()
            assert count_row is not None
            count_value = count_row["count"]
            assert isinstance(count_value, int)
            if count_value >= max_files:
                raise ProjectFileLimitExceeded("Project file-count limit reached")
            now = datetime.now(UTC)
            cursor = await connection.execute(
                """
                INSERT INTO project_files
                    (project_id, path, content, version, created_at, updated_at)
                VALUES (%s, %s, %s, 1, %s, %s)
                RETURNING project_id, path, content, version, created_at, updated_at
                """,
                (project_id, path, content, now, now),
            )
            row = await cursor.fetchone()
            assert row is not None
            return self._file(row)

    async def edit(
        self,
        project_id: str,
        path: str,
        old_string: str,
        new_string: str,
        *,
        max_bytes: int,
        replace_all: bool,
    ) -> tuple[ProjectFile, int]:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """
                SELECT project_id, path, content, version, created_at, updated_at
                FROM project_files
                WHERE project_id = %s AND path = %s
                FOR UPDATE
                """,
                (project_id, path),
            )
            row = await cursor.fetchone()
            if row is None:
                raise ProjectFileNotFound
            current = self._file(row)
            content, occurrences = _replacement(
                current.content, old_string, new_string, replace_all=replace_all
            )
            if len(content.encode("utf-8")) > max_bytes:
                raise ProjectFileLimitExceeded(
                    f"Project file exceeds the configured {max_bytes}-byte limit"
                )
            saved_at = datetime.now(UTC)
            updated = await connection.execute(
                """
                UPDATE project_files
                SET content = %s, version = version + 1, updated_at = %s
                WHERE project_id = %s AND path = %s
                RETURNING project_id, path, content, version, created_at, updated_at
                """,
                (content, saved_at, project_id, path),
            )
            saved = await updated.fetchone()
            assert saved is not None
            return self._file(saved), occurrences


def create_memory_project_files(
    projects: ProjectModule, *, max_bytes: int = 1_000_000
) -> ProjectFilesModule:
    return ProjectFilesModule(
        MemoryProjectFileStore(),
        projects,
        max_bytes=max_bytes,
        max_files=1_000,
        search_max_matches=200,
    )


def create_postgres_project_files(
    settings: Settings, projects: ProjectModule
) -> ProjectFilesModule:
    return ProjectFilesModule(
        PostgresProjectFileStore(settings),
        projects,
        max_bytes=settings.project_file_max_bytes,
        max_files=settings.project_file_max_files,
        search_max_matches=settings.project_file_search_max_matches,
    )
