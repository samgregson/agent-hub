import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, cast
from uuid import NAMESPACE_URL, uuid4, uuid5

from jsonschema import Draft202012Validator, ValidationError  # type: ignore[import-untyped]
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from agent_hub_api.modules.bindings import BindingModule, BindingUnavailable, CapturedFileBinding
from agent_hub_api.modules.call_review import MAX_MAP_INVOCATIONS, call_review
from agent_hub_api.modules.datasets import (
    BatchDefinition,
    DatasetModule,
    DatasetRecord,
    DatasetValidationError,
)
from agent_hub_api.modules.plugin_gateway import PluginGatewayModule
from agent_hub_api.modules.projects import ProjectAccess, ProjectModule, ProjectNotFound
from agent_hub_api.modules.transforms import (
    TransformExecutionError,
    TransformModule,
    TransformNotFound,
)
from agent_hub_api.settings import Settings

MAX_FILE_BOUND_INVOCATIONS = 100
MAX_DIRECT_CALL_INPUT_BYTES = 64_000


def _input_ports(schema: Mapping[str, object]) -> Mapping[str, Mapping[str, object]]:
    properties = schema.get("properties", {})
    if not isinstance(properties, Mapping):
        return {}
    return {
        name: cast(Mapping[str, object], port_schema)
        for name, port_schema in properties.items()
        if isinstance(name, str) and isinstance(port_schema, Mapping)
    }


