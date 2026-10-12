"""Versioned Project Workflow Definitions with validated DAG wiring."""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from jsonschema import SchemaError as JsonSchemaSchemaError
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import TypeAdapter, ValidationError

from agent_hub_api.modules.call_review import MAX_MAP_INVOCATIONS
from agent_hub_api.modules.datasets import DatasetModule, DatasetNotFound
from agent_hub_api.modules.functions import FunctionModule, FunctionNotFound
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

MAX_NODES = 32
MAX_EDGES = 128
MAX_OUTPUTS = 20
MAX_INPUTS = 64
_NODE_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")


@dataclass(frozen=True, slots=True)
class WorkflowNode:
    id: str
    kind: str
    ref_id: str
    version: int | str
    shape: str = "single"
    tool_name: str | None = None
    map_input: str | None = None


@dataclass(frozen=True, slots=True)
class WorkflowEdge:
    source_node: str | None = None
    source_port: str | None = None
    target_node: str = ""
    target_port: str = ""
    source_kind: str = "node"
    source_input: str | None = None
    source_path: str = ""
    target_path: str = ""
    literal: object = None


@dataclass(frozen=True, slots=True)
class WorkflowInput:
    name: str
    schema: Mapping[str, object]
    required: bool = True


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
    inputs: tuple[WorkflowInput, ...] = ()

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
        functions: FunctionModule,
        gateway: PluginGatewayModule | None,
        store: WorkflowStore,
        *,
        project_files: ProjectFilesModule | None = None,
    ) -> None:
        self._projects = projects
        self._datasets = datasets
        self._functions = functions
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
        if (
            len(graph.edges) > MAX_EDGES
            or not 1 <= len(graph.outputs) <= MAX_OUTPUTS
            or len(graph.inputs) > MAX_INPUTS
        ):
            raise WorkflowValidationError("Workflow exceeds its binding, input, or output bound.")
        nodes = {node.id: node for node in graph.nodes}
        if len(nodes) != len(graph.nodes) or any(not _NODE_ID.fullmatch(id) for id in nodes):
            raise WorkflowValidationError("Workflow node IDs must be unique and valid.")
        workflow_inputs = {item.name: item for item in graph.inputs}
        if len(workflow_inputs) != len(graph.inputs) or any(
            not _NODE_ID.fullmatch(name) for name in workflow_inputs
        ):
            raise WorkflowValidationError("Workflow Input names must be unique and valid.")
        for item in graph.inputs:
            try:
                Draft202012Validator.check_schema(item.schema)
            except (JsonSchemaValidationError, JsonSchemaSchemaError) as error:
                raise WorkflowValidationError(
                    f"Workflow Input {item.name!r} has an invalid JSON Schema."
                ) from error
        ports = {node.id: await self._describe(access, project_id, node) for node in graph.nodes}
        incoming: dict[tuple[str, str], list[WorkflowEdge]] = {}
        dependencies: dict[str, set[str]] = {node.id: set() for node in graph.nodes}
        for edge in graph.edges:
            target = ports.get(edge.target_node)
            if target is None:
                raise WorkflowValidationError("Workflow binding refers to an unknown target node.")
            target_schema = target.inputs.get(edge.target_port)
            if target_schema is None:
                raise WorkflowValidationError("Workflow edge refers to an unknown port.")
            key = (edge.target_node, edge.target_port)
            mapped_item = nodes[edge.target_node].shape == "map" and edge.target_port == "items"
            selected_target_schema = _schema_at_path(
                target_schema, edge.target_path, each_item=mapped_item
            )
            if edge.source_kind == "node":
                if edge.source_node is None or edge.source_port is None:
                    raise WorkflowValidationError("Node binding needs a source node and port.")
                source = ports.get(edge.source_node)
                if source is None:
                    raise WorkflowValidationError(
                        "Workflow binding refers to an unknown source node."
                    )
                source_schema = source.outputs.get(edge.source_port)
                if source_schema is None:
                    raise WorkflowValidationError(
                        "Workflow binding refers to an unknown source port."
                    )
                selected_source_schema = _schema_at_path(
                    source_schema,
                    edge.source_path,
                    each_item=mapped_item,
                )
                if (
                    nodes[edge.source_node].kind == "dataset"
                    and nodes[edge.target_node].shape == "map"
                ):
                    dataset = await self._datasets.load_dataset(
                        access, project_id, nodes[edge.source_node].ref_id
                    )
                    if len(dataset.records) > MAX_MAP_INVOCATIONS:
                        raise WorkflowValidationError("Map input exceeds 100 Dataset Records.")
                dependencies[edge.target_node].add(edge.source_node)
            elif edge.source_kind == "workflowInput":
                input_definition = workflow_inputs.get(edge.source_input or "")
                if input_definition is None:
                    raise WorkflowValidationError(
                        f"Workflow binding refers to undeclared Workflow Input "
                        f"{edge.source_input!r}."
                    )
                selected_source_schema = _schema_at_path(
                    input_definition.schema, edge.source_path, each_item=mapped_item
                )
            elif edge.source_kind == "literal":
                selected_source_schema = _schema_at_path(
                    _schema_for_values([edge.literal]), edge.source_path, each_item=mapped_item
                )
            else:
                raise WorkflowValidationError("Workflow binding has an unknown source kind.")
            if not _compatible(selected_source_schema, selected_target_schema):
                raise WorkflowValidationError(
                    f"Workflow has incompatible schemas for input "
                    f"{edge.target_node}.{edge.target_port}{edge.target_path}."
                )
            if edge.source_kind == "literal":
                try:
                    Draft202012Validator(selected_target_schema).validate(
                        _value_at_path(edge.literal, edge.source_path, each_item=mapped_item)
                    )
                except JsonSchemaValidationError as error:
                    raise WorkflowValidationError(
                        f"Literal binding does not match input "
                        f"{edge.target_node}.{edge.target_port}{edge.target_path}."
                    ) from error
            existing = incoming.setdefault(key, [])
            if any(_paths_overlap(binding.target_path, edge.target_path) for binding in existing):
                raise WorkflowValidationError(
                    f"Workflow has conflicting bindings for input {edge.target_node}."
                    f"{edge.target_port}{edge.target_path}."
                )
            existing.append(edge)
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
            for port, bindings in (
                (port, values) for (owner, port), values in incoming.items() if owner == node.id
            ):
                if not _target_required_fields_bound(ports[node.id].inputs[port], bindings):
                    raise WorkflowValidationError(
                        f"Workflow node {node.id} has required fields without bindings for "
                        f"input {port}."
                    )
        await self._validate_mcp_maps(access, project_id, graph, ports, incoming, nodes)
        names: set[str] = set()
        for output in graph.outputs:
            if not _NODE_ID.fullmatch(output.name) or output.name in names:
                raise WorkflowValidationError("Workflow output names must be unique and valid.")
            names.add(output.name)
            node_ports = ports.get(output.node)
            if node_ports is None:
                raise WorkflowValidationError(
                    f"Workflow output {output.name!r} refers to unknown node {output.node!r}."
                )
            if output.port not in node_ports.outputs:
                raise WorkflowValidationError(
                    f"Workflow output {output.name!r} refers to unknown port {output.port!r} "
                    f"on node {output.node!r}; available ports: "
                    + ", ".join(sorted(node_ports.outputs))
                    + ". Properties in an output schema are fields inside the node's result; "
                    "they are not separate ports."
                )

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
                {},
                frozenset(),
                {
                    "records": {
                        "type": "array",
                        "items": _schema_for_values(record.value for record in dataset.records),
                    }
                },
            )
        if node.shape not in {"single", "map"}:
            raise WorkflowValidationError("Call shape must be single or map.")
        if node.kind == "python":
            if node.tool_name is not None or not isinstance(node.version, int):
                raise WorkflowValidationError("Python Function node has an invalid reference.")
            try:
                definition = await self._functions.load(access, project_id, node.ref_id)
            except FunctionNotFound as error:
                raise WorkflowValidationError(
                    f"Python Function ID {node.ref_id!r} is unavailable; use the ID returned "
                    "by discover_project_functions, not the Function name."
                ) from error
            if definition.revision != node.version:
                raise WorkflowValidationError(
                    "Function version changed; review the Workflow again."
                )
            properties = _schema_properties(definition.input_schema)
            names = tuple(properties)
            map_input = node.map_input or (names[0] if names else None)
            if node.shape == "map" and (map_input is None or map_input not in properties):
                raise WorkflowValidationError("Mapped Python Function needs a declared item input.")
            function_inputs: Mapping[str, Mapping[str, object]] = dict(properties)
            if node.shape == "map":
                assert map_input is not None
                function_inputs = {
                    "items": {"type": "array", "items": dict(properties[map_input])},
                    **{name: schema for name, schema in properties.items() if name != map_input},
                }
            required_names = definition.input_schema.get("required", [])
            if not isinstance(required_names, list) or not all(
                isinstance(name, str) for name in required_names
            ):
                raise WorkflowValidationError("Python Function has invalid required inputs.")
            function_required = (
                (
                    frozenset({"items"})
                    | frozenset(name for name in required_names if name != map_input)
                )
                if node.shape == "map"
                else frozenset(required_names)
            )
            output: Mapping[str, object] = dict(definition.output_schema)
            if node.shape == "map":
                output = {"type": "array", "items": output}
            return _Ports(function_inputs, function_required, {"result": output})
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
            mcp_properties = input_schema.get("properties", {})
            if not isinstance(mcp_properties, Mapping):
                raise WorkflowValidationError("MCP tool has no named input ports.")
            mcp_inputs = {
                name: schema
                for name, schema in mcp_properties.items()
                if isinstance(name, str) and isinstance(schema, Mapping)
            }
            mcp_required = input_schema.get("required", [])
            if not isinstance(mcp_required, list) or not all(
                isinstance(name, str) for name in mcp_required
            ):
                raise WorkflowValidationError("MCP tool has invalid required ports.")
            if not set(mcp_required).issubset(mcp_inputs):
                raise WorkflowValidationError("MCP tool required port is not declared.")
            return _Ports(mcp_inputs, frozenset(mcp_required), {"result": dict(output_schema)})
        raise WorkflowValidationError("Workflow node kind is unknown.")

    async def _validate_mcp_maps(
        self,
        access: ProjectAccess,
        project_id: str,
        graph: WorkflowGraph,
        ports: Mapping[str, _Ports],
        incoming: Mapping[tuple[str, str], Sequence[WorkflowEdge]],
        nodes: Mapping[str, WorkflowNode],
    ) -> None:
        for node in graph.nodes:
            node_ports = ports[node.id]
            if node.kind != "mcp" or node.shape != "map" or node_ports.map_schema is None:
                continue
            node_bindings = [
                binding
                for (target_id, _), bindings in incoming.items()
                if target_id == node.id
                for binding in bindings
            ]
            if any(
                binding.source_kind == "workflowInput" or binding.source_path or binding.target_path
                for binding in node_bindings
            ):
                continue
            item_bindings = incoming.get((node.id, "items"), ())
            item_edge = item_bindings[0] if len(item_bindings) == 1 else None
            item_source = (
                nodes[item_edge.source_node]
                if item_edge is not None and item_edge.source_node is not None
                else None
            )
            if item_source is None or item_source.kind != "dataset":
                continue
            dataset = await self._datasets.load_dataset(access, project_id, item_source.ref_id)
            constants: dict[str, object] = {}
            for (target_id, target_port), bindings in incoming.items():
                if target_id != node.id or target_port == "items":
                    continue
                for edge in bindings:
                    if edge.source_kind == "literal" and edge.target_path == "":
                        constants[target_port] = edge.literal
                    elif edge.source_kind == "node" and edge.source_node is not None:
                        source_node = nodes[edge.source_node]
                        if source_node.kind != "file" or edge.target_path:
                            continue
                        if self._project_files is None:
                            raise WorkflowValidationError("Project File input is unavailable.")
                        try:
                            file = await self._project_files.load_ordinary_file(
                                project_id, _project_file_path(source_node.ref_id)
                            )
                        except ProjectFileError as error:
                            raise WorkflowValidationError(
                                "Project File input is unavailable."
                            ) from error
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


