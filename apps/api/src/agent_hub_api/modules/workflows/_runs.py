"""Durable Workflow Run preparation and immutable execution inputs."""

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import UUID, uuid4, uuid5

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from jsonschema import ValidationError as JsonSchemaValidationError

from agent_hub_api.modules.call_review import MAX_MAP_INVOCATIONS
from agent_hub_api.modules.datasets import DatasetModule, DatasetNotFound
from agent_hub_api.modules.plugin_gateway import (
    PluginCallLimitExceeded,
    PluginGatewayModule,
    PluginNotAvailable,
    PluginNotEnabled,
    PluginToolNotAllowed,
    PluginToolResult,
    PluginTransportError,
)
from agent_hub_api.modules.project_files import ProjectFileError, ProjectFilesModule
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
    _project_file_path,
)

MAX_WORKFLOW_CONCURRENCY = 4


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
    async def interrupt_running(self) -> int: ...


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

    async def interrupt_running(self) -> int:
        interrupted = 0
        for key, run in tuple(self._items.items()):
            if run.status == "running":
                self._items[key] = replace(run, status="interrupted")
                interrupted += 1
        return interrupted


class WorkflowRunModule:
    """Capture a checked Definition and source values before dispatch begins."""

    def __init__(
        self,
        definitions: WorkflowDefinitionModule,
        datasets: DatasetModule,
        transforms: TransformModule,
        gateway: PluginGatewayModule | None,
        store: WorkflowRunStore,
        *,
        project_files: ProjectFilesModule | None = None,
    ) -> None:
        self._definitions = definitions
        self._datasets = datasets
        self._transforms = transforms
        self._gateway = gateway
        self._store = store
        self._project_files = project_files

    async def recover(self) -> int:
        """Mark Runs left active by a stopped API process for guarded resumption."""
        return await self._store.interrupt_running()

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
            elif node.kind == "file":
                if self._project_files is None:
                    raise WorkflowValidationError("Project File input is unavailable.")
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
                sources[node.id] = {
                    "path": f"/project{file.path}",
                    "version": file.version,
                    "content": file.content,
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
        """Execute or safely resume a Workflow DAG through its owning Modules."""
        run = await self.load(access, project_id, run_id)
        if run.status == "succeeded":
            return run
        if run.status not in {"prepared", "interrupted"}:
            raise WorkflowRunConflict("Workflow Run is already executing or terminal.")
        graph_raw = run.snapshot.get("graph")
        if not isinstance(graph_raw, dict):
            raise WorkflowValidationError("Workflow Run graph snapshot is invalid.")
        graph = WorkflowGraph.from_json(json.dumps(graph_raw))
        expected_status = run.status
        execution_nodes = dict(_mapping(run.execution.get("nodes")))
        execution_start = replace(run, status="running", execution={"nodes": execution_nodes})
        run = await self._replace(execution_start, expected_status)
        source_snapshots = _mapping(run.snapshot.get("sources"))
        node_outputs: dict[str, dict[str, object]] = {}
        nodes = {node.id: node for node in graph.nodes}
        for node in graph.nodes:
            if node.kind == "dataset":
                source = _mapping(source_snapshots.get(node.id))
                records = source.get("records")
                if not isinstance(records, list):
                    return await self._fail(run, execution_nodes, node.id, "source_snapshot")
                node_outputs[node.id] = {
                    "records": [_mapping(record).get("value") for record in records]
                }
            elif node.kind == "file":
                source = _mapping(source_snapshots.get(node.id))
                content = source.get("content")
                if not isinstance(content, str):
                    return await self._fail(run, execution_nodes, node.id, "source_snapshot")
                node_outputs[node.id] = {"content": content}
            elif _mapping(execution_nodes.get(node.id)).get("status") == "succeeded":
                previous = _mapping(execution_nodes.get(node.id))
                if "output" not in previous:
                    return await self._fail(run, execution_nodes, node.id, "checkpoint_output")
                node_outputs[node.id] = {"result": previous["output"]}

        checkpoint_lock = asyncio.Lock()
        call_semaphore = asyncio.Semaphore(MAX_WORKFLOW_CONCURRENCY)

        async def checkpoint() -> None:
            nonlocal run
            async with checkpoint_lock:
                run = await self._save_progress(run, execution_nodes)

        pending = {node.id for node in graph.nodes if node.kind not in {"dataset", "file"}}
        pending.difference_update(node_outputs)
        target_snapshots = _mapping(run.snapshot.get("targets"))
        while pending:
            ready = sorted(
                node_id
                for node_id in pending
                if all(
                    edge.source_node in node_outputs
                    for edge in graph.edges
                    if edge.target_node == node_id
                )
            )[:MAX_WORKFLOW_CONCURRENCY]
            if not ready:
                return await self._fail(run, execution_nodes, min(pending), "upstream_output")
            work: list[tuple[WorkflowNode, dict[str, object], list[WorkflowEdge]]] = []
            for node_id in ready:
                node = nodes[node_id]
                edges = [edge for edge in graph.edges if edge.target_node == node_id]
                inputs: dict[str, object] = {}
                for edge in edges:
                    outputs = node_outputs[edge.source_node]
                    if edge.source_port not in outputs:
                        return await self._fail(run, execution_nodes, node_id, "upstream_output")
                    inputs[edge.target_port] = outputs[edge.source_port]
                work.append((node, inputs, edges))
            results = await asyncio.gather(
                *(
                    self._execute_node(
                        access,
                        project_id,
                        node,
                        _mapping(target_snapshots.get(node.id)),
                        inputs,
                        edges,
                        graph,
                        source_snapshots,
                        execution_nodes,
                        checkpoint,
                        call_semaphore,
                        run.id,
                        initiation,
                    )
                    for node, inputs, edges in work
                ),
                return_exceptions=True,
            )
            for (_, _, _), result in zip(work, results, strict=True):
                if isinstance(result, BaseException):
                    raise result
            for (node, _, _), result in zip(work, results, strict=True):
                output, error_code = cast(tuple[object | None, str | None], result)
                if error_code is not None:
                    return await self._fail(run, execution_nodes, node.id, error_code)
                node_outputs[node.id] = {"result": output}
                pending.remove(node.id)
            await checkpoint()
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

    async def _execute_node(
        self,
        access: ProjectAccess,
        project_id: str,
        node: WorkflowNode,
        target: Mapping[str, object],
        inputs: dict[str, object],
        edges: Sequence[WorkflowEdge],
        graph: WorkflowGraph,
        source_snapshots: Mapping[str, object],
        execution_nodes: dict[str, object],
        checkpoint: Callable[[], Awaitable[None]],
        call_semaphore: asyncio.Semaphore,
        workflow_run_id: str,
        initiation: TransformInitiation | None,
    ) -> tuple[object | None, str | None]:
        if node.kind == "mcp":
            return await self._execute_mcp_node(
                access,
                project_id,
                node,
                target,
                inputs,
                edges,
                graph,
                source_snapshots,
                execution_nodes,
                checkpoint,
                call_semaphore,
            )

        input_names = target.get("inputNames")
        if not isinstance(input_names, list) or not all(
            isinstance(name, str) for name in input_names
        ):
            return None, "target_snapshot"
        previous = _mapping(execution_nodes.get(node.id))
        call_context = initiation or TransformInitiation("workflowRun", "notRequired")
        if node.shape == "map":
            items = inputs.get("items")
            if (
                not isinstance(items, list)
                or len(items) > MAX_MAP_INVOCATIONS
                or len(input_names) != 1
                or not edges
            ):
                return None, "map_input"
            records = _source_records_for_edge(graph, source_snapshots, edges[0])
            item_results = _indexed_progress(previous.get("items"))
            outputs: dict[int, object] = {}
            pending_items: list[tuple[int, object]] = []
            for index, item in enumerate(items):
                saved_item = item_results.get(index)
                if saved_item is not None and saved_item.get("status") == "succeeded":
                    if "output" not in saved_item:
                        return None, "checkpoint_output"
                    outputs[index] = saved_item["output"]
                    continue
                pending_items.append((index, item))

            async def execute_item(
                index: int, item: object
            ) -> tuple[int, object | None, str | None]:
                item_identity = (
                    _mapping(records[index]).get("id")
                    if records is not None and index < len(records)
                    else f"{edges[0].source_node}:{index}"
                )
                item_results[index] = {
                    "index": index,
                    "itemId": item_identity,
                    "input": item,
                    "status": "running",
                }
                execution_nodes[node.id] = {
                    "status": "running",
                    "inputs": inputs,
                    "items": _ordered_items(item_results),
                }
                await checkpoint()
                try:
                    async with call_semaphore:
                        child = await self._transforms.start_function_call(
                            access,
                            project_id,
                            node.ref_id,
                            {input_names[0]: item},
                            {},
                            expected_revision=int(node.version),
                            initiation=call_context,
                            run_id=_child_run_id(workflow_run_id, node.id, index),
                        )
                except (
                    TransformExecutionError,
                    TransformNotFound,
                    TransformValidationError,
                ) as error:
                    item_results[index] = {
                        "index": index,
                        "input": item,
                        "status": "failed",
                        "error": (
                            error.code if isinstance(error, TransformExecutionError) else str(error)
                        ),
                    }
                    execution_nodes[node.id] = {
                        "status": "failed",
                        "inputs": inputs,
                        "items": _ordered_items(item_results),
                    }
                    await checkpoint()
                    return (
                        index,
                        None,
                        (
                            error.code
                            if isinstance(error, TransformExecutionError)
                            else "stale_target"
                        ),
                    )
                item_results[index] = {
                    "index": index,
                    "itemId": item_identity,
                    "input": item,
                    "status": child.status,
                    "transformRunId": child.id,
                    **({"output": child.output} if child.status == "succeeded" else {}),
                    **({"error": child.error} if child.error else {}),
                }
                if child.status != "succeeded":
                    execution_nodes[node.id] = {
                        "status": "failed",
                        "inputs": inputs,
                        "items": _ordered_items(item_results),
                    }
                    await checkpoint()
                    return index, None, "child_call_failed"
                execution_nodes[node.id] = {
                    "status": "running",
                    "inputs": inputs,
                    "items": _ordered_items(item_results),
                }
                await checkpoint()
                return index, child.output, None

            item_results_by_index = await asyncio.gather(
                *(execute_item(index, item) for index, item in pending_items),
                return_exceptions=True,
            )
            for item_result in item_results_by_index:
                if isinstance(item_result, BaseException):
                    raise item_result
            errors: list[str] = []
            for item_result in item_results_by_index:
                index, output, error_code = cast(tuple[int, object | None, str | None], item_result)
                if error_code is not None:
                    errors.append(error_code)
                else:
                    outputs[index] = output
            if errors:
                execution_nodes[node.id] = {
                    "status": "failed",
                    "inputs": inputs,
                    "items": _ordered_items(item_results),
                }
                await checkpoint()
                return None, errors[0]
            ordered_outputs = [outputs[index] for index in range(len(items))]
            result: object = ordered_outputs
            execution_nodes[node.id] = {
                "status": "succeeded",
                "inputs": inputs,
                "items": _ordered_items(item_results),
                "output": result,
            }
            await checkpoint()
            return result, None

        execution_nodes[node.id] = {"status": "running", "inputs": inputs}
        await checkpoint()
        try:
            async with call_semaphore:
                child = await self._transforms.start_function_call(
                    access,
                    project_id,
                    node.ref_id,
                    inputs,
                    {},
                    expected_revision=int(node.version),
                    initiation=call_context,
                    run_id=_child_run_id(workflow_run_id, node.id),
                )
        except (TransformExecutionError, TransformNotFound, TransformValidationError) as error:
            execution_nodes[node.id] = {
                "status": "failed",
                "inputs": inputs,
                "error": error.code if isinstance(error, TransformExecutionError) else str(error),
            }
            await checkpoint()
            return None, (
                error.code if isinstance(error, TransformExecutionError) else "stale_target"
            )
        execution_nodes[node.id] = {
            "status": child.status,
            "inputs": inputs,
            "transformRunId": child.id,
            **({"output": child.output} if child.status == "succeeded" else {}),
            **({"error": child.error} if child.error else {}),
        }
        await checkpoint()
        if child.status != "succeeded":
            return None, "child_call_failed"
        return child.output, None

    async def _execute_mcp_node(
        self,
        access: ProjectAccess,
        project_id: str,
        node: WorkflowNode,
        target: Mapping[str, object],
        inputs: Mapping[str, object],
        edges: Sequence[WorkflowEdge],
        graph: WorkflowGraph,
        source_snapshots: Mapping[str, object],
        execution_nodes: dict[str, object],
        checkpoint: Callable[[], Awaitable[None]],
        call_semaphore: asyncio.Semaphore,
    ) -> tuple[object | None, str | None]:
        """Dispatch a snapshotted MCP target through Plugin Gateway."""
        plugin_id = target.get("pluginId")
        tool_name = target.get("toolName")
        input_schema = target.get("inputSchema")
        output_schema = target.get("outputSchema")
        gateway = self._gateway
        if (
            gateway is None
            or not isinstance(plugin_id, str)
            or not isinstance(tool_name, str)
            or not isinstance(input_schema, Mapping)
            or not isinstance(output_schema, Mapping)
        ):
            return None, "invalid_target_snapshot"
        version = target.get("version")
        if not isinstance(version, str):
            return None, "invalid_target_snapshot"
        try:
            current_version = await gateway.tool_version(access, project_id, plugin_id, tool_name)
        except (
            PluginNotAvailable,
            PluginNotEnabled,
            PluginToolNotAllowed,
        ) as error:
            code = _plugin_error_code(error)
            execution_nodes[node.id] = {"status": "failed", "error": code}
            return None, code
        if current_version != version:
            execution_nodes[node.id] = {"status": "failed", "error": "stale_target"}
            return None, "stale_target"

        previous = _mapping(execution_nodes.get(node.id))
        if node.shape == "single":
            if previous.get("status") == "running":
                execution_nodes[node.id] = {
                    **previous,
                    "status": "failed",
                    "error": "mcp_outcome_unknown",
                }
                return None, "mcp_outcome_unknown"
            try:
                Draft202012Validator(input_schema).validate(dict(inputs))
            except JsonSchemaValidationError:
                execution_nodes[node.id] = {
                    "status": "failed",
                    "inputs": dict(inputs),
                    "error": "invalid_mcp_input",
                }
                return None, "invalid_mcp_input"
            execution_nodes[node.id] = {
                "status": "running",
                "inputs": dict(inputs),
                "mcpCall": {"pluginId": plugin_id, "toolName": tool_name},
            }
            await checkpoint()
            try:
                async with call_semaphore:
                    result = await gateway.call(access, project_id, plugin_id, tool_name, inputs)
            except (
                PluginCallLimitExceeded,
                PluginNotAvailable,
                PluginNotEnabled,
                PluginToolNotAllowed,
                PluginTransportError,
            ) as error:
                code = _plugin_error_code(error)
                execution_nodes[node.id] = {
                    "status": "failed",
                    "inputs": dict(inputs),
                    "error": code,
                }
                await checkpoint()
                return None, code
            output = _structured_output(result)
            if output is None:
                execution_nodes[node.id] = {
                    "status": "failed",
                    "inputs": dict(inputs),
                    "error": "missing_structured_output",
                }
                await checkpoint()
                return None, "missing_structured_output"
            try:
                Draft202012Validator(output_schema).validate(output)
            except JsonSchemaValidationError:
                execution_nodes[node.id] = {
                    "status": "failed",
                    "inputs": dict(inputs),
                    "output": output,
                    "error": "invalid_mcp_output",
                }
                await checkpoint()
                return None, "invalid_mcp_output"
            execution_nodes[node.id] = {
                "status": "succeeded",
                "inputs": dict(inputs),
                "mcpCall": {"pluginId": plugin_id, "toolName": tool_name},
                "output": output,
            }
            await checkpoint()
            return output, None

        items = inputs.get("items")
        if not isinstance(items, list) or len(items) > MAX_MAP_INVOCATIONS:
            execution_nodes[node.id] = {
                "status": "failed",
                "inputs": dict(inputs),
                "error": "map_input",
            }
            return None, "map_input"
        item_edge = next((edge for edge in edges if edge.target_port == "items"), None)
        if item_edge is None:
            return None, "map_input"
        records = _source_records_for_edge(graph, source_snapshots, item_edge)
        item_results = _indexed_progress(previous.get("items"))
        outputs: dict[int, object] = {}
        pending_items: list[tuple[int, object]] = []
        for index, item in enumerate(items):
            saved_item = item_results.get(index)
            if saved_item is not None and saved_item.get("status") == "succeeded":
                if "output" not in saved_item:
                    return None, "checkpoint_output"
                outputs[index] = saved_item["output"]
                continue
            pending_items.append((index, item))

        async def execute_item(index: int, item: object) -> tuple[int, object | None, str | None]:
            if not isinstance(item, Mapping):
                item_results[index] = {
                    "index": index,
                    "input": item,
                    "status": "failed",
                    "error": "map_input",
                }
                execution_nodes[node.id] = {
                    "status": "failed",
                    "inputs": dict(inputs),
                    "items": _ordered_items(item_results),
                }
                await checkpoint()
                return index, None, "map_input"
            call_arguments = dict(item)
            constant_inputs = {name: value for name, value in inputs.items() if name != "items"}
            collisions = call_arguments.keys() & constant_inputs.keys()
            if collisions:
                item_results[index] = {
                    "index": index,
                    "input": dict(item),
                    "status": "failed",
                    "error": "map_input_conflict",
                }
                execution_nodes[node.id] = {
                    "status": "failed",
                    "inputs": dict(inputs),
                    "items": _ordered_items(item_results),
                }
                await checkpoint()
                return index, None, "map_input_conflict"
            call_arguments.update(constant_inputs)
            item_identity = (
                _mapping(records[index]).get("id")
                if records is not None and index < len(records)
                else f"{node.id}:{index}"
            )
            item_results[index] = {
                "index": index,
                "itemId": item_identity,
                "recordInput": dict(item),
                "input": call_arguments,
                "status": "running",
                "mcpCall": {"pluginId": plugin_id, "toolName": tool_name},
            }
            execution_nodes[node.id] = {
                "status": "running",
                "inputs": dict(inputs),
                "items": _ordered_items(item_results),
            }
            await checkpoint()
            try:
                Draft202012Validator(input_schema).validate(call_arguments)
            except JsonSchemaValidationError:
                code = "invalid_mcp_input"
            else:
                try:
                    async with call_semaphore:
                        result = await gateway.batch_call(
                            access, project_id, plugin_id, tool_name, call_arguments
                        )
                except (
                    PluginCallLimitExceeded,
                    PluginNotAvailable,
                    PluginNotEnabled,
                    PluginToolNotAllowed,
                    PluginTransportError,
                ) as error:
                    code = _plugin_error_code(error)
                else:
                    output = _structured_output(result)
                    if output is None:
                        code = "missing_structured_output"
                    else:
                        try:
                            Draft202012Validator(output_schema).validate(output)
                        except JsonSchemaValidationError:
                            code = "invalid_mcp_output"
                        else:
                            code = ""
            if not code:
                item_results[index] = {
                    **item_results[index],
                    "status": "succeeded",
                    "output": output,
                }
                execution_nodes[node.id] = {
                    "status": "running",
                    "inputs": dict(inputs),
                    "items": _ordered_items(item_results),
                }
                await checkpoint()
                return index, output, None
            item_results[index] = {**item_results[index], "status": "failed", "error": code}
            execution_nodes[node.id] = {
                "status": "running",
                "inputs": dict(inputs),
                "items": _ordered_items(item_results),
            }
            await checkpoint()
            return index, None, code

        first_pending = next(((index, item) for index, item in pending_items if index == 0), None)
        if first_pending is not None:
            first_result = await execute_item(*first_pending)
            if first_result[2] is not None:
                execution_nodes[node.id] = {
                    "status": "failed",
                    "inputs": dict(inputs),
                    "items": _ordered_items(item_results),
                }
                await checkpoint()
                return None, first_result[2]
            outputs[0] = first_result[1]
        remaining = [(index, item) for index, item in pending_items if index != 0]
        item_results_by_index = await asyncio.gather(
            *(execute_item(index, item) for index, item in remaining),
            return_exceptions=True,
        )
        for item_result in item_results_by_index:
            if isinstance(item_result, BaseException):
                raise item_result
        errors: list[str] = []
        for item_result in item_results_by_index:
            index, mapped_output, error_code = cast(
                tuple[int, object | None, str | None], item_result
            )
            if error_code is not None:
                errors.append(error_code)
            else:
                outputs[index] = mapped_output
        if errors:
            execution_nodes[node.id] = {
                "status": "failed",
                "inputs": dict(inputs),
                "items": _ordered_items(item_results),
            }
            await checkpoint()
            return None, errors[0]
        ordered_outputs = [outputs[index] for index in range(len(items))]
        execution_nodes[node.id] = {
            "status": "succeeded",
            "inputs": dict(inputs),
            "items": _ordered_items(item_results),
            "output": ordered_outputs,
        }
        await checkpoint()
        return ordered_outputs, None

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


def _indexed_progress(value: object) -> dict[int, dict[str, object]]:
    if not isinstance(value, list):
        return {}
    result: dict[int, dict[str, object]] = {}
    for item in value:
        if not isinstance(item, Mapping):
            continue
        index = item.get("index")
        if isinstance(index, int) and index >= 0:
            result[index] = dict(item)
    return result


def _ordered_items(value: Mapping[int, dict[str, object]]) -> list[dict[str, object]]:
    return [value[index] for index in sorted(value)]


def _child_run_id(workflow_run_id: str, node_id: str, item_index: int | None = None) -> str:
    identity = node_id if item_index is None else f"{node_id}:{item_index}"
    return str(uuid5(UUID(workflow_run_id), identity))


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


def _structured_output(result: PluginToolResult) -> dict[str, object] | None:
    value = result.structured_content
    return dict(value) if isinstance(value, Mapping) else None


def _plugin_error_code(error: Exception) -> str:
    if isinstance(error, PluginCallLimitExceeded):
        return "plugin_call_limit"
    if isinstance(error, PluginNotAvailable):
        return "plugin_unavailable"
    if isinstance(error, PluginNotEnabled):
        return "plugin_not_enabled"
    if isinstance(error, PluginToolNotAllowed):
        return "plugin_tool_not_allowed"
    return "plugin_transport_error"
