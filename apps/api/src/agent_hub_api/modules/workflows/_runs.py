"""Durable Workflow Run preparation and immutable execution inputs."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from agent_hub_api.modules.call_review import MAX_MAP_INVOCATIONS
from agent_hub_api.modules.datasets import DatasetModule, DatasetNotFound
from agent_hub_api.modules.plugin_gateway import (
    PluginGatewayModule,
    PluginNotAvailable,
    PluginNotEnabled,
    PluginToolNotAllowed,
)
from agent_hub_api.modules.projects import ProjectAccess
from agent_hub_api.modules.transforms import (
    TransformExecutionError,
    TransformInitiation,
    TransformModule,
    TransformNotFound,
    TransformValidationError,
)

from ._application import (
    WorkflowDefinitionModule,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowNode,
    WorkflowNotFound,
    WorkflowValidationError,
)


@dataclass(frozen=True, slots=True)
class WorkflowRun:
    id: str
    project_id: str
    workflow_id: str
    definition_version: int
    status: str
    snapshot: Mapping[str, object]
    execution: Mapping[str, object]
    initiator_subject: str
    idempotency_key: str
    created_at: datetime


class WorkflowRunConflict(Exception):
    """A request key already names a different Workflow."""


class WorkflowRunStore(Protocol):
    async def create_or_load(self, run: WorkflowRun) -> WorkflowRun: ...
    async def load(self, project_id: str, run_id: str) -> WorkflowRun | None: ...
    async def by_key(self, project_id: str, key: str) -> WorkflowRun | None: ...
    async def list(self, project_id: str, workflow_id: str) -> Sequence[WorkflowRun]: ...
    async def update(self, run: WorkflowRun, expected_status: str) -> WorkflowRun | None: ...


class MemoryWorkflowRunStore:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], WorkflowRun] = {}
        self._keys: dict[tuple[str, str], str] = {}

    async def create_or_load(self, run: WorkflowRun) -> WorkflowRun:
        key = (run.project_id, run.idempotency_key)
        existing = self._keys.get(key)
        if existing is not None:
            return self._items[(run.project_id, existing)]
        self._keys[key] = run.id
        self._items[(run.project_id, run.id)] = run
        return run

    async def load(self, project_id: str, run_id: str) -> WorkflowRun | None:
        return self._items.get((project_id, run_id))

    async def by_key(self, project_id: str, key: str) -> WorkflowRun | None:
        run_id = self._keys.get((project_id, key))
        return await self.load(project_id, run_id) if run_id else None

    async def list(self, project_id: str, workflow_id: str) -> Sequence[WorkflowRun]:
        return tuple(
            sorted(
                (
                    run
                    for (owner, _), run in self._items.items()
                    if owner == project_id and run.workflow_id == workflow_id
                ),
                key=lambda run: (run.created_at, run.id),
                reverse=True,
            )
        )

    async def update(self, run: WorkflowRun, expected_status: str) -> WorkflowRun | None:
        key = (run.project_id, run.id)
        current = self._items.get(key)
        if current is None or current.status != expected_status:
            return None
        self._items[key] = run
        return run


class WorkflowRunModule:
    """Capture a checked Definition and source values before dispatch begins."""

    def __init__(
        self,
        definitions: WorkflowDefinitionModule,
        datasets: DatasetModule,
        transforms: TransformModule,
        gateway: PluginGatewayModule | None,
        store: WorkflowRunStore,
    ) -> None:
        self._definitions = definitions
        self._datasets = datasets
        self._transforms = transforms
        self._gateway = gateway
        self._store = store

    async def prepare(
        self,
        access: ProjectAccess,
        project_id: str,
        workflow_id: str,
        idempotency_key: str,
        *,
        expected_version: int,
    ) -> WorkflowRun:
        if not 1 <= len(idempotency_key) <= 120:
            raise WorkflowValidationError("Request key must contain 1–120 characters.")
        definition = await self._definitions.load(access, project_id, workflow_id)
        existing = await self._store.by_key(project_id, idempotency_key)
        if existing is not None:
            return _same_workflow(existing, workflow_id)
        if definition.version != expected_version:
            raise WorkflowValidationError("Workflow version changed; review it again.")
        await self._definitions.check_current(access, project_id, definition)
        sources: dict[str, object] = {}
        targets: dict[str, object] = {}
        for node in definition.graph.nodes:
            if node.kind == "dataset":
                try:
                    dataset = await self._datasets.load_dataset(access, project_id, node.ref_id)
                except DatasetNotFound as error:
                    raise WorkflowValidationError("Dataset input is unavailable.") from error
                if dataset.version != node.version:
                    raise WorkflowValidationError(
                        "Dataset version changed; review the Workflow again."
                    )
                sources[node.id] = {
                    "datasetId": dataset.id,
                    "version": dataset.version,
                    "records": [
                        {"id": record.id, "position": record.position, "value": record.value}
                        for record in dataset.records
                    ],
                }
            elif node.kind == "python":
                try:
                    target = await self._transforms.load(access, project_id, node.ref_id)
                except TransformNotFound as error:
                    raise WorkflowValidationError("Python Function is unavailable.") from error
                if target.revision != node.version:
                    raise WorkflowValidationError(
                        "Function version changed; review the Workflow again."
                    )
                targets[node.id] = {
                    "definitionId": target.id,
                    "revision": target.revision,
                    "source": target.source,
                    "sourceHash": target.source_hash,
                    "inputNames": list(target.input_selectors),
                    "outputSchema": target.output_schema,
                    "runtime": target.runtime,
                    "packageHash": target.package_hash,
                }
            elif node.kind == "mcp":
                if self._gateway is None or node.tool_name is None:
                    raise WorkflowValidationError("MCP tool is unavailable for this Project.")
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
                targets[node.id] = {
                    "pluginId": node.ref_id,
                    "toolName": node.tool_name,
                    "version": version,
                    "inputSchema": input_schema,
                    "outputSchema": output_schema,
                }
        snapshot = json.loads(
            json.dumps({"graph": asdict(definition.graph), "sources": sources, "targets": targets})
        )
        run = WorkflowRun(
            str(uuid4()),
            project_id,
            workflow_id,
            definition.version,
            "prepared",
            snapshot,
            {},
            access.subject,
            idempotency_key,
            datetime.now(UTC),
        )
        return _same_workflow(await self._store.create_or_load(run), workflow_id)

    async def execute(
        self,
        access: ProjectAccess,
        project_id: str,
        run_id: str,
        *,
        initiation: TransformInitiation | None = None,
    ) -> WorkflowRun:
        """Execute a Python-only DAG through the owning Transform Module."""
        run = await self.load(access, project_id, run_id)
        if run.status == "succeeded":
            return run
        if run.status != "prepared":
            raise WorkflowRunConflict("Workflow Run is already executing or terminal.")
        graph_raw = run.snapshot.get("graph")
        if not isinstance(graph_raw, dict):
            raise WorkflowValidationError("Workflow Run graph snapshot is invalid.")
        graph = WorkflowGraph.from_json(json.dumps(graph_raw))
        if any(node.kind == "mcp" for node in graph.nodes):
            raise WorkflowRunConflict("MCP Workflow execution is not available in this slice.")
        execution_start = replace(run, status="running", execution={"nodes": {}})
        run = await self._replace(execution_start, "prepared")
        source_snapshots = _mapping(run.snapshot.get("sources"))
        node_outputs: dict[str, dict[str, object]] = {}
        execution_nodes: dict[str, object] = {}
        for node in _topological_nodes(graph):
            if node.kind == "dataset":
                source = _mapping(source_snapshots.get(node.id))
                records = source.get("records")
                if not isinstance(records, list):
                    return await self._fail(run, execution_nodes, node.id, "source_snapshot")
                values = [_mapping(record).get("value") for record in records]
                node_outputs[node.id] = {"records": values}
                continue
            edges = [edge for edge in graph.edges if edge.target_node == node.id]
            inputs: dict[str, object] = {}
            for edge in edges:
                outputs = node_outputs.get(edge.source_node)
                if outputs is None or edge.source_port not in outputs:
                    return await self._fail(run, execution_nodes, node.id, "upstream_output")
                inputs[edge.target_port] = outputs[edge.source_port]
            target_snapshots = _mapping(run.snapshot.get("targets"))
            target = _mapping(target_snapshots.get(node.id))
            input_names = target.get("inputNames")
            if not isinstance(input_names, list) or not all(
                isinstance(name, str) for name in input_names
            ):
                return await self._fail(run, execution_nodes, node.id, "target_snapshot")
            call_context = initiation or TransformInitiation("workflowRun", "notRequired")
            if node.shape == "map":
                items = inputs.get("items")
                if (
                    not isinstance(items, list)
                    or len(items) > MAX_MAP_INVOCATIONS
                    or len(input_names) != 1
                ):
                    return await self._fail(run, execution_nodes, node.id, "map_input")
                records = _source_records_for_edge(graph, source_snapshots, edges[0])
                item_results: list[dict[str, object]] = []
                results: list[object] = []
                for index, item in enumerate(items):
                    try:
                        child = await self._transforms.start_function_call(
                            access,
                            project_id,
                            node.ref_id,
                            {input_names[0]: item},
                            {},
                            expected_revision=int(node.version),
                            initiation=call_context,
                        )
                    except (
                        TransformExecutionError,
                        TransformNotFound,
                        TransformValidationError,
                    ) as error:
                        item_results.append(
                            {
                                "index": index,
                                "input": item,
                                "status": "failed",
                                "error": error.code
                                if isinstance(error, TransformExecutionError)
                                else str(error),
                            }
                        )
                        execution_nodes[node.id] = {
                            "status": "failed",
                            "inputs": inputs,
                            "items": item_results,
                        }
                        code = (
                            error.code
                            if isinstance(error, TransformExecutionError)
                            else "stale_target"
                        )
                        return await self._fail(run, execution_nodes, node.id, code)
                    item_identity = (
                        _mapping(records[index]).get("id")
                        if records is not None and index < len(records)
                        else f"{edges[0].source_node}:{index}"
                    )
                    item_results.append(
                        {
                            "index": index,
                            "itemId": item_identity,
                            "input": item,
                            "status": child.status,
                            "transformRunId": child.id,
                            **({"output": child.output} if child.status == "succeeded" else {}),
                            **({"error": child.error} if child.error else {}),
                        }
                    )
                    if child.status != "succeeded":
                        execution_nodes[node.id] = {
                            "status": "failed",
                            "inputs": inputs,
                            "items": item_results,
                        }
                        return await self._fail(run, execution_nodes, node.id, "child_call_failed")
                    results.append(child.output)
                    execution_nodes[node.id] = {
                        "status": "running",
                        "inputs": inputs,
                        "items": item_results,
                    }
                    run = await self._save_progress(run, execution_nodes)
                node_outputs[node.id] = {"result": results}
                execution_nodes[node.id] = {
                    "status": "succeeded",
                    "inputs": inputs,
                    "items": item_results,
                    "output": results,
                }
            else:
                try:
                    child = await self._transforms.start_function_call(
                        access,
                        project_id,
                        node.ref_id,
                        inputs,
                        {},
                        expected_revision=int(node.version),
                        initiation=call_context,
                    )
                except (
                    TransformExecutionError,
                    TransformNotFound,
                    TransformValidationError,
                ) as error:
                    execution_nodes[node.id] = {
                        "status": "failed",
                        "inputs": inputs,
                        "error": (
                            error.code if isinstance(error, TransformExecutionError) else str(error)
                        ),
                    }
                    code = (
                        error.code if isinstance(error, TransformExecutionError) else "stale_target"
                    )
                    return await self._fail(run, execution_nodes, node.id, code)
                execution_nodes[node.id] = {
                    "status": child.status,
                    "inputs": inputs,
                    "transformRunId": child.id,
                    **({"output": child.output} if child.status == "succeeded" else {}),
                    **({"error": child.error} if child.error else {}),
                }
                if child.status != "succeeded":
                    return await self._fail(run, execution_nodes, node.id, "child_call_failed")
                node_outputs[node.id] = {"result": child.output}
            run = await self._save_progress(run, execution_nodes)
        named_outputs: dict[str, object] = {}
        for output in graph.outputs:
            named_outputs[output.name] = node_outputs[output.node][output.port]
        return await self._replace(
            replace(
                run,
                status="succeeded",
                execution={"nodes": execution_nodes, "outputs": named_outputs},
            ),
            "running",
        )

    async def _save_progress(self, run: WorkflowRun, nodes: Mapping[str, object]) -> WorkflowRun:
        return await self._replace(replace(run, execution={"nodes": dict(nodes)}), "running")

    async def _fail(
        self, run: WorkflowRun, nodes: Mapping[str, object], node_id: str, code: str
    ) -> WorkflowRun:
        execution = {"nodes": dict(nodes), "error": {"nodeId": node_id, "code": code}}
        return await self._replace(replace(run, status="failed", execution=execution), "running")

    async def _replace(self, run: WorkflowRun, expected_status: str) -> WorkflowRun:
        saved = await self._store.update(run, expected_status)
        if saved is None:
            raise WorkflowRunConflict("Workflow Run changed while it was executing.")
        return saved

    async def load(self, access: ProjectAccess, project_id: str, run_id: str) -> WorkflowRun:
        await self._definitions.list(access, project_id)
        run = await self._store.load(project_id, run_id)
        if run is None:
            raise WorkflowNotFound
        return run

    async def list(
        self, access: ProjectAccess, project_id: str, workflow_id: str
    ) -> Sequence[WorkflowRun]:
        await self._definitions.load(access, project_id, workflow_id)
        return await self._store.list(project_id, workflow_id)


def _same_workflow(run: WorkflowRun, workflow_id: str) -> WorkflowRun:
    if run.workflow_id != workflow_id:
        raise WorkflowRunConflict("Request key already names another Workflow.")
    return run


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _topological_nodes(graph: WorkflowGraph) -> tuple[WorkflowNode, ...]:
    nodes = {node.id: node for node in graph.nodes}
    dependencies: dict[str, set[str]] = {node.id: set() for node in graph.nodes}
    for edge in graph.edges:
        dependencies[edge.target_node].add(edge.source_node)
    ordered: list[WorkflowNode] = []
    while dependencies:
        ready = sorted(node for node, parents in dependencies.items() if not parents)
        if not ready:
            raise WorkflowValidationError("Workflow graph contains a cycle.")
        for node_id in ready:
            ordered.append(nodes[node_id])
            dependencies.pop(node_id)
        for parents in dependencies.values():
            parents.difference_update(ready)
    return tuple(ordered)


def _source_records_for_edge(
    graph: WorkflowGraph,
    sources: Mapping[str, object],
    edge: WorkflowEdge,
) -> list[object] | None:
    node = next((item for item in graph.nodes if item.id == edge.source_node), None)
    if node is None or node.kind != "dataset" or edge.source_port != "records":
        return None
    records = _mapping(sources.get(node.id)).get("records")
    return records if isinstance(records, list) else None
