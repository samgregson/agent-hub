import asyncio
import json
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Protocol

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from jsonschema import ValidationError as JsonSchemaValidationError
from langchain_core.tools import BaseTool, StructuredTool
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from referencing import Registry

from agent_hub_api.modules.observability import trace_plugin_operation
from agent_hub_api.modules.projects import ProjectAccess, ProjectModule
from agent_hub_api.settings import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PluginTool:
    name: str
    read_only: bool
    repeat_safe: bool = False
    description: str = ""
    agent_visible: bool = True


@dataclass(frozen=True, slots=True)
class PluginManifest:
    id: str
    name: str
    version: str
    endpoint: str
    tools: tuple[PluginTool, ...]
    app_resource_uri: str | None = None
    app_tool_names: tuple[str, ...] = ()
    app_allow_wasm: bool = False


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
class PluginUiResource:
    """A reviewed MCP App HTML resource, ready for a sandboxed host."""

    uri: str
    html: str
    allow_wasm: bool = False

    @property
    def content_security_policy(self) -> str:
        wasm = " 'wasm-unsafe-eval'" if self.allow_wasm else ""
        return (
            "default-src 'none'; base-uri 'none'; connect-src 'none'; "
            "font-src data:; form-action 'none'; frame-ancestors 'self'; "
            f"frame-src 'none'; img-src data:; script-src 'unsafe-inline'{wasm}; "
            "style-src 'unsafe-inline'"
        )


@dataclass(frozen=True, slots=True)
class PluginDiscoveredTool:
    name: str
    description: str
    read_only: bool
    input_schema: Mapping[str, object] | None = None
    output_schema: Mapping[str, object] | None = None
    app_resource_uri: str | None = None


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


class PluginCallLimitExceeded(Exception):
    """A Plugin's process-local rate or concurrent call budget is exhausted."""


class PluginTransportError(Exception):
    """The reviewed Plugin did not return a usable MCP result."""


class PluginAppUnavailable(Exception):
    """The requested tool has no current, catalog-approved MCP App resource."""


class _PluginCallBudget:
    def __init__(self, *, max_concurrent: int, max_per_minute: int) -> None:
        self._max_concurrent = max_concurrent
        self._max_per_minute = max_per_minute
        self._active = 0
        self._starts: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def reserve(self) -> None:
        async with self._lock:
            now = time.monotonic()
            while self._starts and now - self._starts[0] >= 60:
                self._starts.popleft()
            if self._active >= self._max_concurrent or len(self._starts) >= self._max_per_minute:
                raise PluginCallLimitExceeded("The Plugin call limit was reached; retry later.")
            self._active += 1
            self._starts.append(now)

    async def release(self) -> None:
        async with self._lock:
            self._active -= 1


class PluginEnablementStore(Protocol):
    async def enabled_plugin_ids(self, project_id: str) -> Sequence[str]: ...

    async def enable(self, project_id: str, plugin_id: str) -> None: ...

    async def disable(self, project_id: str, plugin_id: str) -> None: ...


class PluginClient(Protocol):
    async def discover_tools(self) -> Sequence[PluginDiscoveredTool]: ...

    async def call_tool(
        self, tool_name: str, arguments: Mapping[str, object]
    ) -> PluginToolResult: ...

    async def read_ui_resource(self, resource_uri: str) -> PluginUiResource: ...


PluginResultRecorder = Callable[
    [
        PluginManifest,
        PluginTool,
        Mapping[str, object],
        PluginToolResult,
    ],
    Awaitable[Mapping[str, object] | None],
]


