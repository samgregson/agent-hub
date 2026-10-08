"""Project-owned Transform Definitions and their persistence boundary."""

import ast
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import uuid4

from jsonschema import Draft202012Validator, SchemaError  # type: ignore[import-untyped]
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from agent_hub_api.modules.artifacts import (
    ArtifactDocument,
    ArtifactDraft,
    ArtifactModule,
    ArtifactMutationAccess,
    ArtifactUserActionAccess,
)
from agent_hub_api.modules.datasets import (
    Dataset,
    DatasetModule,
    DatasetNotFound,
    DatasetRecord,
    DatasetRecordInput,
)
from agent_hub_api.modules.projects import ProjectAccess, ProjectModule, ProjectNotFound
from agent_hub_api.settings import Settings


@dataclass(frozen=True, slots=True)
class TransformDefinition:
    id: str
    project_id: str
    name: str
    source: str
    input_selectors: Mapping[str, str]
    output_schema: Mapping[str, object]
    runtime: str | None
    package_hash: str | None
    source_hash: str
    revision: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class TransformPreview:
    output: object
    runtime: str
    source_hash: str


@dataclass(frozen=True, slots=True)
class TransformRuntimeIdentity:
    runtime: str
    package_hash: str
    limits: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TransformInitiation:
    kind: str
    approval: str
    thread_id: str | None = None
    agent_run_id: str | None = None


@dataclass(frozen=True, slots=True)
class TransformRun:
    id: str
    project_id: str
    definition_id: str
    status: str
    definition_snapshot: Mapping[str, object]
    inputs: Mapping[str, object]
    parameters: Mapping[str, object]
    input_hash: str
    source_hash: str
    runtime: str | None
    package_hash: str | None
    output: object | None
    output_manifest: Mapping[str, object]
    error: str | None
    initiator_subject: str
    initiation: Mapping[str, object]
    limits: Mapping[str, object]
    created_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class TransformRunPage:
    items: tuple[TransformRun, ...]
    next_offset: int | None


@dataclass(frozen=True, slots=True)
class DatasetSelection:
    dataset_id: str
    expected_version: int
    expected_definition_revision: int
    filter_path: str | None = None
    equals: str | int | float | bool | None = None
    sort_path: str | None = None
    descending: bool = False
    limit: int | None = None


@dataclass(frozen=True, slots=True)
class DatasetSelectionPlan:
    dataset_id: str
    dataset_version: int
    records: tuple[DatasetRecord, ...]
    rule: DatasetSelection

    @property
    def selected_count(self) -> int:
        return len(self.records)

    @property
    def invocation_count(self) -> int:
        return 1

    def input_record(self) -> Mapping[str, object]:
        return {"selection": {"values": [dict(item.value) for item in self.records]}}

    def snapshot(self) -> Mapping[str, object]:
        return {
            "sourceKind": "dataset",
            "datasetId": self.dataset_id,
            "datasetPath": f"/.datasets/{self.dataset_id}.json",
            "datasetVersion": self.dataset_version,
            "recordIds": [item.id for item in self.records],
            "records": [
                {
                    "id": item.id,
                    "position": item.position,
                    "sourceKey": item.source_key,
                    "value": dict(item.value),
                }
                for item in self.records
            ],
            "rule": {
                "filterPath": self.rule.filter_path,
                "equals": self.rule.equals,
                "sortPath": self.rule.sort_path,
                "descending": self.rule.descending,
                "limit": self.rule.limit,
            },
            "selectedCount": self.selected_count,
            "invocationCount": self.invocation_count,
        }


class TransformNotFound(Exception):
    """The Transform Definition is unavailable in this Project."""


class TransformValidationError(Exception):
    """The Transform Definition does not meet its declared contract."""


