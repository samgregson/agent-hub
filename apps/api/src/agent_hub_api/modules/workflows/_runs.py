"""Durable Workflow Run preparation and immutable execution inputs."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from agent_hub_api.modules.datasets import DatasetModule, DatasetNotFound
from agent_hub_api.modules.plugin_gateway import (
    PluginGatewayModule,
    PluginNotAvailable,
    PluginNotEnabled,
    PluginToolNotAllowed,
)
from agent_hub_api.modules.projects import ProjectAccess
from agent_hub_api.modules.transforms import TransformModule, TransformNotFound

from ._application import WorkflowDefinitionModule, WorkflowNotFound, WorkflowValidationError


@dataclass(frozen=True, slots=True)
class WorkflowRun:
    id: str
    project_id: str
    workflow_id: str
    definition_version: int
    status: str
    snapshot: Mapping[str, object]
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
            access.subject,
            idempotency_key,
            datetime.now(UTC),
        )
        return _same_workflow(await self._store.create_or_load(run), workflow_id)

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