class PluginGatewayModule:
    """Authorize catalogued Plugin capabilities before their MCP transport is used."""

    def __init__(
        self,
        projects: ProjectModule,
        catalog: Sequence[PluginManifest],
        enablements: PluginEnablementStore,
        clients: Mapping[str, PluginClient],
        *,
        discovery_cache_seconds: float = 300,
        max_concurrent_calls: int = 8,
        max_calls_per_minute: int = 120,
    ) -> None:
        if max_concurrent_calls < 1 or max_calls_per_minute < 1:
            raise ValueError("Plugin call budgets must be positive")
        self._projects = projects
        self._catalog = {manifest.id: manifest for manifest in catalog}
        self._enablements = enablements
        self._clients = dict(clients)
        self._discovery_cache_seconds = discovery_cache_seconds
        self._discoveries: dict[str, tuple[float, tuple[PluginDiscoveredTool, ...]]] = {}
        self._budgets = {
            plugin_id: _PluginCallBudget(
                max_concurrent=max_concurrent_calls, max_per_minute=max_calls_per_minute
            )
            for plugin_id in self._catalog
        }

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
        return await self._call_enabled(project_id, plugin_id, tool_name, arguments)

    async def input_schema(
        self,
        access: ProjectAccess,
        project_id: str,
        plugin_id: str,
        tool_name: str,
    ) -> Mapping[str, object]:
        """Return an enabled, catalogued tool's discovered ordinary MCP input schema."""
        await self._projects.load(access, project_id)
        manifest = self._catalog.get(plugin_id)
        if manifest is None:
            raise PluginNotAvailable
        if plugin_id not in await self._enablements.enabled_plugin_ids(project_id):
            raise PluginNotEnabled
        if tool_name not in {tool.name for tool in manifest.tools}:
            raise PluginToolNotAllowed
        discovered = {tool.name: tool for tool in await self._discover(manifest)}
        tool = discovered.get(tool_name)
        if tool is None or tool.input_schema is None:
            raise PluginToolNotAllowed
        return tool.input_schema

    async def tool_version(
        self,
        access: ProjectAccess,
        project_id: str,
        plugin_id: str,
        tool_name: str,
    ) -> str:
        """Return the enabled catalogued version of one MCP tool's Plugin."""
        await self._projects.load(access, project_id)
        manifest = self._catalog.get(plugin_id)
        if manifest is None:
            raise PluginNotAvailable
        if plugin_id not in await self._enablements.enabled_plugin_ids(project_id):
            raise PluginNotEnabled
        if tool_name not in {tool.name for tool in manifest.tools}:
            raise PluginToolNotAllowed
        return manifest.version

    async def output_schema(
        self,
        access: ProjectAccess,
        project_id: str,
        plugin_id: str,
        tool_name: str,
        *,
        require_repeat_safe: bool = True,
    ) -> Mapping[str, object]:
        """Return an enabled batch tool's declared ordinary MCP output schema."""
        await self._projects.load(access, project_id)
        manifest = self._catalog.get(plugin_id)
        if manifest is None:
            raise PluginNotAvailable
        if plugin_id not in await self._enablements.enabled_plugin_ids(project_id):
            raise PluginNotEnabled
        tool = next((item for item in manifest.tools if item.name == tool_name), None)
        if tool is None or (require_repeat_safe and not tool.repeat_safe):
            raise PluginToolNotAllowed
        discovered = {item.name: item for item in await self._discover(manifest)}
        output_schema = discovered.get(tool_name)
        if output_schema is None or output_schema.output_schema is None:
            raise PluginToolNotAllowed("The batch tool has no declared MCP output schema.")
        return output_schema.output_schema

    async def batch_call(
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
        tool = next((item for item in manifest.tools if item.name == tool_name), None)
        if tool is None or not tool.repeat_safe:
            raise PluginToolNotAllowed("The tool is not approved for batch execution.")
        return await self._call_enabled(project_id, plugin_id, tool_name, arguments)

    async def read_ui_resource(
        self,
        access: ProjectAccess,
        project_id: str,
        plugin_id: str,
        resource_uri: str,
    ) -> PluginUiResource:
        """Load only the reviewed App resource of an enabled Plugin."""
        await self._projects.load(access, project_id)
        manifest = self._catalog.get(plugin_id)
        if manifest is None:
            raise PluginNotAvailable
        if plugin_id not in await self._enablements.enabled_plugin_ids(project_id):
            raise PluginNotEnabled
        if manifest.app_resource_uri != resource_uri:
            raise PluginToolNotAllowed
        client = self._clients.get(plugin_id)
        if client is None:
            raise PluginNotAvailable
        return await self._read_ui_resource(plugin_id, resource_uri)

    async def app_resource_for_tool(
        self,
        access: ProjectAccess,
        project_id: str,
        plugin_id: str,
        tool_name: str,
        expected_version: str,
    ) -> PluginUiResource:
        """Load the reviewed App linked to one enabled, captured MCP tool."""
        await self._projects.load(access, project_id)
        manifest = self._catalog.get(plugin_id)
        if manifest is None:
            raise PluginNotAvailable
        if plugin_id not in await self._enablements.enabled_plugin_ids(project_id):
            raise PluginNotEnabled
        if manifest.version != expected_version:
            raise PluginAppUnavailable
        if tool_name not in {tool.name for tool in manifest.tools}:
            raise PluginToolNotAllowed
        discovered = {tool.name: tool for tool in await self._discover(manifest)}
        tool = discovered.get(tool_name)
        resource_uri = tool.app_resource_uri if tool is not None else None
        if (
            resource_uri is None
            or resource_uri != manifest.app_resource_uri
            or not resource_uri.startswith("ui://")
        ):
            raise PluginAppUnavailable
        return await self._read_ui_resource(plugin_id, resource_uri)

    async def _read_ui_resource(self, plugin_id: str, resource_uri: str) -> PluginUiResource:
        client = self._clients.get(plugin_id)
        if client is None:
            raise PluginNotAvailable
        budget = self._budgets[plugin_id]
        await budget.reserve()
        try:
            async with trace_plugin_operation("mcp.app_resource", plugin_id):
                resource = await client.read_ui_resource(resource_uri)
                # Only deployment review grants WASM; never trust a server's request.
                return replace(resource, allow_wasm=self._catalog[plugin_id].app_allow_wasm)
        finally:
            await budget.release()

    async def _call_enabled(
        self,
        project_id: str,
        plugin_id: str,
        tool_name: str,
        arguments: Mapping[str, object],
    ) -> PluginToolResult:
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
        budget = self._budgets[plugin_id]
        await budget.reserve()
        try:
            async with trace_plugin_operation("mcp.tool", plugin_id):
                return await client.call_tool(tool_name, arguments)
        finally:
            await budget.release()

    async def agent_tools(
        self,
        project_id: str,
        *,
        on_success: PluginResultRecorder | None = None,
    ) -> tuple[BaseTool, ...]:
        """Return only currently enabled capabilities for an authorized Run.

        Agent Transport authorizes the Project before it starts a Run. This
        method deliberately does not accept browser-controlled identity input.
        """
        enabled = set(await self._enablements.enabled_plugin_ids(project_id))
        tools: list[BaseTool] = []
        for manifest in self._catalog.values():
            if manifest.id not in enabled:
                continue
            try:
                discovered = {tool.name: tool for tool in await self._discover(manifest)}
            except PluginTransportError:
                logger.warning("Skipping unavailable Plugin %s during agent setup", manifest.id)
                continue
            tools.extend(
                _agent_tool(
                    self,
                    project_id,
                    manifest,
                    plugin_tool,
                    discovered[plugin_tool.name],
                    on_success,
                )
                for plugin_tool in manifest.tools
                if plugin_tool.agent_visible and plugin_tool.name in discovered
            )
        return tuple(tools)

    async def programmatic_tools(
        self,
        access: ProjectAccess,
        project_id: str,
    ) -> tuple[BaseTool, ...]:
        """Expose only reviewed, server-declared read-only tools without auto-saving results."""
        await self._projects.load(access, project_id)
        enabled = set(await self._enablements.enabled_plugin_ids(project_id))
        tools = []
        for manifest in self._catalog.values():
            if manifest.id not in enabled:
                continue
            try:
                discovered = {tool.name: tool for tool in await self._discover(manifest)}
            except PluginTransportError:
                continue
            for target in manifest.tools:
                contract = discovered.get(target.name)
                if (
                    target.agent_visible
                    and target.read_only
                    and contract is not None
                    and contract.read_only
                ):
                    tools.append(
                        _programmatic_tool(self, access, project_id, manifest, target, contract)
                    )
        return tuple(tools)

    async def _discover(self, manifest: PluginManifest) -> tuple[PluginDiscoveredTool, ...]:
        cached = self._discoveries.get(manifest.id)
        now = time.monotonic()
        if cached is not None and now - cached[0] < self._discovery_cache_seconds:
            return cached[1]
        client = self._clients.get(manifest.id)
        if client is None:
            raise PluginNotAvailable
        allowed = {tool.name: tool for tool in manifest.tools}
        budget = self._budgets[manifest.id]
        await budget.reserve()
        try:
            async with trace_plugin_operation("mcp.discovery", manifest.id):
                discovered = tuple(
                    tool for tool in await client.discover_tools() if tool.name in allowed
                )
        finally:
            await budget.release()
        self._discoveries[manifest.id] = (now, discovered)
        return discovered


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
) -> PluginGatewayModule:
    """Compose the deployment-controlled initial catalog.

    The fixture endpoint is deployment-configured; it is never supplied by a
    browser request or a Project configuration record.
    """
    fixture = PluginManifest(
        id="foundation-fixture",
        name="Foundation fixture",
        version="0.1.0",
        endpoint=settings.foundation_fixture_url,
        tools=(
            PluginTool(name="foundation_status", read_only=True),
            PluginTool(name="render_template_value", read_only=True, repeat_safe=True),
            PluginTool(name="create_status_artifact", read_only=False, agent_visible=False),
            PluginTool(name="validate_status_artifact", read_only=True, agent_visible=False),
            PluginTool(name="set_status_artifact_status", read_only=False, agent_visible=False),
        ),
        app_resource_uri="ui://agent-hub-foundation/status.html",
        app_tool_names=("set_status_artifact_status",),
    )
    reference_calculation = PluginManifest(
        id="reference-calculation",
        name="Reference calculation",
        version="0.1.0",
        endpoint="http://reference-calculation:8000/mcp",
        tools=(
            PluginTool(name="calculate_cantilever_tip_load", read_only=False, repeat_safe=True),
            PluginTool(name="check_uniform_beam_deflection", read_only=False, repeat_safe=True),
            PluginTool(name="size_for_deflection", read_only=False, repeat_safe=True),
            PluginTool(name="draft_beam_review_note", read_only=False, repeat_safe=True),
        ),
        app_resource_uri="ui://agent-hub-reference-calculation/cantilever.html",
        app_tool_names=(),
    )
    calculation_source_object = PluginManifest(
        id="calculation-source-object",
        name="Calculation Source Object",
        version="0.1.0",
        endpoint="http://calculation-source-object:8000/mcp",
        tools=(PluginTool(name="run_calculation", read_only=False, repeat_safe=True),),
        app_resource_uri="ui://agent-hub-calculation-source-object/report.html",
        app_tool_names=(),
    )
    ifc_viewer = PluginManifest(
        id="ifc-viewer",
        name="IFC viewer",
        version="0.1.0",
        endpoint="http://ifc-viewer:8000/mcp",
        tools=(
            PluginTool(name="get_ifc_guide", read_only=True, repeat_safe=True),
            PluginTool(name="inspect_ifc_objects", read_only=True, repeat_safe=True),
            PluginTool(name="prepare_ifc_view", read_only=True, repeat_safe=True),
        ),
        app_resource_uri="ui://agent-hub-ifc-viewer/view.html",
        app_allow_wasm=True,
    )
    from agent_hub_api.modules.plugin_gateway._mcp import McpPluginClient

    return PluginGatewayModule(
        projects,
        catalog=(fixture, reference_calculation, calculation_source_object, ifc_viewer),
        enablements=PostgresPluginEnablementStore(settings),
        clients={
            fixture.id: McpPluginClient(
                endpoint=fixture.endpoint,
                timeout_seconds=settings.plugin_tool_timeout_seconds,
                max_result_bytes=settings.plugin_result_max_bytes,
                allow_private_network=True,
            ),
            reference_calculation.id: McpPluginClient(
                endpoint=reference_calculation.endpoint,
                timeout_seconds=settings.plugin_tool_timeout_seconds,
                max_result_bytes=settings.plugin_result_max_bytes,
                allow_private_network=True,
            ),
            calculation_source_object.id: McpPluginClient(
                endpoint=calculation_source_object.endpoint,
                timeout_seconds=settings.plugin_tool_timeout_seconds,
                max_result_bytes=settings.plugin_result_max_bytes,
                allow_private_network=True,
            ),
            ifc_viewer.id: McpPluginClient(
                endpoint=ifc_viewer.endpoint,
                timeout_seconds=settings.plugin_tool_timeout_seconds,
                max_result_bytes=settings.plugin_result_max_bytes,
                max_ui_resource_bytes=12_000_000,
                allow_private_network=True,
            ),
        },
        discovery_cache_seconds=settings.plugin_discovery_cache_seconds,
        max_concurrent_calls=settings.plugin_max_concurrent_calls,
        max_calls_per_minute=settings.plugin_max_calls_per_minute,
    )


