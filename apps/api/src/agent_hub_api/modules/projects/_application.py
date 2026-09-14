from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from agent_hub_api.modules.identity import RequestContext
from agent_hub_api.settings import Settings


@dataclass(frozen=True, slots=True)
class Project:
    id: str
    name: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class Thread:
    id: str
    project_id: str
    title: str
    created_at: datetime
    updated_at: datetime


class ProjectNotFound(Exception):
    """No Project is visible in the caller's identity scope."""


class ThreadNotFound(Exception):
    """No Thread is visible in the caller's Project and identity scope."""


class ProjectStore(Protocol):
    async def create(self, subject: str, project: Project) -> Project: ...

    async def list(self, subject: str) -> Sequence[Project]: ...

    async def load(self, subject: str, project_id: str) -> Project | None: ...

    async def create_thread(self, subject: str, thread: Thread) -> Thread | None: ...

    async def list_threads(self, subject: str, project_id: str) -> Sequence[Thread]: ...

    async def load_thread(self, subject: str, project_id: str, thread_id: str) -> Thread | None: ...


class ProjectModule:
    """Own Project creation and identity-scoped discovery."""

    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    async def create(self, context: RequestContext, name: str) -> Project:
        normalized_name = name.strip()
        if not normalized_name or len(normalized_name) > 120:
            raise ValueError("Project name must contain between 1 and 120 characters")

        now = datetime.now(UTC)
        return await self._store.create(
            context.subject,
            Project(
                id=str(uuid4()),
                name=normalized_name,
                created_at=now,
                updated_at=now,
            ),
        )

    async def list(self, context: RequestContext) -> Sequence[Project]:
        return await self._store.list(context.subject)

    async def load(self, context: RequestContext, project_id: str) -> Project:
        project = await self._store.load(context.subject, project_id)
        if project is None:
            raise ProjectNotFound
        return project

    async def create_thread(self, context: RequestContext, project_id: str, title: str) -> Thread:
        normalized_title = title.strip()
        if not normalized_title or len(normalized_title) > 160:
            raise ValueError("Thread title must contain between 1 and 160 characters")

        now = datetime.now(UTC)
        thread = await self._store.create_thread(
            context.subject,
            Thread(
                id=str(uuid4()),
                project_id=project_id,
                title=normalized_title,
                created_at=now,
                updated_at=now,
            ),
        )
        if thread is None:
            raise ProjectNotFound
        return thread

    async def list_threads(self, context: RequestContext, project_id: str) -> Sequence[Thread]:
        await self.load(context, project_id)
        return await self._store.list_threads(context.subject, project_id)

    async def load_thread(self, context: RequestContext, project_id: str, thread_id: str) -> Thread:
        thread = await self._store.load_thread(context.subject, project_id, thread_id)
        if thread is None:
            raise ThreadNotFound
        return thread


class MemoryProjectStore:
    def __init__(self) -> None:
        self._projects: dict[str, tuple[str, Project]] = {}
        self._threads: dict[str, tuple[str, Thread]] = {}

    async def create(self, subject: str, project: Project) -> Project:
        self._projects[project.id] = (subject, project)
        return project

    async def list(self, subject: str) -> Sequence[Project]:
        return tuple(project for owner, project in self._projects.values() if owner == subject)

    async def load(self, subject: str, project_id: str) -> Project | None:
        owned_project = self._projects.get(project_id)
        if owned_project is None or owned_project[0] != subject:
            return None
        return owned_project[1]

    async def create_thread(self, subject: str, thread: Thread) -> Thread | None:
        if await self.load(subject, thread.project_id) is None:
            return None
        self._threads[thread.id] = (subject, thread)
        return thread

    async def list_threads(self, subject: str, project_id: str) -> Sequence[Thread]:
        return tuple(
            thread
            for owner, thread in self._threads.values()
            if owner == subject and thread.project_id == project_id
        )

    async def load_thread(self, subject: str, project_id: str, thread_id: str) -> Thread | None:
        owned_thread = self._threads.get(thread_id)
        if owned_thread is None or owned_thread[0] != subject:
            return None
        thread = owned_thread[1]
        if thread.project_id != project_id:
            return None
        return thread


class PostgresProjectStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def _connect(self) -> AsyncConnection[dict[str, object]]:
        return await AsyncConnection.connect(
            str(self._settings.database_url),
            connect_timeout=self._settings.database_connect_timeout_seconds,
            row_factory=dict_row,
        )

    async def create(self, subject: str, project: Project) -> Project:
        connection = await self._connect()
        async with connection:
            await connection.execute(
                """
                INSERT INTO users (subject)
                VALUES (%s)
                ON CONFLICT (subject) DO NOTHING
                """,
                (subject,),
            )
            cursor = await connection.execute(
                """
                INSERT INTO projects (id, owner_subject, name, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, name, created_at, updated_at
                """,
                (
                    project.id,
                    subject,
                    project.name,
                    project.created_at,
                    project.updated_at,
                ),
            )
            saved = await cursor.fetchone()
            assert saved is not None
            return Project(**saved)  # type: ignore[arg-type]

    async def list(self, subject: str) -> Sequence[Project]:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """
                SELECT id, name, created_at, updated_at
                FROM projects
                WHERE owner_subject = %s
                ORDER BY updated_at DESC, id
                """,
                (subject,),
            )
            return [Project(**row) for row in await cursor.fetchall()]  # type: ignore[arg-type]

    async def load(self, subject: str, project_id: str) -> Project | None:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """
                SELECT id, name, created_at, updated_at
                FROM projects
                WHERE id = %s AND owner_subject = %s
                """,
                (project_id, subject),
            )
            row = await cursor.fetchone()
            return None if row is None else Project(**row)  # type: ignore[arg-type]

    async def create_thread(self, subject: str, thread: Thread) -> Thread | None:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """
                INSERT INTO threads (id, project_id, title, created_at, updated_at)
                SELECT %s, projects.id, %s, %s, %s
                FROM projects
                WHERE projects.id = %s AND projects.owner_subject = %s
                RETURNING id, project_id, title, created_at, updated_at
                """,
                (
                    thread.id,
                    thread.title,
                    thread.created_at,
                    thread.updated_at,
                    thread.project_id,
                    subject,
                ),
            )
            row = await cursor.fetchone()
            return None if row is None else Thread(**row)  # type: ignore[arg-type]

    async def list_threads(self, subject: str, project_id: str) -> Sequence[Thread]:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """
                SELECT threads.id, threads.project_id, threads.title,
                       threads.created_at, threads.updated_at
                FROM threads
                JOIN projects ON projects.id = threads.project_id
                WHERE threads.project_id = %s AND projects.owner_subject = %s
                ORDER BY threads.updated_at DESC, threads.id
                """,
                (project_id, subject),
            )
            return [Thread(**row) for row in await cursor.fetchall()]  # type: ignore[arg-type]

    async def load_thread(self, subject: str, project_id: str, thread_id: str) -> Thread | None:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """
                SELECT threads.id, threads.project_id, threads.title,
                       threads.created_at, threads.updated_at
                FROM threads
                JOIN projects ON projects.id = threads.project_id
                WHERE threads.id = %s
                  AND threads.project_id = %s
                  AND projects.owner_subject = %s
                """,
                (thread_id, project_id, subject),
            )
            row = await cursor.fetchone()
            return None if row is None else Thread(**row)  # type: ignore[arg-type]


def create_memory_project_module() -> ProjectModule:
    return ProjectModule(MemoryProjectStore())


def create_postgres_project_module(settings: Settings) -> ProjectModule:
    return ProjectModule(PostgresProjectStore(settings))