def _schema_for_values(values: Iterable[object]) -> Mapping[str, object]:
    samples = list(values)
    if not samples:
        return {"type": "object"}
    types = sorted({_json_type(value) for value in samples})
    if len(types) == 1 and types[0] == "object":
        records = [value for value in samples if isinstance(value, Mapping)]
        keys = set().union(*(record.keys() for record in records))
        properties = {
            key: _schema_for_values([record[key] for record in records if key in record])
            for key in sorted(keys)
            if isinstance(key, str)
        }
        required = sorted(key for key in properties if all(key in record for record in records))
        return {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        }
    if len(types) == 1 and types[0] == "array":
        items = [item for value in samples if isinstance(value, list) for item in value]
        return {"type": "array", "items": _schema_for_values(items)}
    return {"type": types[0] if len(types) == 1 else types}


def _json_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, list):
        return "array"
    return "null"


def _pointer_tokens(pointer: str) -> tuple[str, ...]:
    if pointer == "":
        return ()
    if not pointer.startswith("/"):
        raise WorkflowValidationError("Binding field paths must be JSON Pointers or empty.")
    tokens: list[str] = []
    for token in pointer[1:].split("/"):
        if re.search(r"~(?![01])", token):
            raise WorkflowValidationError("Binding field path has an invalid JSON Pointer escape.")
        tokens.append(token.replace("~1", "/").replace("~0", "~"))
    return tuple(tokens)


