from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from psycopg import AsyncConnection
from psycopg.rows import class_row

from agent_hub_api.modules.identity import RequestContext
from agent_hub_api.settings import Settings


@dataclass(frozen=True, slots=True)
class Project:
    id: str
    name: str
    created_at: datetime
    updated_at: datetime


class ProjectNotFound(Exception):
    """No Project is visible in the caller's identity scope."""


class ProjectStore(Protocol):
    async def create(self, subject: str, project: Project) -> Project: ...

    async def list(self, subject: str) -> Sequence[Project]: ...

    async def load(self, subject: str, project_id: str) -> Project | None: ...


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


class MemoryProjectStore:
    def __init__(self) -> None:
        self._projects: dict[str, tuple[str, Project]] = {}

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


class PostgresProjectStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def _connect(self) -> AsyncConnection[Project]:
        return await AsyncConnection.connect(
            str(self._settings.database_url),
            connect_timeout=self._settings.database_connect_timeout_seconds,
            row_factory=class_row(Project),
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
            return saved

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
            return await cursor.fetchall()

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
            return await cursor.fetchone()


def create_memory_project_module() -> ProjectModule:
    return ProjectModule(MemoryProjectStore())


def create_postgres_project_module(settings: Settings) -> ProjectModule:
    return ProjectModule(PostgresProjectStore(settings))
