from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from agent_hub_api.modules.projects import ProjectAccess, ProjectModule
from agent_hub_api.settings import Settings


@dataclass(frozen=True, slots=True)
class PluginTool:
    name: str
    read_only: bool


@dataclass(frozen=True, slots=True)
class PluginManifest:
    id: str
    name: str
    version: str
    endpoint: str
    tools: tuple[PluginTool, ...]


@dataclass(frozen=True, slots=True)
class PluginCapability:
    plugin_id: str
    tool_name: str

    @property
    def qualified_name(self) -> str:
        return f"{self.plugin_id}.{self.tool_name}"


@dataclass(frozen=True, slots=True)
class PluginToolResult:
    content: tuple[str, ...]
    structured_content: Mapping[str, object] | None


@dataclass(frozen=True, slots=True)
class PluginSelection:
    manifest: PluginManifest
    enabled: bool


class PluginNotAvailable(Exception):
    """The Plugin is absent from the reviewed deployment catalog."""


class PluginNotEnabled(Exception):
    """The Plugin is not enabled for the authorized Project."""


class PluginToolNotAllowed(Exception):
    """The Plugin did not declare the requested tool."""


class PluginEnablementStore(Protocol):
    async def enabled_plugin_ids(self, project_id: str) -> Sequence[str]: ...

    async def enable(self, project_id: str, plugin_id: str) -> None: ...

    async def disable(self, project_id: str, plugin_id: str) -> None: ...


class PluginClient(Protocol):
    async def call_tool(
        self, tool_name: str, arguments: Mapping[str, object]
    ) -> PluginToolResult: ...


class PluginGatewayModule:
    """Authorize catalogued Plugin capabilities before their MCP transport is used."""

    def __init__(
        self,
        projects: ProjectModule,
        catalog: Sequence[PluginManifest],
        enablements: PluginEnablementStore,
        clients: Mapping[str, PluginClient],
    ) -> None:
        self._projects = projects
        self._catalog = {manifest.id: manifest for manifest in catalog}
        self._enablements = enablements
        self._clients = dict(clients)

    async def enable(self, access: ProjectAccess, project_id: str, plugin_id: str) -> None:
        await self._projects.load(access, project_id)
        if plugin_id not in self._catalog:
            raise PluginNotAvailable
        await self._enablements.enable(project_id, plugin_id)

    async def disable(self, access: ProjectAccess, project_id: str, plugin_id: str) -> None:
        await self._projects.load(access, project_id)
        if plugin_id not in self._catalog:
            raise PluginNotAvailable
        await self._enablements.disable(project_id, plugin_id)

    async def selections(
        self, access: ProjectAccess, project_id: str
    ) -> tuple[PluginSelection, ...]:
        await self._projects.load(access, project_id)
        enabled = set(await self._enablements.enabled_plugin_ids(project_id))
        return tuple(
            PluginSelection(manifest=manifest, enabled=manifest.id in enabled)
            for manifest in self._catalog.values()
        )

    async def capabilities(
        self, access: ProjectAccess, project_id: str
    ) -> tuple[PluginCapability, ...]:
        await self._projects.load(access, project_id)
        enabled = set(await self._enablements.enabled_plugin_ids(project_id))
        return tuple(
            PluginCapability(plugin_id=manifest.id, tool_name=tool.name)
            for manifest in self._catalog.values()
            if manifest.id in enabled
            for tool in manifest.tools
        )

    async def call(
        self,
        access: ProjectAccess,
        project_id: str,
        plugin_id: str,
        tool_name: str,
        arguments: Mapping[str, object],
    ) -> PluginToolResult:
        await self._projects.load(access, project_id)
        manifest = self._catalog.get(plugin_id)
        if manifest is None:
            raise PluginNotAvailable
        if plugin_id not in await self._enablements.enabled_plugin_ids(project_id):
            raise PluginNotEnabled
        if tool_name not in {tool.name for tool in manifest.tools}:
            raise PluginToolNotAllowed
        client = self._clients.get(plugin_id)
        if client is None:
            raise PluginNotAvailable
        return await client.call_tool(tool_name, arguments)


class MemoryPluginEnablementStore:
    def __init__(self) -> None:
        self._enabled: dict[str, set[str]] = {}

    async def enabled_plugin_ids(self, project_id: str) -> Sequence[str]:
        return tuple(sorted(self._enabled.get(project_id, set())))

    async def enable(self, project_id: str, plugin_id: str) -> None:
        self._enabled.setdefault(project_id, set()).add(plugin_id)

    async def disable(self, project_id: str, plugin_id: str) -> None:
        self._enabled.setdefault(project_id, set()).discard(plugin_id)


class PostgresPluginEnablementStore:
    """Persist the reviewed Plugin IDs selected by each authorized Project."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def _connect(self) -> AsyncConnection[dict[str, object]]:
        return await AsyncConnection.connect(
            str(self._settings.database_url),
            connect_timeout=self._settings.database_connect_timeout_seconds,
            row_factory=dict_row,
        )

    async def enabled_plugin_ids(self, project_id: str) -> Sequence[str]:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """
                SELECT plugin_id
                FROM project_plugin_selections
                WHERE project_id = %s
                ORDER BY plugin_id
                """,
                (project_id,),
            )
            return tuple(str(row["plugin_id"]) for row in await cursor.fetchall())

    async def enable(self, project_id: str, plugin_id: str) -> None:
        connection = await self._connect()
        async with connection:
            await connection.execute(
                """
                INSERT INTO project_plugin_selections (project_id, plugin_id)
                VALUES (%s, %s)
                ON CONFLICT (project_id, plugin_id) DO NOTHING
                """,
                (project_id, plugin_id),
            )

    async def disable(self, project_id: str, plugin_id: str) -> None:
        connection = await self._connect()
        async with connection:
            await connection.execute(
                """
                DELETE FROM project_plugin_selections
                WHERE project_id = %s AND plugin_id = %s
                """,
                (project_id, plugin_id),
            )


def create_postgres_plugin_gateway(
    settings: Settings,
    projects: ProjectModule,
    clients: Mapping[str, PluginClient],
) -> PluginGatewayModule:
    """Compose the deployment-controlled initial catalog.

    The endpoint remains source-controlled; it is never supplied by a browser
    request or a Project configuration record.
    """
    return PluginGatewayModule(
        projects,
        catalog=(
            PluginManifest(
                id="foundation-fixture",
                name="Foundation fixture",
                version="0.1.0",
                endpoint="http://foundation-fixture:8000/mcp",
                tools=(PluginTool(name="foundation_status", read_only=True),),
            ),
        ),
        enablements=PostgresPluginEnablementStore(settings),
        clients=clients,
    )