def _value_at_path(value: object, pointer: str, *, each_item: bool = False) -> object:
    if each_item:
        if not isinstance(value, list):
            raise WorkflowValidationError("Map item binding source must be a collection.")
        return [_value_at_path(item, pointer) for item in value]
    current = value
    for token in _pointer_tokens(pointer):
        if isinstance(current, Mapping) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdecimal() and int(token) < len(current):
            current = current[int(token)]
        else:
            raise WorkflowValidationError(
                f"Binding field path {pointer!r} does not exist in the literal value."
            )
    return current


def _schema_at_path(
    schema: Mapping[str, object], pointer: str, *, each_item: bool = False
) -> Mapping[str, object]:
    tokens = _pointer_tokens(pointer)
    current: Mapping[str, object] = schema
    if each_item:
        items = current.get("items")
        if not isinstance(items, Mapping):
            raise WorkflowValidationError("Map item binding needs an array source and target.")
        current = items
    for token in tokens:
        schema_type = current.get("type")
        if schema_type == "array" or (isinstance(schema_type, list) and "array" in schema_type):
            items = current.get("items")
            if not isinstance(items, Mapping) or not token.isdecimal():
                raise WorkflowValidationError(
                    f"Binding field path {pointer!r} does not select an array item."
                )
            current = items
            continue
        properties = current.get("properties")
        if not isinstance(properties, Mapping) or token not in properties:
            raise WorkflowValidationError(
                f"Binding field path {pointer!r} refers to an unknown field."
            )
        selected = properties[token]
        if not isinstance(selected, Mapping):
            raise WorkflowValidationError("Binding field path refers to an invalid schema.")
        current = selected
    if each_item:
        return {"type": "array", "items": dict(current)}
    return current