class TransformExecutionError(Exception):
    """The isolated Transform runner could not produce a valid output."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class TransformStore(Protocol):
    async def create(self, definition: TransformDefinition) -> TransformDefinition: ...
    async def load(self, project_id: str, definition_id: str) -> TransformDefinition | None: ...
    async def list(self, project_id: str) -> Sequence[TransformDefinition]: ...
    async def replace(self, definition: TransformDefinition) -> bool: ...
    async def delete(self, project_id: str, definition_id: str) -> bool: ...


class TransformRunner(Protocol):
    async def identity(self) -> TransformRuntimeIdentity: ...

    async def execute(
        self, source: str, inputs: dict[str, object], parameters: dict[str, object]
    ) -> tuple[object, str]: ...


class TransformRunStore(Protocol):
    async def create(self, run: TransformRun) -> TransformRun: ...
    async def complete(self, run: TransformRun) -> TransformRun: ...
    async def load(self, project_id: str, run_id: str) -> TransformRun | None: ...
    async def list(
        self, project_id: str, definition_id: str | None, limit: int, offset: int
    ) -> TransformRunPage: ...
    async def reconcile_running(self, now: datetime) -> int: ...


class TransformModule:
    """Own validation and authorized lifecycle of Transform Definitions."""

    def __init__(
        self, projects: ProjectModule, store: TransformStore,
        runner: TransformRunner | None = None,
        run_store: TransformRunStore | None = None,
        datasets: DatasetModule | None = None,
        artifacts: ArtifactModule | None = None,
    ) -> None:
        self._projects = projects
        self._store = store
        self._runner = runner
        self._run_store = run_store
        self._datasets = datasets
        self._artifacts = artifacts

    async def define(
        self,
        access: ProjectAccess,
        project_id: str,
        name: str,
        source: str,
        input_selectors: Mapping[str, str],
        output_schema: Mapping[str, object],
    ) -> TransformDefinition:
        await self._authorize(access, project_id)
        clean_name, clean_source, selectors, schema = _validate_definition(
            name, source, input_selectors, output_schema
        )
        identity = await self._runner.identity() if self._runner else None
        now = datetime.now(UTC)
        return await self._store.create(
            TransformDefinition(
                str(uuid4()), project_id, clean_name, clean_source, selectors, schema,
                identity.runtime if identity else None,
                identity.package_hash if identity else None,
                hashlib.sha256(clean_source.encode()).hexdigest(), 1, now, now,
            )
        )

    async def load(
        self, access: ProjectAccess, project_id: str, definition_id: str
    ) -> TransformDefinition:
        await self._authorize(access, project_id)
        definition = await self._store.load(project_id, definition_id)
        if definition is None:
            raise TransformNotFound
        return definition

    async def list(
        self, access: ProjectAccess, project_id: str
    ) -> Sequence[TransformDefinition]:
        await self._authorize(access, project_id)
        return await self._store.list(project_id)

    async def revise(
        self,
        access: ProjectAccess,
        project_id: str,
        definition_id: str,
        name: str,
        source: str,
        input_selectors: Mapping[str, str],
        output_schema: Mapping[str, object],
    ) -> TransformDefinition:
        current = await self.load(access, project_id, definition_id)
        clean_name, clean_source, selectors, schema = _validate_definition(
            name, source, input_selectors, output_schema
        )
        identity = await self._runner.identity() if self._runner else None
        revised = replace(
            current,
            name=clean_name,
            source=clean_source,
            input_selectors=selectors,
            output_schema=schema,
            runtime=identity.runtime if identity else None,
            package_hash=identity.package_hash if identity else None,
            source_hash=hashlib.sha256(clean_source.encode()).hexdigest(),
            revision=current.revision + 1,
            updated_at=datetime.now(UTC),
        )
        if not await self._store.replace(revised):
            raise TransformNotFound
        return revised

    async def delete(self, access: ProjectAccess, project_id: str, definition_id: str) -> None:
        await self._authorize(access, project_id)
        if not await self._store.delete(project_id, definition_id):
            raise TransformNotFound

    async def preview(
        self, access: ProjectAccess, project_id: str, definition_id: str,
        record: Mapping[str, object], parameters: Mapping[str, object],
    ) -> TransformPreview:
        definition = await self.load(access, project_id, definition_id)
        if self._runner is None:
            raise TransformExecutionError("runner_unavailable")
        inputs, parameter_values = _inputs(definition, record, parameters)
        output, runtime = await self._runner.execute(
            definition.source, inputs, parameter_values
        )
        if not Draft202012Validator(definition.output_schema).is_valid(output):
            raise TransformValidationError("Transform output does not match its output schema.")
        return TransformPreview(output, runtime, definition.source_hash)

    async def batch_snapshot(
        self, access: ProjectAccess, project_id: str, definition_id: str
    ) -> Mapping[str, object]:
        """Capture the reviewed Transform contract for a durable per-record Batch Run."""
        definition = await self.load(access, project_id, definition_id)
        if self._runner is None:
            raise TransformExecutionError("runner_unavailable")
        identity = await self._runner.identity()
        if (
            definition.runtime != identity.runtime
            or definition.package_hash != identity.package_hash
        ):
            raise TransformExecutionError("runtime_mismatch")
        return {
            "transformDefinitionId": definition.id,
            "name": definition.name,
            "revision": definition.revision,
            "source": definition.source,
            "sourceHash": definition.source_hash,
            "inputSelectors": dict(definition.input_selectors),
            "outputSchema": dict(definition.output_schema),
            "runtime": identity.runtime,
            "packageHash": identity.package_hash,
            "limits": dict(identity.limits),
        }

    async def execute_batch_record(
        self, access: ProjectAccess, project_id: str,
        snapshot: Mapping[str, object], record: Mapping[str, object],
    ) -> Mapping[str, object]:
        """Run one captured record without creating a second Transform Run."""
        await self._authorize(access, project_id)
        if self._runner is None:
            raise TransformExecutionError("runner_unavailable")
        identity = await self._runner.identity()
        if (
            snapshot["runtime"] != identity.runtime
            or snapshot["packageHash"] != identity.package_hash
        ):
            raise TransformExecutionError("runtime_mismatch")
        selectors = cast(Mapping[str, str], snapshot["inputSelectors"])
        inputs = {name: _select(record, pointer) for name, pointer in selectors.items()}
        if len(_canonical(inputs)) > 64_000:
            raise TransformValidationError("Transform inputs exceed 64000 bytes.")
        output, runtime = await self._runner.execute(
            str(snapshot["source"]), inputs, {}
        )
        if runtime != identity.runtime:
            raise TransformExecutionError("runtime_mismatch")
        schema = cast(Mapping[str, object], snapshot["outputSchema"])
        if not Draft202012Validator(schema).is_valid(output):
            raise TransformValidationError("Transform output does not match its output schema.")
        if not isinstance(output, dict) or not all(isinstance(key, str) for key in output):
            raise TransformValidationError("Per-record Transform output must be a JSON object.")
        if len(_canonical(output)) > 128_000:
            raise TransformExecutionError("output_limit")
        return output

    async def start_run(
        self, access: ProjectAccess, project_id: str, definition_id: str,
        record: Mapping[str, object], parameters: Mapping[str, object],
        initiation: TransformInitiation | None = None,
    ) -> TransformRun:
        return await self._start_run(
            access, project_id, definition_id, record, parameters, initiation,
            selection_snapshot=None, expected_revision=None,
        )

    async def plan_dataset_selection(
        self,
        access: ProjectAccess,
        project_id: str,
        definition_id: str,
        selection: DatasetSelection,
        parameters: Mapping[str, object] | None = None,
    ) -> DatasetSelectionPlan:
        definition = await self.load(access, project_id, definition_id)
        if definition.revision != selection.expected_definition_revision:
            raise TransformValidationError(
                "Transform Definition revision changed; review it again."
            )
        if self._datasets is None:
            raise TransformExecutionError("dataset_selection_unavailable")
        try:
            dataset = await self._datasets.load_dataset(access, project_id, selection.dataset_id)
        except DatasetNotFound as error:
            raise TransformValidationError("Selected Dataset is unavailable.") from error
        if dataset.version != selection.expected_version:
            raise TransformValidationError("Dataset version changed; review the selection again.")
        records = _select_dataset_records(dataset.records, selection)
        plan = DatasetSelectionPlan(dataset.id, dataset.version, records, selection)
        _inputs(definition, plan.input_record(), parameters or {})
        return plan

    async def start_selected_run(
        self,
        access: ProjectAccess,
        project_id: str,
        definition_id: str,
        selection: DatasetSelection,
        parameters: Mapping[str, object],
        initiation: TransformInitiation | None = None,
    ) -> TransformRun:
        plan = await self.plan_dataset_selection(
            access, project_id, definition_id, selection, parameters
        )
        if not plan.records:
            raise TransformValidationError("Selection has no Records to run.")
        return await self._start_run(
            access, project_id, definition_id, plan.input_record(), parameters,
            initiation, selection_snapshot=plan.snapshot(),
            expected_revision=selection.expected_definition_revision,
        )

    async def _start_run(
        self,
        access: ProjectAccess,
        project_id: str,
        definition_id: str,
        record: Mapping[str, object],
        parameters: Mapping[str, object],
        initiation: TransformInitiation | None,
        *,
        selection_snapshot: Mapping[str, object] | None,
        expected_revision: int | None,
    ) -> TransformRun:
        definition = await self.load(access, project_id, definition_id)
        if expected_revision is not None and definition.revision != expected_revision:
            raise TransformValidationError(
                "Transform Definition revision changed; review it again."
            )
        if self._run_store is None:
            raise TransformExecutionError("run_store_unavailable")
        if self._runner is None:
            raise TransformExecutionError("runner_unavailable")
        identity = await self._runner.identity()
        if definition.runtime and (
            definition.runtime != identity.runtime or
            definition.package_hash != identity.package_hash
        ):
            raise TransformExecutionError("runtime_mismatch")
        inputs, parameter_values = _inputs(definition, record, parameters)
        input_bytes = _canonical({"inputs": inputs, "parameters": parameter_values})
        now = datetime.now(UTC)
        context = initiation or TransformInitiation("directUser", "notRequired")
        run = await self._run_store.create(TransformRun(
            id=str(uuid4()), project_id=project_id, definition_id=definition_id,
            status="running", definition_snapshot={
                "name": definition.name, "source": definition.source,
                "input_selectors": dict(definition.input_selectors),
                "output_schema": dict(definition.output_schema),
                "revision": definition.revision,
                "runtime": identity.runtime,
                "package_hash": identity.package_hash,
                **({"selection": dict(selection_snapshot)} if selection_snapshot else {}),
            },
            inputs=inputs, parameters=parameter_values,
            input_hash=hashlib.sha256(input_bytes).hexdigest(),
            source_hash=definition.source_hash, runtime=identity.runtime,
            package_hash=identity.package_hash, output=None,
            output_manifest={}, error=None, initiator_subject=access.subject,
            initiation={
                "kind": context.kind, "approval": context.approval,
                "threadId": context.thread_id, "agentRunId": context.agent_run_id,
            },
            limits=dict(identity.limits),
            created_at=now, completed_at=None,
        ))
        try:
            output, runtime = await self._runner.execute(
                definition.source, inputs, parameter_values
            )
            if runtime != identity.runtime:
                raise TransformExecutionError("runtime_mismatch")
            if not Draft202012Validator(definition.output_schema).is_valid(output):
                raise TransformExecutionError("output_schema")
            output_bytes = _canonical(output)
            if len(output_bytes) > 128_000:
                raise TransformExecutionError("output_limit")
            completed = replace(
                run, status="succeeded", output=output,
                output_manifest={
                    "kind": "json", "bytes": len(output_bytes),
                    "sha256": hashlib.sha256(output_bytes).hexdigest(),
                },
                completed_at=datetime.now(UTC),
            )
        except TransformExecutionError as error:
            completed = replace(
                run, status="failed", error=error.code, completed_at=datetime.now(UTC)
            )
        return await self._run_store.complete(completed)

    async def load_run(
        self, access: ProjectAccess, project_id: str, run_id: str
    ) -> TransformRun:
        await self._authorize(access, project_id)
        if self._run_store is None:
            raise TransformExecutionError("run_store_unavailable")
        run = await self._run_store.load(project_id, run_id)
        if run is None:
            raise TransformNotFound
        return run

    async def list_runs(
        self, access: ProjectAccess, project_id: str,
        definition_id: str | None = None, limit: int = 20, offset: int = 0,
    ) -> TransformRunPage:
        await self._authorize(access, project_id)
        if self._run_store is None:
            raise TransformExecutionError("run_store_unavailable")
        if not 1 <= limit <= 100 or offset < 0:
            raise TransformValidationError("Run page limit or offset is invalid.")
        return await self._run_store.list(project_id, definition_id, limit, offset)

    async def save_run_as_dataset(
        self, access: ProjectAccess, project_id: str, run_id: str, name: str
    ) -> Dataset:
        run = await self.load_run(access, project_id, run_id)
        if self._datasets is None:
            raise TransformExecutionError("dataset_save_unavailable")
        if run.status != "succeeded":
            raise TransformValidationError("Only successful Transform Run output can be saved.")
        output = run.output
        values = [output] if isinstance(output, dict) else output
        if not isinstance(values, list) or not values or any(
            not isinstance(value, dict) or not all(isinstance(key, str) for key in value)
            for value in values
        ):
            raise TransformValidationError(
                "Dataset save requires an object or a nonempty array of objects."
            )
        return await self._datasets.create_dataset(
            access, project_id, name,
            [
                DatasetRecordInput(
                    value, source_key=f"transform-run:{run.id}:{index}"
                )
                for index, value in enumerate(values)
            ],
        )

    async def save_run_as_artifact(
        self, access: ArtifactMutationAccess | ArtifactUserActionAccess,
        project_id: str, run_id: str, title: str,
    ) -> ArtifactDocument:
        run = await self.load_run(ProjectAccess(subject=access.subject), project_id, run_id)
        if self._artifacts is None:
            raise TransformExecutionError("artifact_save_unavailable")
        if run.status != "succeeded":
            raise TransformValidationError("Only successful Transform Run output can be saved.")
        clean_title = title.strip()
        if not clean_title or len(clean_title) > 240:
            raise TransformValidationError("Artifact title must contain 1 to 240 characters.")
        return await self._artifacts.create(
            access, project_id,
            ArtifactDraft(
                type="agent-hub.transform-result", title=clean_title,
                plugin_id="agent-hub.transforms", plugin_version="1",
                schema_id="agent-hub.transform-result", schema_version="1.0",
                payload={
                    "transformRunId": run.id,
                    "inputs": dict(run.inputs),
                    "parameters": dict(run.parameters),
                    "output": run.output,
                    "inputHash": run.input_hash,
                    "sourceHash": run.source_hash,
                    "runtime": run.runtime,
                    "packageHash": run.package_hash,
                    "outputManifest": dict(run.output_manifest),
                    "initiation": dict(run.initiation),
                    "limits": dict(run.limits),
                },
                summary=f"Saved output from Transform Run {run.id}.",
            ),
        )

    async def recover(self) -> int:
        if self._run_store is None:
            return 0
        return await self._run_store.reconcile_running(datetime.now(UTC))

    async def _authorize(self, access: ProjectAccess, project_id: str) -> None:
        try:
            await self._projects.load(access, project_id)
        except ProjectNotFound as error:
            raise TransformNotFound from error


def _select(record: Mapping[str, object], pointer: str) -> object:
    value: object = record
    for raw in pointer[1:].split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict) and key in value:
            value = value[key]
        elif isinstance(value, list) and key.isdecimal() and int(key) < len(value):
            value = value[int(key)]
        else:
            raise TransformValidationError("Transform input selector did not match the record.")
    return value


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _select_dataset_records(
    records: Sequence[DatasetRecord], selection: DatasetSelection
) -> tuple[DatasetRecord, ...]:
    if selection.expected_version < 1 or selection.expected_definition_revision < 1:
        raise TransformValidationError("Selection versions must be positive.")
    if selection.limit is not None and not 1 <= selection.limit <= 100:
        raise TransformValidationError("Selection limit must be between 1 and 100.")
    for pointer in (selection.filter_path, selection.sort_path):
        if pointer is not None and (
            not pointer.startswith("/") or re.search(r"~(?![01])", pointer) is not None
        ):
            raise TransformValidationError("Selection paths must be JSON Pointers.")
    if selection.filter_path is None and selection.equals is not None:
        raise TransformValidationError("A filter value requires a filter path.")
    if selection.filter_path is not None:
        if selection.equals is not None and not isinstance(
            selection.equals, (str, int, float, bool)
        ):
            raise TransformValidationError("Filter equality must be a JSON scalar.")
        try:
            _canonical(selection.equals)
        except (TypeError, ValueError) as error:
            raise TransformValidationError("Filter equality must be a JSON scalar.") from error
    selected = list(records)
    if selection.filter_path is not None:
        matching: list[DatasetRecord] = []
        for record in selected:
            value = _select(record.value, selection.filter_path)
            if not isinstance(value, (str, int, float, bool, type(None))):
                raise TransformValidationError("Filter path must select a scalar value.")
            if _same_scalar(value, selection.equals):
                matching.append(record)
        selected = matching
    if selection.sort_path is not None:
        keys = [_select(record.value, selection.sort_path) for record in selected]
        if keys and (
            any(
                isinstance(value, bool) or not isinstance(value, (str, int, float))
                for value in keys
            )
            or any(isinstance(value, str) != isinstance(keys[0], str) for value in keys)
        ):
            raise TransformValidationError("Sort path must select comparable strings or numbers.")
        selected.sort(
            key=lambda record: cast(
                str | int | float, _select(record.value, selection.sort_path or "")
            ),
            reverse=selection.descending,
        )
    if selection.limit is not None:
        selected = selected[: selection.limit]
    if len(selected) > 100:
        raise TransformValidationError("Selection exceeds 100 Records; add an explicit limit.")
    return tuple(selected)


def _same_scalar(left: object, right: object) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    return type(left) is type(right) and left == right


def _inputs(
    definition: TransformDefinition, record: Mapping[str, object],
    parameters: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    inputs = {
        name: _select(record, pointer)
        for name, pointer in definition.input_selectors.items()
    }
    parameter_values = dict(parameters)
    try:
        if len(_canonical({"inputs": inputs, "parameters": parameter_values})) > 64_000:
            raise TransformValidationError("Transform inputs exceed 64000 bytes.")
    except (TypeError, ValueError) as error:
        raise TransformValidationError("Transform inputs must be JSON values.") from error
    return inputs, parameter_values


class MemoryTransformRunStore:
    def __init__(self) -> None:
        self._runs: dict[tuple[str, str], TransformRun] = {}

    async def create(self, run: TransformRun) -> TransformRun:
        self._runs[(run.project_id, run.id)] = run
        return run

    async def complete(self, run: TransformRun) -> TransformRun:
        key = (run.project_id, run.id)
        if self._runs[key].status != "running":
            raise TransformExecutionError("run_already_completed")
        self._runs[key] = run
        return run

    async def load(self, project_id: str, run_id: str) -> TransformRun | None:
        return self._runs.get((project_id, run_id))

    async def list(
        self, project_id: str, definition_id: str | None, limit: int, offset: int
    ) -> TransformRunPage:
        matching = sorted(
            (
                run for (stored_project, _), run in self._runs.items()
                if stored_project == project_id and (
                    definition_id is None or run.definition_id == definition_id
                )
            ),
            key=lambda run: (run.created_at, run.id),
            reverse=True,
        )
        items = tuple(matching[offset:offset + limit])
        next_offset = offset + limit if len(matching) > offset + limit else None
        return TransformRunPage(items, next_offset)

    async def reconcile_running(self, now: datetime) -> int:
        active = [key for key, run in self._runs.items() if run.status == "running"]
        for key in active:
            self._runs[key] = replace(
                self._runs[key], status="failed", error="interrupted", completed_at=now
            )
        return len(active)


def _validate_definition(
    name: str, source: str, input_selectors: Mapping[str, str],
    output_schema: Mapping[str, object],
) -> tuple[str, str, dict[str, str], dict[str, object]]:
    clean_name = name.strip()
    if not clean_name or len(clean_name) > 160:
        raise TransformValidationError("Transform name must contain 1 to 160 characters.")
    if not source.strip() or len(source.encode()) > 64_000:
        raise TransformValidationError("Transform source must contain 1 to 64000 bytes.")
    try:
        ast.parse(source)
    except SyntaxError as error:
        raise TransformValidationError("Transform source is not valid Python.") from error
    selectors = dict(input_selectors)
    if not selectors or len(selectors) > 32 or any(
        not key.isidentifier() or not isinstance(pointer, str) or not pointer.startswith("/")
        for key, pointer in selectors.items()
    ):
        raise TransformValidationError("Each input selector needs a name and JSON pointer.")
    schema = dict(output_schema)
    try:
        if len(json.dumps(schema, allow_nan=False).encode()) > 16_000:
            raise TransformValidationError("Transform output schema exceeds 16000 bytes.")
        Draft202012Validator.check_schema(schema)
    except (SchemaError, TypeError, ValueError) as error:
        raise TransformValidationError("Transform output schema is invalid.") from error
    return clean_name, source, selectors, schema


class MemoryTransformStore:
    def __init__(self) -> None:
        self._definitions: dict[tuple[str, str], TransformDefinition] = {}

    async def create(self, definition: TransformDefinition) -> TransformDefinition:
        self._definitions[(definition.project_id, definition.id)] = definition
        return definition

    async def load(self, project_id: str, definition_id: str) -> TransformDefinition | None:
        return self._definitions.get((project_id, definition_id))

    async def list(self, project_id: str) -> Sequence[TransformDefinition]:
        return tuple(
            item for (stored_project, _), item in self._definitions.items()
            if stored_project == project_id
        )

    async def replace(self, definition: TransformDefinition) -> bool:
        key = (definition.project_id, definition.id)
        if key not in self._definitions:
            return False
        self._definitions[key] = definition
        return True

    async def delete(self, project_id: str, definition_id: str) -> bool:
        return self._definitions.pop((project_id, definition_id), None) is not None


class PostgresTransformStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def _connect(self) -> AsyncConnection[dict[str, object]]:
        return await AsyncConnection.connect(
            str(self._settings.database_url),
            connect_timeout=self._settings.database_connect_timeout_seconds,
            row_factory=dict_row,
        )

    async def create(self, definition: TransformDefinition) -> TransformDefinition:
        connection = await self._connect()
        async with connection:
            await connection.execute(
                """INSERT INTO transform_definitions
                (project_id,transform_definition_id,name,source,input_selectors,output_schema,
                runtime,package_hash,source_hash,revision,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                _values(definition),
            )
        return definition

    async def load(self, project_id: str, definition_id: str) -> TransformDefinition | None:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """SELECT * FROM transform_definitions
                WHERE project_id=%s AND transform_definition_id=%s""",
                (project_id, definition_id),
            )
            row = await cursor.fetchone()
        return _from_row(row) if row else None

    async def list(self, project_id: str) -> Sequence[TransformDefinition]:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """SELECT * FROM transform_definitions WHERE project_id=%s
                ORDER BY created_at, transform_definition_id""",
                (project_id,),
            )
            rows = await cursor.fetchall()
        return tuple(_from_row(row) for row in rows)

    async def replace(self, definition: TransformDefinition) -> bool:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """UPDATE transform_definitions SET name=%s,source=%s,input_selectors=%s,
                output_schema=%s,runtime=%s,package_hash=%s,source_hash=%s,revision=%s,updated_at=%s
                WHERE project_id=%s AND transform_definition_id=%s AND revision=%s""",
                (
                    definition.name, definition.source, json.dumps(definition.input_selectors),
                    json.dumps(definition.output_schema), definition.runtime,
                    definition.package_hash,
                    definition.source_hash, definition.revision, definition.updated_at,
                    definition.project_id, definition.id, definition.revision - 1,
                ),
            )
            return cursor.rowcount == 1

    async def delete(self, project_id: str, definition_id: str) -> bool:
        connection = await self._connect()
        async with connection:
            cursor = await connection.execute(
                """DELETE FROM transform_definitions
                WHERE project_id=%s AND transform_definition_id=%s""",
                (project_id, definition_id),
            )
            return cursor.rowcount == 1