class BatchRunStatus(StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    partial = "partial"


class BatchRunOrder(StrEnum):
    newest = "newest"
    oldest = "oldest"


@dataclass(frozen=True, slots=True)
class BatchInitiation:
    kind: str
    approval: str
    thread_id: str | None = None
    agent_run_id: str | None = None
    tool_call_id: str | None = None


@dataclass(frozen=True, slots=True)
class ResultRecord:
    dataset_record_id: str
    input: Mapping[str, object]
    structured_output: Mapping[str, object] | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class BatchRun:
    id: str
    project_id: str
    definition_id: str
    status: BatchRunStatus
    definition_snapshot: Mapping[str, object]
    records: tuple[ResultRecord, ...]
    created_at: datetime
    updated_at: datetime
    idempotency_key: str | None = None
    initiator_subject: str | None = None
    archived_at: datetime | None = None
    initiation: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BatchRunPage:
    items: tuple[BatchRun, ...]
    next_offset: int | None


@dataclass(frozen=True, slots=True)
class ResultRecordPage:
    items: tuple[ResultRecord, ...]
    next_offset: int | None
    summary: "ResultSummary"


@dataclass(frozen=True, slots=True)
class ResultSummary:
    total_count: int
    succeeded_count: int
    failed_count: int
    numeric_count: int = 0
    numeric_sum: float | None = None
    numeric_min: float | None = None
    numeric_max: float | None = None
    numeric_average: float | None = None


@dataclass(frozen=True, slots=True)
class McpDatasetMapPlan:
    dataset_id: str
    dataset_version: int
    plugin_id: str
    plugin_version: str
    tool_name: str
    records: tuple[DatasetRecord, ...]
    input_schema: Mapping[str, object]
    output_schema: Mapping[str, object]

    @property
    def record_ids(self) -> tuple[str, ...]:
        return tuple(record.id for record in self.records)

    @property
    def invocation_count(self) -> int:
        return len(self.records)

    def snapshot(self) -> Mapping[str, object]:
        return {
            "callKind": "mcpMap",
            "datasetId": self.dataset_id,
            "datasetVersion": self.dataset_version,
            "pluginId": self.plugin_id,
            "pluginVersion": self.plugin_version,
            "toolName": self.tool_name,
            "inputSchema": dict(self.input_schema),
            "outputSchema": dict(self.output_schema),
            "invocationCount": self.invocation_count,
            "recordIds": list(self.record_ids),
            "inputs": [dict(record.value) for record in self.records],
            "datasetRecords": [
                {
                    "id": record.id,
                    "position": record.position,
                    "sourceKey": record.source_key,
                    "value": dict(record.value),
                }
                for record in self.records
            ],
            "outputKind": "batchResultSet",
            "review": call_review(
                target_kind="mcp",
                target_id=f"{self.plugin_id}/{self.tool_name}",
                target_version=self.plugin_version,
                target_name=self.tool_name,
                shape="map",
                source={"kind": "dataset", "id": self.dataset_id, "version": self.dataset_version},
                input_ports=_input_ports(self.input_schema),
                output_schema=self.output_schema,
                bindings=[
                    {"recordId": record.id, "inputs": dict(record.value)} for record in self.records
                ],
                max_invocations=MAX_MAP_INVOCATIONS,
                output_kind="batchResultSet",
            ),
        }


@dataclass(frozen=True, slots=True)
class McpCallPlan:
    plugin_id: str
    plugin_version: str
    tool_name: str
    arguments: Mapping[str, object]
    input_schema: Mapping[str, object]
    output_schema: Mapping[str, object]

    def snapshot(self) -> Mapping[str, object]:
        return {
            "callKind": "mcpCall",
            "pluginId": self.plugin_id,
            "pluginVersion": self.plugin_version,
            "toolName": self.tool_name,
            "inputs": dict(self.arguments),
            "inputSchema": dict(self.input_schema),
            "outputSchema": dict(self.output_schema),
            "invocationCount": 1,
            "outputKind": "batchResultSet",
            "review": call_review(
                target_kind="mcp",
                target_id=f"{self.plugin_id}/{self.tool_name}",
                target_version=self.plugin_version,
                target_name=self.tool_name,
                shape="single",
                source={"kind": "direct"},
                input_ports=_input_ports(self.input_schema),
                output_schema=self.output_schema,
                bindings=[{"inputs": dict(self.arguments)}],
                max_invocations=1,
                output_kind="batchResultSet",
            ),
        }


@dataclass(frozen=True, slots=True)
class PythonDatasetMapPlan:
    dataset_id: str
    dataset_version: int
    definition_id: str
    definition_revision: int
    definition_name: str
    item_input_name: str
    records: tuple[DatasetRecord, ...]
    definition_snapshot: Mapping[str, object]
    parameters: Mapping[str, object]

    def snapshot(self) -> Mapping[str, object]:
        return {
            "callKind": "pythonMap",
            "datasetId": self.dataset_id,
            "datasetVersion": self.dataset_version,
            "definitionId": self.definition_id,
            "definitionRevision": self.definition_revision,
            "name": self.definition_name,
            "itemInputName": self.item_input_name,
            "recordIds": [record.id for record in self.records],
            "inputs": [dict(record.value) for record in self.records],
            "boundInputs": [
                {"recordId": record.id, "inputs": {self.item_input_name: dict(record.value)}}
                for record in self.records
            ],
            "datasetRecords": [
                {
                    "id": record.id,
                    "position": record.position,
                    "sourceKey": record.source_key,
                    "value": dict(record.value),
                }
                for record in self.records
            ],
            "parameters": dict(self.parameters),
            "outputSchema": self.definition_snapshot["outputSchema"],
            "sourceHash": self.definition_snapshot["sourceHash"],
            "runtime": self.definition_snapshot["runtime"],
            "packageHash": self.definition_snapshot["packageHash"],
            "invocationCount": len(self.records),
            "outputKind": "batchResultSet",
            "review": call_review(
                target_kind="python",
                target_id=self.definition_id,
                target_version=self.definition_revision,
                target_name=self.definition_name,
                shape="map",
                source={"kind": "dataset", "id": self.dataset_id, "version": self.dataset_version},
                input_ports={self.item_input_name: {}},
                output_schema=cast(Mapping[str, object], self.definition_snapshot["outputSchema"]),
                bindings=[
                    {"recordId": record.id, "inputs": {self.item_input_name: dict(record.value)}}
                    for record in self.records
                ],
                max_invocations=MAX_MAP_INVOCATIONS,
                output_kind="batchResultSet",
            ),
        }


class BatchRunNotFound(Exception):
    pass


class McpCallValidationError(Exception):
    pass


class BatchRunIdempotencyConflict(Exception):
    """An idempotency key already identifies another Batch Definition."""


class BatchRunNotArchivable(Exception):
    """A non-terminal Batch Run cannot be archived."""


class BatchRunStore(Protocol):
    async def create_or_load(self, run: BatchRun) -> tuple[BatchRun, bool]: ...
    async def load_by_idempotency_key(
        self, project_id: str, idempotency_key: str
    ) -> BatchRun | None: ...
    async def load(self, project_id: str, run_id: str) -> BatchRun | None: ...
    async def list(
        self,
        project_id: str,
        definition_id: str | None = None,
        status: BatchRunStatus | None = None,
        order: BatchRunOrder = BatchRunOrder.newest,
        limit: int = 10,
        offset: int = 0,
        include_archived: bool = False,
    ) -> BatchRunPage: ...
    async def replace(self, run: BatchRun) -> BatchRun | None: ...
    async def reconcile_non_terminal(self, now: datetime) -> int: ...
    async def non_terminal(self) -> tuple[BatchRun, ...]: ...


class BatchExecutionModule:
    """Own one-record Batch Run persistence and repeat-safe MCP execution."""

    def __init__(
        self,
        projects: ProjectModule,
        datasets: DatasetModule,
        gateway: PluginGatewayModule,
        store: BatchRunStore,
        max_concurrency: int = 4,
        transforms: TransformModule | None = None,
        bindings: BindingModule | None = None,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least one")
        self._projects, self._datasets, self._gateway, self._store = (
            projects,
            datasets,
            gateway,
            store,
        )
        self._max_concurrency = max_concurrency
        self._transforms = transforms
        self._bindings = bindings
        self._tasks: dict[tuple[str, str], asyncio.Task[BatchRun]] = {}

    async def plan_python_dataset_map(
        self,
        access: ProjectAccess,
        project_id: str,
        definition_id: str,
        dataset_id: str,
        parameters: Mapping[str, object] | None = None,
    ) -> PythonDatasetMapPlan:
        """Review an explicit Map of a one-input Python Function over Dataset Records."""
        await self._authorize(access, project_id)
        if self._transforms is None:
            raise DatasetValidationError("Python Function execution is unavailable.")
        dataset = await self._datasets.load_dataset(access, project_id, dataset_id)
        if not dataset.records:
            raise DatasetValidationError("Dataset has no Records to map.")
        if len(dataset.records) > MAX_MAP_INVOCATIONS:
            raise DatasetValidationError("Python Map is limited to 100 Records.")
        definition, item_input_name = await self._transforms.function_map_snapshot(
            access,
            project_id,
            definition_id,
            tuple(record.value for record in dataset.records),
            parameters or {},
        )
        return PythonDatasetMapPlan(
            dataset.id,
            dataset.version,
            definition_id,
            cast(int, definition["revision"]),
            cast(str, definition["name"]),
            item_input_name,
            dataset.records,
            definition,
            dict(parameters or {}),
        )

    async def submit_python_dataset_map(
        self,
        access: ProjectAccess,
        project_id: str,
        definition_id: str,
        dataset_id: str,
        expected_dataset_version: int,
        expected_definition_revision: int,
        idempotency_key: str | None = None,
        *,
        initiation: BatchInitiation | None = None,
        parameters: Mapping[str, object] | None = None,
    ) -> BatchRun:
        """Capture a reviewed Python Function Map in the existing Result Set store."""
        await self._authorize(access, project_id)
        existing = await self._idempotent_existing(project_id, definition_id, idempotency_key)
        if existing is not None:
            if (
                existing.definition_snapshot.get("callKind") != "pythonMap"
                or existing.definition_snapshot.get("datasetId") != dataset_id
                or existing.definition_snapshot.get("datasetVersion") != expected_dataset_version
                or existing.definition_snapshot.get("revision") != expected_definition_revision
                or existing.definition_snapshot.get("parameters", {}) != dict(parameters or {})
            ):
                raise BatchRunIdempotencyConflict(
                    "This idempotency key identifies another Python Map."
                )
            return existing
        plan = await self.plan_python_dataset_map(
            access, project_id, definition_id, dataset_id, parameters
        )
        if (
            plan.dataset_version != expected_dataset_version
            or plan.definition_revision != expected_definition_revision
        ):
            raise DatasetValidationError("Dataset or Function changed; review the Map again.")
        now = datetime.now(UTC)
        run = BatchRun(
            id=str(uuid4()),
            project_id=project_id,
            definition_id=definition_id,
            status=BatchRunStatus.queued,
            definition_snapshot={
                **plan.definition_snapshot,
                "review": plan.snapshot()["review"],
                **_dataset_snapshot(plan.dataset_id, plan.dataset_version, plan.records),
                "callKind": "pythonMap",
                "datasetId": plan.dataset_id,
                "definitionName": plan.definition_name,
                "itemInputName": plan.item_input_name,
                "mode": "perRecord",
                "parameters": dict(plan.parameters),
                "recordIds": [record.id for record in plan.records],
                "maxConcurrency": self._max_concurrency,
            },
            records=tuple(ResultRecord(record.id, dict(record.value)) for record in plan.records),
            created_at=now,
            updated_at=now,
            idempotency_key=idempotency_key,
            initiator_subject=access.subject,
            initiation=_initiation_snapshot(initiation),
        )
        stored, _ = await self._store.create_or_load(run)
        if (
            stored.definition_id != definition_id
            or stored.definition_snapshot.get("callKind") != "pythonMap"
            or stored.definition_snapshot.get("datasetId") != dataset_id
            or stored.definition_snapshot.get("datasetVersion") != expected_dataset_version
            or stored.definition_snapshot.get("revision") != expected_definition_revision
            or stored.definition_snapshot.get("parameters", {}) != dict(parameters or {})
        ):
            raise BatchRunIdempotencyConflict("This idempotency key identifies another Python Map.")
        return stored

    async def plan_mcp_call(
        self,
        access: ProjectAccess,
        project_id: str,
        plugin_id: str,
        tool_name: str,
        arguments: Mapping[str, object],
    ) -> McpCallPlan:
        """Review one permitted MCP invocation with captured arguments."""
        await self._authorize(access, project_id)
        plugin_version = await self._gateway.tool_version(access, project_id, plugin_id, tool_name)
        input_schema = await self._gateway.input_schema(access, project_id, plugin_id, tool_name)
        output_schema = await self._gateway.output_schema(
            access, project_id, plugin_id, tool_name, require_repeat_safe=False
        )
        try:
            encoded = json.dumps(arguments, allow_nan=False, sort_keys=True, separators=(",", ":"))
            if len(encoded.encode()) > MAX_DIRECT_CALL_INPUT_BYTES:
                raise McpCallValidationError("MCP call arguments exceed 64000 bytes.")
            captured = json.loads(encoded)
            Draft202012Validator(input_schema).validate(captured)
        except (TypeError, ValueError, ValidationError) as error:
            raise McpCallValidationError(
                "MCP call arguments do not satisfy the input schema."
            ) from error
        if not isinstance(captured, dict):
            raise McpCallValidationError("MCP call arguments must be a JSON object.")
        return McpCallPlan(
            plugin_id,
            plugin_version,
            tool_name,
            captured,
            dict(input_schema),
            dict(output_schema),
        )

    async def submit_mcp_call(
        self,
        access: ProjectAccess,
        project_id: str,
        plugin_id: str,
        tool_name: str,
        arguments: Mapping[str, object],
        expected_plugin_version: str,
        idempotency_key: str | None = None,
        *,
        initiation: BatchInitiation | None = None,
    ) -> BatchRun:
        """Retain one direct MCP invocation in the existing Run store."""
        await self._authorize(access, project_id)
        target_id = str(uuid5(NAMESPACE_URL, f"mcp-call:{project_id}:{plugin_id}:{tool_name}"))
        existing = await self._idempotent_existing(project_id, target_id, idempotency_key)
        if existing is not None:
            if (
                existing.definition_snapshot.get("callKind") != "mcpCall"
                or existing.definition_snapshot.get("pluginVersion") != expected_plugin_version
                or existing.records[0].input != arguments
            ):
                raise BatchRunIdempotencyConflict(
                    "This idempotency key identifies another MCP call."
                )
            return existing
        plan = await self.plan_mcp_call(access, project_id, plugin_id, tool_name, arguments)
        if plan.plugin_version != expected_plugin_version:
            raise McpCallValidationError("MCP tool version changed; review the call again.")
        now = datetime.now(UTC)
        run = BatchRun(
            id=str(uuid4()),
            project_id=project_id,
            definition_id=target_id,
            status=BatchRunStatus.queued,
            definition_snapshot={
                **plan.snapshot(),
                "definitionName": tool_name,
                "maxConcurrency": 1,
            },
            records=(ResultRecord("single", dict(plan.arguments)),),
            created_at=now,
            updated_at=now,
            idempotency_key=idempotency_key,
            initiator_subject=access.subject,
            initiation=_initiation_snapshot(initiation),
        )
        stored, _ = await self._store.create_or_load(run)
        if stored.definition_id != target_id:
            raise BatchRunIdempotencyConflict("This idempotency key identifies another MCP call.")
        return stored

    async def plan_mcp_dataset(
        self,
        access: ProjectAccess,
        project_id: str,
        plugin_id: str,
        tool_name: str,
        dataset_id: str,
    ) -> McpDatasetMapPlan:
        """Review a direct Map of tool-ready Dataset Records over an MCP tool."""
        await self._authorize(access, project_id)
        dataset = await self._datasets.load_dataset(access, project_id, dataset_id)
        if not dataset.records:
            raise DatasetValidationError("Dataset has no Records to map.")
        if len(dataset.records) > MAX_MAP_INVOCATIONS:
            raise DatasetValidationError("MCP Map is limited to 100 Records.")
        plugin_version = await self._gateway.tool_version(access, project_id, plugin_id, tool_name)
        input_schema = await self._gateway.input_schema(access, project_id, plugin_id, tool_name)
        output_schema = await self._gateway.output_schema(access, project_id, plugin_id, tool_name)
        validator = Draft202012Validator(input_schema)
        for record in dataset.records:
            try:
                validator.validate(record.value)
            except ValidationError as error:
                raise DatasetValidationError(
                    f"Dataset Record {record.position + 1} does not satisfy the MCP input schema."
                ) from error
        return McpDatasetMapPlan(
            dataset.id,
            dataset.version,
            plugin_id,
            plugin_version,
            tool_name,
            dataset.records,
            dict(input_schema),
            dict(output_schema),
        )

    async def submit_mcp_dataset(
        self,
        access: ProjectAccess,
        project_id: str,
        plugin_id: str,
        tool_name: str,
        dataset_id: str,
        expected_dataset_version: int,
        expected_plugin_version: str,
        idempotency_key: str | None = None,
        *,
        initiation: BatchInitiation | None = None,
    ) -> BatchRun:
        """Retain a direct MCP Map without creating a Batch Definition."""
        await self._authorize(access, project_id)
        target_id = str(uuid5(NAMESPACE_URL, f"mcp-map:{project_id}:{plugin_id}:{tool_name}"))
        existing = await self._idempotent_existing(project_id, target_id, idempotency_key)
        if existing is not None:
            if (
                existing.definition_snapshot.get("callKind") != "mcpMap"
                or existing.definition_snapshot.get("datasetId") != dataset_id
                or existing.definition_snapshot.get("datasetVersion") != expected_dataset_version
                or existing.definition_snapshot.get("pluginVersion") != expected_plugin_version
            ):
                raise BatchRunIdempotencyConflict(
                    "This idempotency key identifies another MCP Map."
                )
            return existing
        plan = await self.plan_mcp_dataset(access, project_id, plugin_id, tool_name, dataset_id)
        if plan.dataset_version != expected_dataset_version:
            raise DatasetValidationError("Dataset changed; review the MCP Map again.")
        if plan.plugin_version != expected_plugin_version:
            raise McpCallValidationError("MCP tool version changed; review the Map again.")
        now = datetime.now(UTC)
        run = BatchRun(
            id=str(uuid4()),
            project_id=project_id,
            definition_id=target_id,
            status=BatchRunStatus.queued,
            definition_snapshot={
                **plan.snapshot(),
                "definitionName": plan.tool_name,
                **_dataset_snapshot(plan.dataset_id, plan.dataset_version, plan.records),
                "maxConcurrency": self._max_concurrency,
            },
            records=tuple(ResultRecord(record.id, dict(record.value)) for record in plan.records),
            created_at=now,
            updated_at=now,
            idempotency_key=idempotency_key,
            initiator_subject=access.subject,
            initiation=_initiation_snapshot(initiation),
        )
        stored, _ = await self._store.create_or_load(run)
        if stored.definition_id != target_id:
            raise BatchRunIdempotencyConflict("This idempotency key identifies another Batch Run.")
        return stored

    async def define_transform_batch(
        self,
        access: ProjectAccess,
        project_id: str,
        dataset_id: str,
        name: str,
        transform_definition_id: str,
    ) -> BatchDefinition:
        if self._transforms is None:
            raise DatasetValidationError("Transform execution is unavailable.")
        try:
            await self._transforms.batch_snapshot(access, project_id, transform_definition_id)
        except (TransformNotFound, TransformExecutionError) as error:
            raise DatasetValidationError("Transform Definition is unavailable.") from error
        return await self._datasets.create_transform_definition(
            access, project_id, dataset_id, name, transform_definition_id
        )

    async def submit_transform_dataset(
        self,
        access: ProjectAccess,
        project_id: str,
        transform_definition_id: str,
        dataset_id: str,
        expected_dataset_version: int,
        expected_transform_revision: int,
        idempotency_key: str | None = None,
        *,
        initiation: BatchInitiation | None = None,
        parameters: Mapping[str, object] | None = None,
    ) -> BatchRun:
        """Capture one independent invocation per Dataset Record for a Transform."""
        await self._authorize(access, project_id)
        existing = await self._idempotent_existing(
            project_id, transform_definition_id, idempotency_key
        )
        if existing is not None:
            if (
                existing.definition_snapshot.get("datasetId") != dataset_id
                or existing.definition_snapshot.get("datasetVersion") != expected_dataset_version
                or existing.definition_snapshot.get("revision") != expected_transform_revision
                or existing.definition_snapshot.get("parameters", {}) != dict(parameters or {})
            ):
                raise BatchRunIdempotencyConflict(
                    "This idempotency key identifies another Transform Run."
                )
            return existing
        if self._transforms is None:
            raise DatasetValidationError("Transform execution is unavailable.")
        snapshot = await self._transforms.batch_snapshot(
            access, project_id, transform_definition_id
        )
        if snapshot["revision"] != expected_transform_revision:
            raise DatasetValidationError("Transform Definition changed; review it again.")
        dataset = await self._datasets.load_dataset(access, project_id, dataset_id)
        if dataset.version != expected_dataset_version:
            raise DatasetValidationError("Dataset changed; review it again.")
        if not dataset.records:
            raise DatasetValidationError("Dataset has no Records to run.")
        now = datetime.now(UTC)
        run = BatchRun(
            id=str(uuid4()),
            project_id=project_id,
            definition_id=transform_definition_id,
            status=BatchRunStatus.queued,
            definition_snapshot={
                **snapshot,
                **_dataset_snapshot(dataset.id, dataset.version, dataset.records),
                "datasetId": dataset.id,
                "definitionName": snapshot["name"],
                "mode": "perRecord",
                "parameters": dict(parameters or {}),
                "maxConcurrency": self._max_concurrency,
                "recordIds": [record.id for record in dataset.records],
            },
            records=tuple(
                ResultRecord(record.id, dict(record.value)) for record in dataset.records
            ),
            created_at=now,
            updated_at=now,
            idempotency_key=idempotency_key,
            initiator_subject=access.subject,
            initiation=_initiation_snapshot(initiation),
        )
        stored, _ = await self._store.create_or_load(run)
        if (
            stored.definition_id != transform_definition_id
            or stored.definition_snapshot.get("datasetId") != dataset_id
            or stored.definition_snapshot.get("datasetVersion") != expected_dataset_version
            or stored.definition_snapshot.get("revision") != expected_transform_revision
            or stored.definition_snapshot.get("parameters", {}) != dict(parameters or {})
        ):
            raise BatchRunIdempotencyConflict(
                "This idempotency key identifies another Transform Run."
            )
        return stored

    async def start_one(
        self,
        access: ProjectAccess,
        project_id: str,
        definition_id: str,
        record_id: str,
        idempotency_key: str | None = None,
        *,
        initiation: BatchInitiation | None = None,
    ) -> BatchRun:
        run = await self.submit_one(
            access,
            project_id,
            definition_id,
            record_id,
            idempotency_key,
            initiation=initiation,
        )
        return await self.execute(access, project_id, run.id)

    async def submit_one(
        self,
        access: ProjectAccess,
        project_id: str,
        definition_id: str,
        record_id: str,
        idempotency_key: str | None = None,
        *,
        initiation: BatchInitiation | None = None,
    ) -> BatchRun:
        await self._authorize(access, project_id)
        existing = await self._idempotent_existing(project_id, definition_id, idempotency_key)
        if existing is not None:
            return existing
        definition = await self._datasets.load_definition(access, project_id, definition_id)
        binding = await self._capture_binding(access, project_id, definition)
        snapshot = await self._definition_snapshot(access, project_id, definition)
        dataset = await self._datasets.load_dataset(access, project_id, definition.dataset_id)
        record = next((item for item in dataset.records if item.id == record_id), None)
        if record is None:
            raise BatchRunNotFound
        arguments = (
            dict(record.value)
            if definition.transform_definition_id
            else _bound_arguments(record.value, definition, binding)
        )
        now = datetime.now(UTC)
        run = BatchRun(
            str(uuid4()),
            project_id,
            definition.id,
            BatchRunStatus.queued,
            {
                **snapshot,
                **_dataset_snapshot(dataset.id, dataset.version, (record,)),
                **({"fileBinding": binding.snapshot()} if binding else {}),
            },
            (ResultRecord(record.id, arguments),),
            now,
            now,
            idempotency_key,
            access.subject,
            initiation=_initiation_snapshot(initiation),
        )
        run, created = await self._store.create_or_load(run)
        if run.definition_id != definition_id:
            raise BatchRunIdempotencyConflict("This idempotency key identifies another Batch Run.")
        return run

    async def start_all(
        self,
        access: ProjectAccess,
        project_id: str,
        definition_id: str,
        idempotency_key: str | None = None,
        *,
        initiation: BatchInitiation | None = None,
    ) -> BatchRun:
        run = await self.submit_all(
            access, project_id, definition_id, idempotency_key, initiation=initiation
        )
        return await self.execute(access, project_id, run.id)

    async def submit_all(
        self,
        access: ProjectAccess,
        project_id: str,
        definition_id: str,
        idempotency_key: str | None = None,
        *,
        initiation: BatchInitiation | None = None,
    ) -> BatchRun:
        """Execute a captured Dataset after its first record succeeds."""
        await self._authorize(access, project_id)
        existing = await self._idempotent_existing(project_id, definition_id, idempotency_key)
        if existing is not None:
            return existing
        definition = await self._datasets.load_definition(access, project_id, definition_id)
        binding = await self._capture_binding(access, project_id, definition)
        snapshot = await self._definition_snapshot(access, project_id, definition)
        dataset = await self._datasets.load_dataset(access, project_id, definition.dataset_id)
        if not dataset.records:
            raise BatchRunNotFound
        if binding is not None and len(dataset.records) > MAX_FILE_BOUND_INVOCATIONS:
            raise BindingUnavailable("A file-bound Batch Run is limited to 100 Records.")
        now = datetime.now(UTC)
        captured = tuple(
            (
                record.id,
                dict(record.value)
                if definition.transform_definition_id
                else _bound_arguments(record.value, definition, binding),
            )
            for record in dataset.records
        )
        run = BatchRun(
            str(uuid4()),
            project_id,
            definition.id,
            BatchRunStatus.queued,
            {
                **snapshot,
                **_dataset_snapshot(dataset.id, dataset.version, dataset.records),
                **({"fileBinding": binding.snapshot()} if binding else {}),
                "maxConcurrency": self._max_concurrency,
                "recordIds": [record_id for record_id, _ in captured],
            },
            tuple(ResultRecord(record_id, arguments) for record_id, arguments in captured),
            now,
            now,
            idempotency_key,
            access.subject,
            initiation=_initiation_snapshot(initiation),
        )
        run, created = await self._store.create_or_load(run)
        if run.definition_id != definition_id:
            raise BatchRunIdempotencyConflict("This idempotency key identifies another Batch Run.")
        return run

    async def _idempotent_existing(
        self, project_id: str, definition_id: str, idempotency_key: str | None
    ) -> BatchRun | None:
        if idempotency_key is None:
            return None
        existing = await self._store.load_by_idempotency_key(project_id, idempotency_key)
        if existing is not None and existing.definition_id != definition_id:
            raise BatchRunIdempotencyConflict("This idempotency key identifies another Batch Run.")
        return existing

    async def execute(self, access: ProjectAccess, project_id: str, run_id: str) -> BatchRun:
        run = await self.load(access, project_id, run_id)
        if run.status not in {BatchRunStatus.queued, BatchRunStatus.running}:
            return run
        running = replace(run, status=BatchRunStatus.running, updated_at=datetime.now(UTC))
        await self._store.replace(running)
        if run.definition_snapshot.get("callKind") in {"mcpCall", "mcpMap"}:
            try:
                await self._assert_reviewed_mcp_version(access, project_id, run.definition_snapshot)
            except Exception as error:
                records = tuple(
                    record
                    if record.structured_output is not None or record.error is not None
                    else replace(record, error=str(error))
                    for record in running.records
                )
                stopped = replace(
                    running,
                    status=(
                        BatchRunStatus.partial
                        if any(record.structured_output is not None for record in records)
                        else BatchRunStatus.failed
                    ),
                    records=records,
                    updated_at=datetime.now(UTC),
                )
                return await self._store.replace(stopped) or stopped
        first = running.records[0]
        if first.structured_output is None and first.error is None:
            first = await self._execute_snapshot(access, project_id, running, first)
        progress = replace(
            running,
            records=(first, *running.records[1:]),
            updated_at=datetime.now(UTC),
        )
        await self._store.replace(progress)
        if first.error and running.definition_snapshot.get("mode") != "perRecord":
            failed = replace(progress, status=BatchRunStatus.failed, updated_at=datetime.now(UTC))
            return await self._store.replace(failed) or failed
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def execute_bounded(record: ResultRecord) -> ResultRecord:
            async with semaphore:
                return await self._execute_snapshot(access, project_id, running, record)

        pending = tuple(
            record
            for record in running.records[1:]
            if record.structured_output is None and record.error is None
        )
        executed = await asyncio.gather(*(execute_bounded(record) for record in pending))
        completed_records = {record.dataset_record_id: record for record in executed}
        remaining = tuple(
            completed_records.get(record.dataset_record_id, record)
            for record in running.records[1:]
        )
        completed = replace(
            progress,
            status=(
                BatchRunStatus.failed
                if all(record.error for record in (first, *remaining))
                else BatchRunStatus.partial
                if any(record.error for record in (first, *remaining))
                else BatchRunStatus.succeeded
            ),
            records=(first, *remaining),
            updated_at=datetime.now(UTC),
        )
        return await self._store.replace(completed) or completed

    async def enqueue(
        self, access: ProjectAccess, project_id: str, run_id: str
    ) -> asyncio.Task[BatchRun]:
        """Schedule one durable Batch Run once within this host process."""
        await self.load(access, project_id, run_id)
        key = (project_id, run_id)
        task = self._tasks.get(key)
        if task is not None and not task.done():
            return task
        task = asyncio.create_task(self.execute(access, project_id, run_id))
        self._tasks[key] = task
        task.add_done_callback(lambda _: self._tasks.pop(key, None))
        return task

    async def _execute_snapshot(
        self, access: ProjectAccess, project_id: str, run: BatchRun, record: ResultRecord
    ) -> ResultRecord:
        try:
            if "transformDefinitionId" in run.definition_snapshot:
                if self._transforms is None:
                    raise ValueError("The Transform runner is unavailable.")
                output = await self._transforms.execute_batch_record(
                    access,
                    project_id,
                    run.definition_snapshot,
                    record.input,
                    cast(Mapping[str, object], run.definition_snapshot.get("parameters", {})),
                )
                return ResultRecord(record.dataset_record_id, record.input, output)
            plugin_id = run.definition_snapshot.get("pluginId")
            tool_name = run.definition_snapshot.get("toolName")
            if not isinstance(plugin_id, str) or not isinstance(tool_name, str):
                raise ValueError("The Batch Run has no MCP tool target.")
            if run.definition_snapshot.get("callKind") in {"mcpCall", "mcpMap"}:
                await self._assert_reviewed_mcp_version(access, project_id, run.definition_snapshot)
            result = await (
                self._gateway.call(access, project_id, plugin_id, tool_name, record.input)
                if run.definition_snapshot.get("callKind") == "mcpCall"
                else self._gateway.batch_call(
                    access, project_id, plugin_id, tool_name, record.input
                )
            )
            if result.structured_content is None:
                raise ValueError("The tool returned no structured output.")
            output_schema = run.definition_snapshot.get("outputSchema")
            if not isinstance(output_schema, Mapping):
                raise ValueError("The Batch Run has no declared MCP output schema.")
            Draft202012Validator(output_schema).validate(result.structured_content)
            return ResultRecord(record.dataset_record_id, record.input, result.structured_content)
        except Exception as error:
            return ResultRecord(record.dataset_record_id, record.input, error=str(error))

    async def _assert_reviewed_mcp_version(
        self, access: ProjectAccess, project_id: str, snapshot: Mapping[str, object]
    ) -> None:
        plugin_id = snapshot.get("pluginId")
        tool_name = snapshot.get("toolName")
        if not isinstance(plugin_id, str) or not isinstance(tool_name, str):
            raise ValueError("The Batch Run has no MCP tool target.")
        current_version = await self._gateway.tool_version(access, project_id, plugin_id, tool_name)
        reviewed_version = snapshot.get("pluginVersion")
        if reviewed_version != current_version:
            raise ValueError(
                "MCP tool version changed since this Run was queued "
                f"({reviewed_version} → {current_version})."
            )

    async def _execute(
        self,
        access: ProjectAccess,
        project_id: str,
        definition: BatchDefinition,
        record_id: str,
        arguments: Mapping[str, object],
    ) -> ResultRecord:
        try:
            if definition.plugin_id is None or definition.tool_name is None:
                raise ValueError("The Batch Definition has no MCP tool target.")
            result = await self._gateway.batch_call(
                access, project_id, definition.plugin_id, definition.tool_name, arguments
            )
            if result.structured_content is None:
                raise ValueError("The tool returned no structured output.")
            return ResultRecord(record_id, arguments, result.structured_content)
        except Exception as error:
            return ResultRecord(record_id, arguments, error=str(error))

    async def load(self, access: ProjectAccess, project_id: str, run_id: str) -> BatchRun:
        await self._authorize(access, project_id)
        run = await self._store.load(project_id, run_id)
        if run is None:
            raise BatchRunNotFound
        return run

    async def archive(self, access: ProjectAccess, project_id: str, run_id: str) -> BatchRun:
        """Hide one completed Batch Run without erasing its Result Set."""
        run = await self.load(access, project_id, run_id)
        if run.status in {BatchRunStatus.queued, BatchRunStatus.running}:
            raise BatchRunNotArchivable
        if run.archived_at is not None:
            return run
        archived = replace(run, archived_at=datetime.now(UTC))
        return await self._store.replace(archived) or archived

    async def inspect_results(
        self,
        access: ProjectAccess,
        project_id: str,
        run_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
        filter_path: str | None = None,
        equals: str | int | float | bool | None = None,
        minimum: int | float | None = None,
        maximum: int | float | None = None,
        sort_path: str | None = None,
        descending: bool = False,
        aggregate_path: str | None = None,
    ) -> ResultRecordPage:
        """Read one bounded page from a durable Result Set."""
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError(
                "Result Set pagination requires a limit from 1 to 100 and an offset >= 0."
            )
        run = await self.load(access, project_id, run_id)
        if (equals is not None or minimum is not None or maximum is not None) and not filter_path:
            raise ValueError("A filter path is required for scalar comparisons.")
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValueError("Minimum cannot exceed maximum.")
        if filter_path is not None:
            _validate_result_path(filter_path)
        if sort_path is not None:
            _validate_result_path(sort_path)
        if aggregate_path is not None:
            _validate_result_path(aggregate_path)
        records = [
            record
            for record in run.records
            if filter_path is None or _matches_result(record, filter_path, equals, minimum, maximum)
        ]
        if sort_path is not None:
            records.sort(
                key=lambda record: _sort_value(_result_value(record, sort_path)),
                reverse=descending,
            )
            records.sort(key=lambda record: _result_value(record, sort_path) is None)
        items = tuple(records[offset : offset + limit])
        next_offset = offset + len(items) if offset + len(items) < len(records) else None
        values = [
            value
            for record in records
            if aggregate_path is not None
            if (value := _result_value(record, aggregate_path)) is not None
            and not isinstance(value, bool)
            and isinstance(value, (int, float))
        ]
        total = sum(values) if values else None
        return ResultRecordPage(
            items,
            next_offset,
            ResultSummary(
                total_count=len(records),
                succeeded_count=sum(record.structured_output is not None for record in records),
                failed_count=sum(record.error is not None for record in records),
                numeric_count=len(values),
                numeric_sum=total,
                numeric_min=min(values) if values else None,
                numeric_max=max(values) if values else None,
                numeric_average=total / len(values) if total is not None else None,
            ),
        )

    async def list(
        self,
        access: ProjectAccess,
        project_id: str,
        definition_id: str | None = None,
        status: BatchRunStatus | None = None,
        order: BatchRunOrder = BatchRunOrder.newest,
        limit: int = 10,
        offset: int = 0,
        include_archived: bool = False,
    ) -> BatchRunPage:
        await self._authorize(access, project_id)
        return await self._store.list(
            project_id, definition_id, status, order, limit, offset, include_archived
        )

    async def reconcile_non_terminal(self) -> int:
        """Make interrupted in-process work visible and safely retryable."""
        return await self._store.reconcile_non_terminal(datetime.now(UTC))

    async def recoverable(self) -> tuple[BatchRun, ...]:
        """Return durable work that a new process can safely reclaim."""
        return tuple(
            run for run in await self._store.non_terminal() if run.initiator_subject is not None
        )

    async def recover(self) -> tuple[asyncio.Task[BatchRun], ...]:
        """Schedule durable non-terminal runs after a host restart."""
        tasks: list[asyncio.Task[BatchRun]] = []
        for run in await self.recoverable():
            assert run.initiator_subject is not None
            tasks.append(
                await self.enqueue(
                    ProjectAccess(subject=run.initiator_subject), run.project_id, run.id
                )
            )
        return tuple(tasks)

    async def _authorize(self, access: ProjectAccess, project_id: str) -> None:
        try:
            await self._projects.load(access, project_id)
        except ProjectNotFound as error:
            raise BatchRunNotFound from error

    async def _definition_snapshot(
        self, access: ProjectAccess, project_id: str, definition: BatchDefinition
    ) -> Mapping[str, object]:
        if definition.transform_definition_id is not None:
            if self._transforms is None:
                raise BatchRunNotFound
            try:
                transform_snapshot = await self._transforms.batch_snapshot(
                    access, project_id, definition.transform_definition_id
                )
            except TransformNotFound as error:
                raise BatchRunNotFound from error
            return {
                "datasetId": definition.dataset_id,
                "definitionName": definition.name,
                **transform_snapshot,
            }
        if definition.plugin_id is None or definition.tool_name is None:
            raise BatchRunNotFound
        schema = await self._gateway.output_schema(
            access, project_id, definition.plugin_id, definition.tool_name
        )
        return _snapshot(definition, schema)

    async def _capture_binding(
        self, access: ProjectAccess, project_id: str, definition: BatchDefinition
    ) -> CapturedFileBinding | None:
        if definition.file_argument is None:
            return None
        if self._bindings is None:
            raise BindingUnavailable("File Bindings are unavailable.")
        return await self._bindings.capture(access, project_id, definition)


class MemoryBatchRunStore:
    def __init__(self) -> None:
        self._runs: dict[tuple[str, str], BatchRun] = {}
        self._idempotency_keys: dict[tuple[str, str], str] = {}

    async def create_or_load(self, run: BatchRun) -> tuple[BatchRun, bool]:
        if run.idempotency_key is not None:
            existing_id = self._idempotency_keys.get((run.project_id, run.idempotency_key))
            if existing_id is not None:
                return self._runs[(run.project_id, existing_id)], False
        self._runs[(run.project_id, run.id)] = run
        if run.idempotency_key is not None:
            self._idempotency_keys[(run.project_id, run.idempotency_key)] = run.id
        return run, True

    async def load_by_idempotency_key(
        self, project_id: str, idempotency_key: str
    ) -> BatchRun | None:
        run_id = self._idempotency_keys.get((project_id, idempotency_key))
        return self._runs.get((project_id, run_id)) if run_id is not None else None

    async def load(self, project_id: str, run_id: str) -> BatchRun | None:
        return self._runs.get((project_id, run_id))

    async def list(
        self,
        project_id: str,
        definition_id: str | None = None,
        status: BatchRunStatus | None = None,
        order: BatchRunOrder = BatchRunOrder.newest,
        limit: int = 10,
        offset: int = 0,
        include_archived: bool = False,
    ) -> BatchRunPage:
        runs = sorted(
            (
                run
                for (stored_project_id, _), run in self._runs.items()
                if stored_project_id == project_id
                and (definition_id is None or run.definition_id == definition_id)
                and (status is None or run.status is status)
                and (include_archived or run.archived_at is None)
            ),
            key=lambda run: run.updated_at,
            reverse=order is BatchRunOrder.newest,
        )
        items = tuple(runs[offset : offset + limit])
        next_offset = offset + len(items) if offset + len(items) < len(runs) else None
        return BatchRunPage(items, next_offset)

    async def replace(self, run: BatchRun) -> BatchRun | None:
        if (run.project_id, run.id) not in self._runs:
            return None
        self._runs[(run.project_id, run.id)] = run
        return run

    async def reconcile_non_terminal(self, now: datetime) -> int:
        runs = tuple(self._runs.items())
        reconciled = 0
        for key, run in runs:
            if run.status in {BatchRunStatus.queued, BatchRunStatus.running}:
                self._runs[key] = replace(run, status=BatchRunStatus.failed, updated_at=now)
                reconciled += 1
        return reconciled

    async def non_terminal(self) -> tuple[BatchRun, ...]:
        return tuple(
            run
            for run in self._runs.values()
            if run.status in {BatchRunStatus.queued, BatchRunStatus.running}
        )


class PostgresBatchRunStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def _connect(self) -> AsyncConnection[dict[str, object]]:
        return await AsyncConnection.connect(
            str(self._settings.database_url),
            connect_timeout=self._settings.database_connect_timeout_seconds,
            row_factory=dict_row,
        )

    async def create_or_load(self, run: BatchRun) -> tuple[BatchRun, bool]:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """INSERT INTO batch_runs
                (project_id,batch_run_id,batch_definition_id,status,definition_snapshot,created_at,updated_at,idempotency_key,initiator_subject,initiation)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (project_id,idempotency_key)
                WHERE idempotency_key IS NOT NULL DO NOTHING
                RETURNING batch_run_id""",
                (
                    run.project_id,
                    run.id,
                    run.definition_id,
                    run.status.value,
                    json.dumps(run.definition_snapshot),
                    run.created_at,
                    run.updated_at,
                    run.idempotency_key,
                    run.initiator_subject,
                    json.dumps(run.initiation),
                ),
            )
            if await cursor.fetchone() is not None:
                await _insert_result_records(connection, run)
                return run, True
            if run.idempotency_key is not None:
                cursor = await connection.execute(
                    """SELECT batch_run_id FROM batch_runs
                    WHERE project_id=%s AND idempotency_key=%s""",
                    (run.project_id, run.idempotency_key),
                )
                row = await cursor.fetchone()
                if row is not None:
                    existing = await _load(connection, run.project_id, str(row["batch_run_id"]))
                    if existing is not None:
                        return existing, False
            raise RuntimeError("Batch Run could not be created")

    async def load(self, project_id: str, run_id: str) -> BatchRun | None:
        connection = await self._connect()
        async with connection:
            return await _load(connection, project_id, run_id)

    async def load_by_idempotency_key(
        self, project_id: str, idempotency_key: str
    ) -> BatchRun | None:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """SELECT batch_run_id FROM batch_runs
                WHERE project_id=%s AND idempotency_key=%s""",
                (project_id, idempotency_key),
            )
            row = await cursor.fetchone()
            return await _load(connection, project_id, str(row["batch_run_id"])) if row else None

    async def list(
        self,
        project_id: str,
        definition_id: str | None = None,
        status: BatchRunStatus | None = None,
        order: BatchRunOrder = BatchRunOrder.newest,
        limit: int = 10,
        offset: int = 0,
        include_archived: bool = False,
    ) -> BatchRunPage:
        connection = await self._connect()
        async with connection:
            clauses = ["project_id=%s"]
            parameters: list[object] = [project_id]
            if definition_id is not None:
                clauses.append("batch_definition_id=%s")
                parameters.append(definition_id)
            if status is not None:
                clauses.append("status=%s")
                parameters.append(status.value)
            if not include_archived:
                clauses.append("archived_at IS NULL")
            direction = "DESC" if order is BatchRunOrder.newest else "ASC"
            cursor = await connection.execute(
                f"""SELECT batch_run_id FROM batch_runs WHERE {" AND ".join(clauses)}
                ORDER BY updated_at {direction} LIMIT %s OFFSET %s""",
                (*parameters, limit + 1, offset),
            )
            rows = await cursor.fetchall()
            runs: list[BatchRun] = []
            for row in rows[:limit]:
                run = await _load(connection, project_id, str(row["batch_run_id"]))
                if run is not None:
                    runs.append(run)
            return BatchRunPage(tuple(runs), offset + limit if len(rows) > limit else None)

    async def replace(self, run: BatchRun) -> BatchRun | None:
        connection = await self._connect()
        async with connection:
            if await _load(connection, run.project_id, run.id) is None:
                return None
            await _save(connection, run, True)
        return run

    async def reconcile_non_terminal(self, now: datetime) -> int:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """UPDATE batch_runs SET status='failed', updated_at=%s
                WHERE status IN ('queued', 'running')""",
                (now,),
            )
            return cursor.rowcount

    async def non_terminal(self) -> tuple[BatchRun, ...]:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """SELECT project_id, batch_run_id FROM batch_runs
                WHERE status IN ('queued', 'running')"""
            )
            runs: list[BatchRun] = []
            for row in await cursor.fetchall():
                run = await _load(connection, str(row["project_id"]), str(row["batch_run_id"]))
                if run is not None:
                    runs.append(run)
            return tuple(runs)