def _paths_overlap(left: str, right: str) -> bool:
    left_tokens = _pointer_tokens(left)
    right_tokens = _pointer_tokens(right)
    shorter = min(len(left_tokens), len(right_tokens))
    return left_tokens[:shorter] == right_tokens[:shorter]


def _target_required_fields_bound(
    schema: Mapping[str, object], bindings: Sequence[WorkflowEdge]
) -> bool:
    paths = [_pointer_tokens(binding.target_path) for binding in bindings]
    if any(not path for path in paths):
        return True

    def required_paths(
        current: Mapping[str, object], prefix: tuple[str, ...]
    ) -> list[tuple[str, ...]]:
        properties = current.get("properties")
        required = current.get("required", [])
        if not isinstance(properties, Mapping) or not isinstance(required, list):
            return []
        result: list[tuple[str, ...]] = []
        for name in required:
            if not isinstance(name, str) or not isinstance(properties.get(name), Mapping):
                continue
            path = (*prefix, name)
            child = properties[name]
            result.extend(required_paths(child, path))
            if not any(existing[: len(path)] == path for existing in result):
                result.append(path)
        return result

    required = required_paths(schema, ())
    return all(any(path[: len(binding)] == binding for binding in paths) for path in required)


def _project_file_path(value: str) -> str:
    if not value.startswith("/project/"):
        raise WorkflowValidationError("Project File reference must use an absolute /project path.")
    return value.removeprefix("/project")


def _compatible(source: Mapping[str, object], target: Mapping[str, object]) -> bool:
    source_types = _schema_types(source.get("type"))
    target_types = _schema_types(target.get("type"))
    if target_types and (
        not source_types
        or any(
            source_type not in target_types
            and not (source_type == "integer" and "number" in target_types)
            for source_type in source_types
        )
    ):
        return False
    if "array" in (source_types or set()) and "array" in (target_types or set()):
        source_items = source.get("items")
        target_items = target.get("items")
        if isinstance(target_items, Mapping) and (
            not isinstance(source_items, Mapping) or not _compatible(source_items, target_items)
        ):
            return False
    if "object" in (source_types or set()) and "object" in (target_types or set()):
        source_properties = source.get("properties", {})
        target_properties = target.get("properties", {})
        if isinstance(source_properties, Mapping) and isinstance(target_properties, Mapping):
            source_additional = source.get("additionalProperties", True)
            target_required = target.get("required", [])
            required_names = set(target_required) if isinstance(target_required, list) else set()
            for name, target_property in target_properties.items():
                source_property = source_properties.get(name)
                if not isinstance(target_property, Mapping):
                    continue
                if isinstance(source_property, Mapping):
                    if not _compatible(source_property, target_property):
                        return False
                elif (
                    source_additional is False
                    and name in required_names
                    or isinstance(source_additional, Mapping)
                    and not _compatible(source_additional, target_property)
                ):
                    return False
    return True


def _schema_types(value: object) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return set(value)
    return set()


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