def _values(definition: TransformDefinition) -> tuple[object, ...]:
    return (
        definition.project_id, definition.id, definition.name, definition.source,
        json.dumps(definition.input_selectors), json.dumps(definition.output_schema),
        definition.runtime, definition.package_hash, definition.source_hash, definition.revision,
        definition.created_at, definition.updated_at,
    )


def _from_row(row: Mapping[str, object]) -> TransformDefinition:
    selectors = row["input_selectors"]
    schema = row["output_schema"]
    return TransformDefinition(
        id=str(row["transform_definition_id"]),
        project_id=str(row["project_id"]),
        name=str(row["name"]),
        source=str(row["source"]),
        input_selectors=(
            json.loads(selectors) if isinstance(selectors, str)
            else dict(cast(Mapping[str, str], selectors))
        ),
        output_schema=(
            json.loads(schema) if isinstance(schema, str)
            else dict(cast(Mapping[str, object], schema))
        ),
        runtime=str(row["runtime"]) if row["runtime"] is not None else None,
        package_hash=str(row["package_hash"]) if row["package_hash"] is not None else None,
        source_hash=str(row["source_hash"]),
        revision=cast(int, row["revision"]),
        created_at=cast(datetime, row["created_at"]),
        updated_at=cast(datetime, row["updated_at"]),
    )


def create_postgres_transform_module(
    settings: Settings, projects: ProjectModule,
    runner: TransformRunner | None = None,
    datasets: DatasetModule | None = None,
    artifacts: ArtifactModule | None = None,
) -> TransformModule:
    from agent_hub_api.modules.transforms._run_store import PostgresTransformRunStore
    from agent_hub_api.modules.transforms._runner import DenoTransformRunner

    resolved_runner = runner or (
        DenoTransformRunner(settings.transform_runner_url)
        if settings.transform_runner_url else None
    )
    return TransformModule(
        projects, PostgresTransformStore(settings), resolved_runner,
        PostgresTransformRunStore(settings), datasets, artifacts,
    )