def _validate_arguments(schema: Mapping[str, object], arguments: Mapping[str, object]) -> None:
    # A Plugin's schema may refer to its own definitions, never fetch remote schemas.
    try:
        Draft202012Validator(schema, registry=Registry()).validate(arguments)
    except JsonSchemaValidationError as error:
        location = "/" + "/".join(str(part) for part in error.path)
        raise ValueError(f"MCP input is invalid at {location} ({error.validator}).") from None


def _agent_tool(
    gateway: PluginGatewayModule,
    project_id: str,
    manifest: PluginManifest,
    plugin_tool: PluginTool,
    discovered: PluginDiscoveredTool,
    on_success: PluginResultRecorder | None,
) -> BaseTool:
    async def invoke(**arguments: object) -> str:
        try:
            _validate_arguments(discovered.input_schema or {}, arguments)
        except Exception:
            return "Plugin tool input does not match its declared schema."
        try:
            result = await gateway._call_enabled(
                project_id,
                manifest.id,
                plugin_tool.name,
                arguments,
            )
        except Exception as error:
            return f"Plugin tool failed: {error}"
        saved = None
        if result.structured_content is not None and on_success is not None:
            saved = await on_success(manifest, plugin_tool, arguments, result)
        text = (
            "\n".join(result.content)
            if result.content
            else json.dumps(
                result.structured_content,
                sort_keys=True,
            )
        )
        if saved is not None:
            text += "\nSaved structured result: " + json.dumps(dict(saved), sort_keys=True)
        return text

    return StructuredTool.from_function(
        coroutine=invoke,
        name=f"{manifest.id.replace('-', '_')}__{plugin_tool.name}",
        description=discovered.description
        or plugin_tool.description
        or f"Run {plugin_tool.name} from {manifest.name}.",
        args_schema=dict(discovered.input_schema or {"type": "object", "properties": {}}),
    )


