from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from agent_hub_api.modules.projects import ProjectAccess, ProjectModule


@dataclass(frozen=True, slots=True)
class PluginTool:
    name: str
    read_only: bool


@dataclass(frozen=True, slots=True)
class PluginManifest:
    id: str
    name: str
    version: str
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


class PluginNotAvailable(Exception):
    """The Plugin is absent from the reviewed deployment catalog."""


class PluginNotEnabled(Exception):
    """The Plugin is not enabled for the authorized Project."""


class PluginToolNotAllowed(Exception):
    """The Plugin did not declare the requested tool."""


class PluginEnablementStore(Protocol):
    async def enabled_plugin_ids(self, project_id: str) -> Sequence[str]: ...

    async def enable(self, project_id: str, plugin_id: str) -> None: ...


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