async def _save(
    connection: AsyncConnection[dict[str, object]], run: BatchRun, replace_run: bool
) -> None:
    if replace_run:
        await connection.execute(
            """UPDATE batch_runs
            SET status=%s, definition_snapshot=%s, updated_at=%s, archived_at=%s
            WHERE project_id=%s AND batch_run_id=%s""",
            (
                run.status.value,
                json.dumps(run.definition_snapshot),
                run.updated_at,
                run.archived_at,
                run.project_id,
                run.id,
            ),
        )
        for record in run.records:
            await connection.execute(
                """UPDATE batch_result_records
                SET structured_output=%s, error=%s
                WHERE project_id=%s AND batch_run_id=%s AND dataset_record_id=%s""",
                (
                    json.dumps(record.structured_output) if record.structured_output else None,
                    record.error,
                    run.project_id,
                    run.id,
                    record.dataset_record_id,
                ),
            )
    else:
        await connection.execute(
            """INSERT INTO batch_runs
            (project_id,batch_run_id,batch_definition_id,status,definition_snapshot,created_at,updated_at,idempotency_key,initiator_subject,archived_at,initiation)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                run.project_id,
                run.id,
                run.definition_id,
                run.status.value,
                json.dumps(run.definition_snapshot),
                run.created_at,
                run.updated_at,
                run.idempotency_key,
                run.initiator_subject,
                run.archived_at,
                json.dumps(run.initiation),
            ),
        )
        await _insert_result_records(connection, run)


async def _insert_result_records(
    connection: AsyncConnection[dict[str, object]], run: BatchRun
) -> None:
    for position, record in enumerate(run.records):
        await connection.execute(
            """INSERT INTO batch_result_records
            (project_id,batch_run_id,dataset_record_id,position,input,structured_output,error)
            VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (
                run.project_id,
                run.id,
                record.dataset_record_id,
                position,
                json.dumps(record.input),
                json.dumps(record.structured_output) if record.structured_output else None,
                record.error,
            ),
        )