def _programmatic_tool(
    gateway: PluginGatewayModule,
    access: ProjectAccess,
    project_id: str,
    manifest: PluginManifest,
    plugin_tool: PluginTool,
    discovered: PluginDiscoveredTool,
) -> BaseTool:
    async def invoke(**arguments: object) -> dict[str, object]:
        # Recheck the current catalog, Project and server contract on each invocation.
        await gateway._projects.load(access, project_id)
        current = gateway._catalog.get(manifest.id)
        if current is None:
            raise PluginToolNotAllowed("This Plugin is unavailable for PTC.")
        permitted = next((tool for tool in current.tools if tool.name == plugin_tool.name), None)
        if permitted is None or not permitted.agent_visible or not permitted.read_only:
            raise PluginToolNotAllowed("This tool is not approved for read-only PTC.")
        discovered_tools = await gateway._discover(current)
        contract = next((tool for tool in discovered_tools if tool.name == plugin_tool.name), None)
        if contract is None or not contract.read_only:
            raise PluginToolNotAllowed("The server does not declare this tool read-only.")
        _validate_arguments(contract.input_schema or {}, arguments)
        result = await gateway._call_enabled(project_id, current.id, plugin_tool.name, arguments)
        # Deliberately no result recorder: PTC never creates a saved Artifact.
        return {
            "content": list(result.content),
            "structuredContent": dict(result.structured_content)
            if result.structured_content is not None
            else None,
        }

    return StructuredTool.from_function(
        coroutine=invoke,
        name=f"{manifest.id.replace('-', '_')}__{plugin_tool.name}",
        description=(discovered.description or plugin_tool.description or plugin_tool.name)
        + " Returns {content, structuredContent}; PTC results are unsaved.",
        args_schema=dict(discovered.input_schema or {"type": "object", "properties": {}}),
    )
