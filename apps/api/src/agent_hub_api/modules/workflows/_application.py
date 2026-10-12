"""Versioned Project Workflow Definitions with validated DAG wiring."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import TypeAdapter, ValidationError

from agent_hub_api.modules.call_review import MAX_MAP_INVOCATIONS
from agent_hub_api.modules.datasets import DatasetModule, DatasetNotFound
from agent_hub_api.modules.plugin_gateway import (
    PluginGatewayModule,
    PluginNotAvailable,
    PluginNotEnabled,
    PluginToolNotAllowed,
)
from agent_hub_api.modules.project_files import (
    ProjectFileAccess,
    ProjectFileError,
    ProjectFilesModule,
)
from agent_hub_api.modules.projects import ProjectAccess, ProjectModule, ProjectNotFound
from agent_hub_api.modules.transforms import TransformModule, TransformNotFound

MAX_NODES = 32
MAX_EDGES = 128
MAX_OUTPUTS = 20
_NODE_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")


@dataclass(frozen=True, slots=True)
class WorkflowNode:
    id: str
    kind: str
    ref_id: str
    version: int | str
    shape: str = "single"
    tool_name: str | None = None


@dataclass(frozen=True, slots=True)
class WorkflowEdge:
    source_node: str
    source_port: str
    target_node: str
    target_port: str


@dataclass(frozen=True, slots=True)
class WorkflowOutput:
    name: str
    node: str
    port: str


@dataclass(frozen=True, slots=True)
class WorkflowGraph:
    nodes: tuple[WorkflowNode, ...]
    edges: tuple[WorkflowEdge, ...]
    outputs: tuple[WorkflowOutput, ...]

    @classmethod
    def from_json(cls, raw: str) -> "WorkflowGraph":
        try:
            return TypeAdapter(cls).validate_json(raw)
        except ValidationError as error:
            raise WorkflowValidationError(
                "Workflow graph must be valid JSON with nodes, edges, and outputs."
            ) from error


@dataclass(frozen=True, slots=True)
class WorkflowDefinition:
    id: str
    project_id: str
    name: str
    graph: WorkflowGraph
    version: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class WorkflowFileSource:
    """An ordinary durable Project File that can be pinned by a Workflow node."""

    path: str
    version: int


class WorkflowNotFound(Exception):
    """No Workflow Definition is visible in the Project."""


class WorkflowValidationError(Exception):
    """A Workflow Definition has invalid or stale graph wiring."""


class WorkflowVersionConflict(WorkflowValidationError):
    """The saved Workflow Definition changed since it was loaded."""


class WorkflowStore(Protocol):
    async def create(self, definition: WorkflowDefinition) -> WorkflowDefinition: ...
    async def load(self, project_id: str, definition_id: str) -> WorkflowDefinition | None: ...
    async def list(self, project_id: str) -> Sequence[WorkflowDefinition]: ...
    async def replace(
        self, definition: WorkflowDefinition, expected_version: int
    ) -> WorkflowDefinition | None: ...


class MemoryWorkflowStore:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], WorkflowDefinition] = {}

    async def create(self, definition: WorkflowDefinition) -> WorkflowDefinition:
        self._items[(definition.project_id, definition.id)] = definition
        return definition

    async def load(self, project_id: str, definition_id: str) -> WorkflowDefinition | None:
        return self._items.get((project_id, definition_id))

    async def list(self, project_id: str) -> Sequence[WorkflowDefinition]:
        return tuple(item for (owner, _), item in self._items.items() if owner == project_id)

    async def replace(
        self, definition: WorkflowDefinition, expected_version: int
    ) -> WorkflowDefinition | None:
        key = (definition.project_id, definition.id)
        current = self._items.get(key)
        if current is None or current.version != expected_version:
            return None
        self._items[key] = definition
        return definition


@dataclass(frozen=True, slots=True)
class _Ports:
    inputs: Mapping[str, Mapping[str, object]]
    required: frozenset[str]
    outputs: Mapping[str, Mapping[str, object]]
    map_schema: Mapping[str, object] | None = None


class WorkflowDefinitionModule:
    """Own saved graph syntax, target resolution, and Project authority."""

    def __init__(
        self,
        projects: ProjectModule,
        datasets: DatasetModule,
        transforms: TransformModule,
        gateway: PluginGatewayModule | None,
        store: WorkflowStore,
        *,
        project_files: ProjectFilesModule | None = None,
    ) -> None:
        self._projects = projects
        self._datasets = datasets
        self._transforms = transforms
        self._gateway = gateway
        self._store = store
        self._project_files = project_files

    async def create(
        self, access: ProjectAccess, project_id: str, name: str, graph: WorkflowGraph
    ) -> WorkflowDefinition:
        await self._authorize(access, project_id)
        await self._validate(access, project_id, graph)
        now = datetime.now(UTC)
        return await self._store.create(
            WorkflowDefinition(str(uuid4()), project_id, _name(name), graph, 1, now, now)
        )

    async def load(
        self, access: ProjectAccess, project_id: str, definition_id: str
    ) -> WorkflowDefinition:
        await self._authorize(access, project_id)
        definition = await self._store.load(project_id, definition_id)
        if definition is None:
            raise WorkflowNotFound
        return definition

    async def list(self, access: ProjectAccess, project_id: str) -> Sequence[WorkflowDefinition]:
        await self._authorize(access, project_id)
        return await self._store.list(project_id)

    async def validate_graph(
        self, access: ProjectAccess, project_id: str, graph: WorkflowGraph
    ) -> None:
        """Validate a proposed graph without creating or revising a Workflow."""
        await self._authorize(access, project_id)
        await self._validate(access, project_id, graph)

    async def list_file_sources(
        self, access: ProjectAccess, project_id: str
    ) -> Sequence[WorkflowFileSource]:
        """List ordinary durable files with versions suitable for Workflow file nodes."""
        await self._authorize(access, project_id)
        if self._project_files is None:
            return ()
        files = await self._project_files.list_visible(
            ProjectFileAccess(subject=access.subject), project_id
        )
        return tuple(
            WorkflowFileSource(f"/project{file.path}", file.version)
            for file in files
            if not file.path.startswith(("/.datasets/", "/.artifacts/"))
        )

    async def check_current(
        self, access: ProjectAccess, project_id: str, definition: WorkflowDefinition
    ) -> None:
        """Recheck every pinned input and target before a Run captures them."""
        await self._authorize(access, project_id)
        if definition.project_id != project_id:
            raise WorkflowNotFound
        await self._validate(access, project_id, definition.graph)

    async def revise(
        self,
        access: ProjectAccess,
        project_id: str,
        definition_id: str,
        name: str,
        graph: WorkflowGraph,
        *,
        expected_version: int,
    ) -> WorkflowDefinition:
        current = await self.load(access, project_id, definition_id)
        if current.version != expected_version:
            raise WorkflowVersionConflict("Workflow version changed; reload before editing.")
        await self._validate(access, project_id, graph)
        revised = replace(
            current,
            name=_name(name),
            graph=graph,
            version=current.version + 1,
            updated_at=datetime.now(UTC),
        )
        saved = await self._store.replace(revised, expected_version)
        if saved is None:
            raise WorkflowVersionConflict("Workflow version changed; reload before editing.")
        return saved

    async def _authorize(self, access: ProjectAccess, project_id: str) -> None:
        try:
            await self._projects.load(access, project_id)
        except ProjectNotFound as error:
            raise WorkflowNotFound from error

    async def _validate(self, access: ProjectAccess, project_id: str, graph: WorkflowGraph) -> None:
        if not 1 <= len(graph.nodes) <= MAX_NODES:
            raise WorkflowValidationError("Workflow needs 1–32 nodes.")
        if len(graph.edges) > MAX_EDGES or not 1 <= len(graph.outputs) <= MAX_OUTPUTS:
            raise WorkflowValidationError("Workflow exceeds its edge or output bound.")
        nodes = {node.id: node for node in graph.nodes}
        if len(nodes) != len(graph.nodes) or any(not _NODE_ID.fullmatch(id) for id in nodes):
            raise WorkflowValidationError("Workflow node IDs must be unique and valid.")
        ports = {node.id: await self._describe(access, project_id, node) for node in graph.nodes}
        incoming: dict[tuple[str, str], WorkflowEdge] = {}
        dependencies: dict[str, set[str]] = {node.id: set() for node in graph.nodes}
        for edge in graph.edges:
            source = ports.get(edge.source_node)
            target = ports.get(edge.target_node)
            if source is None or target is None:
                raise WorkflowValidationError("Workflow edge refers to an unknown node.")
            source_schema = source.outputs.get(edge.source_port)
            target_schema = target.inputs.get(edge.target_port)
            if source_schema is None or target_schema is None:
                raise WorkflowValidationError("Workflow edge refers to an unknown port.")
            key = (edge.target_node, edge.target_port)
            if key in incoming:
                raise WorkflowValidationError("A call input can have only one incoming edge.")
            if not _compatible(source_schema, target_schema):
                raise WorkflowValidationError("Workflow edge has incompatible port shapes.")
            source_node = nodes[edge.source_node]
            target_node = nodes[edge.target_node]
            if source_node.kind == "dataset" and target_node.shape == "map":
                dataset = await self._datasets.load_dataset(access, project_id, source_node.ref_id)
                if len(dataset.records) > MAX_MAP_INVOCATIONS:
                    raise WorkflowValidationError("Map input exceeds 100 Dataset Records.")
            incoming[key] = edge
            dependencies[edge.target_node].add(edge.source_node)
        if _has_cycle(dependencies):
            raise WorkflowValidationError("Workflow graph contains a cycle.")
        for node in graph.nodes:
            missing = ports[node.id].required - {
                port for (owner, port) in incoming if owner == node.id
            }
            if missing:
                raise WorkflowValidationError(
                    f"Workflow node {node.id} has a required input without an edge: "
                    + ", ".join(sorted(missing))
                )
        await self._validate_mcp_maps(access, project_id, graph, ports, incoming, nodes)
        names: set[str] = set()
        for output in graph.outputs:
            if not _NODE_ID.fullmatch(output.name) or output.name in names:
                raise WorkflowValidationError("Workflow output names must be unique and valid.")
            names.add(output.name)
            if output.node not in ports or output.port not in ports[output.node].outputs:
                raise WorkflowValidationError("Workflow output refers to an unknown port.")

    async def _describe(self, access: ProjectAccess, project_id: str, node: WorkflowNode) -> _Ports:
        if node.kind == "file":
            if (
                self._project_files is None
                or node.tool_name is not None
                or node.shape != "single"
                or not isinstance(node.version, int)
            ):
                raise WorkflowValidationError("Project File node has an invalid reference.")
            try:
                file = await self._project_files.load_ordinary_file(
                    project_id, _project_file_path(node.ref_id)
                )
            except ProjectFileError as error:
                raise WorkflowValidationError("Project File input is unavailable.") from error
            if file.version != node.version:
                raise WorkflowValidationError(
                    "Project File version changed; review the Workflow again."
                )
            return _Ports({}, frozenset(), {"content": {"type": "string"}})
        if node.kind == "dataset":
            if (
                node.tool_name is not None
                or node.shape != "single"
                or not isinstance(node.version, int)
            ):
                raise WorkflowValidationError("Dataset node has an invalid reference.")
            try:
                dataset = await self._datasets.load_dataset(access, project_id, node.ref_id)
            except DatasetNotFound as error:
                raise WorkflowValidationError("Dataset input is unavailable.") from error
            if dataset.version != node.version:
                raise WorkflowValidationError("Dataset version changed; review the Workflow again.")
            return _Ports(
                {}, frozenset(), {"records": {"type": "array", "items": {"type": "object"}}}
            )
        if node.shape not in {"single", "map"}:
            raise WorkflowValidationError("Call shape must be single or map.")
        if node.kind == "python":
            if node.tool_name is not None or not isinstance(node.version, int):
                raise WorkflowValidationError("Python Function node has an invalid reference.")
            try:
                definition = await self._transforms.load(access, project_id, node.ref_id)
            except TransformNotFound as error:
                raise WorkflowValidationError(
                    f"Python Function ID {node.ref_id!r} is unavailable; use the ID returned "
                    "by discover_project_transforms, not the Function name."
                ) from error
            if definition.revision != node.version:
                raise WorkflowValidationError(
                    "Function version changed; review the Workflow again."
                )
            names = tuple(definition.input_selectors)
            if node.shape == "map" and len(names) != 1:
                raise WorkflowValidationError("Mapped Python Function needs one named input.")
            inputs: Mapping[str, Mapping[str, object]] = (
                {"items": {"type": "array"}}
                if node.shape == "map"
                else {name: {} for name in names}
            )
            output: Mapping[str, object] = dict(definition.output_schema)
            if node.shape == "map":
                output = {"type": "array", "items": output}
            return _Ports(inputs, frozenset(inputs), {"result": output})
        if node.kind == "mcp":
            if self._gateway is None or not node.tool_name or not isinstance(node.version, str):
                raise WorkflowValidationError("MCP tool node has an invalid reference.")
            try:
                version = await self._gateway.tool_version(
                    access, project_id, node.ref_id, node.tool_name
                )
                input_schema = await self._gateway.input_schema(
                    access, project_id, node.ref_id, node.tool_name
                )
                output_schema = await self._gateway.output_schema(
                    access,
                    project_id,
                    node.ref_id,
                    node.tool_name,
                    require_repeat_safe=node.shape == "map",
                )
            except (PluginNotAvailable, PluginNotEnabled, PluginToolNotAllowed) as error:
                raise WorkflowValidationError(
                    "MCP tool is unavailable for this Project."
                ) from error
            if version != node.version:
                raise WorkflowValidationError(
                    "MCP tool version changed; review the Workflow again."
                )
            if node.shape == "map":
                return _Ports(
                    {
                        "items": {"type": "array", "items": {"type": "object"}},
                        **{
                            name: schema
                            for name, schema in _schema_properties(input_schema).items()
                            if name != "items"
                        },
                    },
                    frozenset({"items"}),
                    {"result": {"type": "array", "items": dict(output_schema)}},
                    dict(input_schema),
                )
            properties = input_schema.get("properties", {})
            if not isinstance(properties, Mapping):
                raise WorkflowValidationError("MCP tool has no named input ports.")
            inputs = {
                name: schema
                for name, schema in properties.items()
                if isinstance(name, str) and isinstance(schema, Mapping)
            }
            required = input_schema.get("required", [])
            if not isinstance(required, list) or not all(
                isinstance(name, str) for name in required
            ):
                raise WorkflowValidationError("MCP tool has invalid required ports.")
            if not set(required).issubset(inputs):
                raise WorkflowValidationError("MCP tool required port is not declared.")
            return _Ports(inputs, frozenset(required), {"result": dict(output_schema)})
        raise WorkflowValidationError("Workflow node kind is unknown.")

    async def _validate_mcp_maps(
        self,
        access: ProjectAccess,
        project_id: str,
        graph: WorkflowGraph,
        ports: Mapping[str, _Ports],
        incoming: Mapping[tuple[str, str], WorkflowEdge],
        nodes: Mapping[str, WorkflowNode],
    ) -> None:
        for node in graph.nodes:
            node_ports = ports[node.id]
            if node.kind != "mcp" or node.shape != "map" or node_ports.map_schema is None:
                continue
            item_edge = incoming.get((node.id, "items"))
            item_source = nodes[item_edge.source_node] if item_edge is not None else None
            if item_source is None or item_source.kind != "dataset":
                continue
            dataset = await self._datasets.load_dataset(access, project_id, item_source.ref_id)
            constants: dict[str, object] = {}
            for (target_id, target_port), edge in incoming.items():
                if target_id != node.id or target_port == "items":
                    continue
                source_node = nodes[edge.source_node]
                if source_node.kind != "file":
                    continue
                if self._project_files is None:
                    raise WorkflowValidationError("Project File input is unavailable.")
                try:
                    file = await self._project_files.load_ordinary_file(
                        project_id, _project_file_path(source_node.ref_id)
                    )
                except ProjectFileError as error:
                    raise WorkflowValidationError("Project File input is unavailable.") from error
                if file.version != source_node.version:
                    raise WorkflowValidationError(
                        "Project File version changed; review the Workflow again."
                    )
                constants[target_port] = file.content
            validator = Draft202012Validator(node_ports.map_schema)
            for record in dataset.records:
                collisions = constants.keys() & record.value.keys()
                if collisions:
                    raise WorkflowValidationError(
                        f"Dataset Record {record.position + 1} already supplies mapped MCP input "
                        + ", ".join(sorted(collisions))
                        + "."
                    )
                try:
                    validator.validate({**record.value, **constants})
                except JsonSchemaValidationError as error:
                    raise WorkflowValidationError(
                        f"Dataset Record {record.position + 1} and connected inputs do not match "
                        "the MCP tool input schema."
                    ) from error


def _name(value: str) -> str:
    normalized = value.strip()
    if not 1 <= len(normalized) <= 120:
        raise WorkflowValidationError("Workflow name must contain 1–120 characters.")
    return normalized


def _schema_properties(schema: Mapping[str, object]) -> Mapping[str, Mapping[str, object]]:
    raw = schema.get("properties", {})
    if not isinstance(raw, Mapping) or any(
        not isinstance(name, str) or not isinstance(value, Mapping) for name, value in raw.items()
    ):
        raise WorkflowValidationError("MCP tool has invalid named input ports.")
    return {name: value for name, value in raw.items() if isinstance(name, str)}


def _project_file_path(value: str) -> str:
    if not value.startswith("/project/"):
        raise WorkflowValidationError("Project File reference must use an absolute /project path.")
    return value.removeprefix("/project")


def _compatible(source: Mapping[str, object], target: Mapping[str, object]) -> bool:
    source_type = source.get("type")
    target_type = target.get("type")
    return (
        not isinstance(source_type, str)
        or not isinstance(target_type, str)
        or source_type == target_type
    )


def _has_cycle(dependencies: Mapping[str, set[str]]) -> bool:
    remaining = {node: set(parents) for node, parents in dependencies.items()}
    while remaining:
        ready = {node for node, parents in remaining.items() if not parents}
        if not ready:
            return True
        remaining = {
            node: parents - ready for node, parents in remaining.items() if node not in ready
        }
    return False