async def _load(
    connection: AsyncConnection[dict[str, object]], project_id: str, run_id: str
) -> BatchRun | None:
    cursor = await connection.execute(
        "SELECT * FROM batch_runs WHERE project_id=%s AND batch_run_id=%s", (project_id, run_id)
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    cursor = await connection.execute(
        """SELECT * FROM batch_result_records WHERE project_id=%s AND batch_run_id=%s
        ORDER BY position, dataset_record_id""",
        (project_id, run_id),
    )
    records = tuple(
        ResultRecord(
            str(item["dataset_record_id"]),
            _obj(item["input"]),
            _obj(item["structured_output"]) if item["structured_output"] is not None else None,
            str(item["error"]) if item["error"] else None,
        )
        for item in await cursor.fetchall()
    )
    return BatchRun(
        str(row["batch_run_id"]),
        project_id,
        str(row["batch_definition_id"]),
        BatchRunStatus(str(row["status"])),
        _obj(row["definition_snapshot"]),
        records,
        cast(datetime, row["created_at"]),
        cast(datetime, row["updated_at"]),
        str(row["idempotency_key"]) if row["idempotency_key"] is not None else None,
        str(row["initiator_subject"]) if row["initiator_subject"] is not None else None,
        cast(datetime | None, row["archived_at"]),
        _obj(row["initiation"]),
    )


def _obj(value: object) -> Mapping[str, object]:
    if isinstance(value, str):
        value = json.loads(value)
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError("Stored Batch Run JSON must be an object")


def _initiation_snapshot(initiation: BatchInitiation | None) -> Mapping[str, object]:
    context = initiation or BatchInitiation("directUser", "notRequired")
    return {
        "kind": context.kind,
        "approval": context.approval,
        "threadId": context.thread_id,
        "agentRunId": context.agent_run_id,
        "toolCallId": context.tool_call_id,
    }


def _select(value: Mapping[str, object], pointer: str) -> object:
    current: object = value
    for token in pointer[1:].split("/"):
        if not isinstance(current, Mapping):
            raise ValueError("Mapping no longer identifies a value.")
        current = current[token.replace("~1", "/").replace("~0", "~")]
    return current


def _arguments(value: Mapping[str, object], definition: BatchDefinition) -> Mapping[str, object]:
    return {name: _select(value, pointer) for name, pointer in definition.argument_mappings.items()}


def _bound_arguments(
    value: Mapping[str, object],
    definition: BatchDefinition,
    binding: CapturedFileBinding | None,
) -> Mapping[str, object]:
    arguments = dict(_arguments(value, definition))
    if binding is not None:
        arguments[binding.argument] = binding.content
        try:
            Draft202012Validator(definition.input_schema).validate(arguments)
        except ValidationError as error:
            raise BindingUnavailable(
                "Bound arguments do not satisfy the MCP input schema."
            ) from error
    return arguments


def _validate_result_path(path: str) -> None:
    if not (path.startswith(("/input/", "/structuredOutput/")) or path == "/error"):
        raise ValueError("Result paths must select input, structuredOutput, or error.")


def _result_value(record: ResultRecord, path: str) -> object | None:
    parts = path[1:].split("/")
    value: object = {
        "input": record.input,
        "structuredOutput": record.structured_output,
        "error": record.error,
    }[parts[0]]
    for part in parts[1:]:
        if not isinstance(value, Mapping):
            return None
        value = value.get(part.replace("~1", "/").replace("~0", "~"))
    return value if isinstance(value, (str, int, float, bool)) else None


def _matches_result(
    record: ResultRecord,
    path: str,
    equals: str | int | float | bool | None,
    minimum: int | float | None,
    maximum: int | float | None,
) -> bool:
    value = _result_value(record, path)
    if value is None:
        return False
    same_numeric_type = (
        not isinstance(value, bool)
        and not isinstance(equals, bool)
        and isinstance(value, (int, float))
        and isinstance(equals, (int, float))
    )
    if equals is not None and not (same_numeric_type or type(value) is type(equals)):
        return False
    if equals is not None and value != equals:
        return False
    if minimum is not None or maximum is not None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        if minimum is not None and value < minimum:
            return False
        if maximum is not None and value > maximum:
            return False
    return True


def _sort_value(value: object | None) -> tuple[int, object]:
    if isinstance(value, bool):
        return (0, int(value))
    if isinstance(value, (int, float)):
        return (1, value)
    if isinstance(value, str):
        return (2, value)
    return (3, "")


def _snapshot(
    definition: BatchDefinition, output_schema: Mapping[str, object]
) -> Mapping[str, object]:
    return {
        "datasetId": definition.dataset_id,
        "definitionName": definition.name,
        "pluginId": definition.plugin_id,
        "toolName": definition.tool_name,
        "argumentMappings": definition.argument_mappings,
        "inputSchema": definition.input_schema,
        "outputSchema": dict(output_schema),
    }


def _dataset_snapshot(
    dataset_id: str, version: int, records: tuple[DatasetRecord, ...]
) -> Mapping[str, object]:
    return {
        "datasetPath": f"/.datasets/{dataset_id}.json",
        "datasetVersion": version,
        "datasetRecords": [
            {
                "id": record.id,
                "position": record.position,
                "sourceKey": record.source_key,
                "value": dict(record.value),
            }
            for record in records
        ],
    }


def create_postgres_batch_execution_module(
    settings: Settings,
    projects: ProjectModule,
    datasets: DatasetModule,
    gateway: PluginGatewayModule,
    transforms: TransformModule | None = None,
    bindings: BindingModule | None = None,
) -> BatchExecutionModule:
    return BatchExecutionModule(
        projects,
        datasets,
        gateway,
        PostgresBatchRunStore(settings),
        transforms=transforms,
        bindings=bindings,
    )
