"""Coordinate retained operation values with Transform execution."""

import json
from collections.abc import Mapping
from dataclasses import dataclass

from agent_hub_api.modules.artifacts import ArtifactAccess, ArtifactModule, ArtifactNotFound
from agent_hub_api.modules.batch_execution import (
    BatchExecutionModule,
    BatchRunNotFound,
    BatchRunStatus,
)
from agent_hub_api.modules.input_selection import (
    SelectionRule,
    SelectionValidationError,
    SelectionValue,
    project_value,
    select_values,
)
from agent_hub_api.modules.projects import ProjectAccess
from agent_hub_api.modules.transforms import (
    TransformInitiation,
    TransformModule,
    TransformRun,
)

MAX_SOURCE_ROWS = 10_000


class TransformInputValidationError(ValueError):
    """A source Run cannot provide the requested bounded Transform input."""


@dataclass(frozen=True, slots=True)
class ResultSetSelection:
    source_run_id: str
    output_path: str
    expected_definition_revision: int
    filter_path: str | None = None
    equals: str | int | float | bool | None = None
    sort_path: str | None = None
    descending: bool = False
    limit: int | None = None

    def rule(self) -> SelectionRule:
        return SelectionRule(
            self.filter_path, self.equals, self.sort_path, self.descending, self.limit
        )


@dataclass(frozen=True, slots=True)
class ResultSetSelectionPlan:
    source_run_id: str
    source_definition_id: str
    source_status: BatchRunStatus
    source_record_count: int
    failed_count: int
    output_path: str
    selected: tuple[SelectionValue, ...]
    selected_inputs: tuple[Mapping[str, object], ...]
    rule: SelectionRule

    @property
    def selected_count(self) -> int:
        return len(self.selected)

    @property
    def invocation_count(self) -> int:
        return 1

    def input_record(self) -> Mapping[str, object]:
        rows = self._rows()
        return {
            "selection": {
                "values": [row["value"] for row in rows],
                "rows": rows,
            }
        }

    def _rows(self) -> list[dict[str, object]]:
        return [
            {
                "resultRecordId": f"{self.source_run_id}:{item.id}",
                "datasetRecordId": item.id,
                "sourceKey": item.source_key,
                "position": item.position,
                "input": _json_copy(inputs),
                "value": _json_copy(item.value),
            }
            for item, inputs in zip(self.selected, self.selected_inputs, strict=True)
        ]

    def snapshot(self) -> Mapping[str, object]:
        return {
            "sourceKind": "resultSet",
            "batchRunId": self.source_run_id,
            "sourceDefinitionId": self.source_definition_id,
            "sourceStatus": self.source_status.value,
            "sourceRecordCount": self.source_record_count,
            "failedCount": self.failed_count,
            "outputPath": self.output_path,
            "selectedRecords": self._rows(),
            "rule": dict(self.rule.snapshot()),
            "selectedCount": self.selected_count,
        }


@dataclass(frozen=True, slots=True)
class ArtifactSelection:
    artifact_id: str
    expected_artifact_version: int
    output_path: str
    expected_definition_revision: int
    filter_path: str | None = None
    equals: str | int | float | bool | None = None
    sort_path: str | None = None
    descending: bool = False
    limit: int | None = None

    def rule(self) -> SelectionRule:
        return SelectionRule(
            self.filter_path, self.equals, self.sort_path, self.descending, self.limit
        )


@dataclass(frozen=True, slots=True)
class ArtifactSelectionPlan:
    artifact_id: str
    artifact_version: int
    plugin_id: str
    tool_name: str
    output_path: str
    selected: tuple[SelectionValue, ...]
    rule: SelectionRule

    @property
    def selected_count(self) -> int:
        return len(self.selected)

    @property
    def invocation_count(self) -> int:
        return 1

    def input_record(self) -> Mapping[str, object]:
        return {"selection": {"values": [_json_copy(item.value) for item in self.selected]}}

    def snapshot(self) -> Mapping[str, object]:
        return {
            "sourceKind": "mcpToolResult",
            "artifactId": self.artifact_id,
            "artifactVersion": self.artifact_version,
            "pluginId": self.plugin_id,
            "toolName": self.tool_name,
            "outputPath": self.output_path,
            "selectedValues": [
                {"position": item.position, "value": _json_copy(item.value)}
                for item in self.selected
            ],
            "rule": dict(self.rule.snapshot()),
            "selectedCount": self.selected_count,
        }


class TransformInputModule:
    """Plan and execute one Transform from captured cross-Module values."""

    def __init__(
        self, batches: BatchExecutionModule, transforms: TransformModule, artifacts: ArtifactModule
    ) -> None:
        self._batches = batches
        self._transforms = transforms
        self._artifacts = artifacts

    async def plan_artifact_selection(
        self,
        access: ProjectAccess,
        project_id: str,
        definition_id: str,
        selection: ArtifactSelection,
        parameters: Mapping[str, object] | None = None,
    ) -> ArtifactSelectionPlan:
        try:
            source = await self._artifacts.load(
                ArtifactAccess(access.subject), project_id, selection.artifact_id
            )
        except ArtifactNotFound as error:
            raise TransformInputValidationError("Selected MCP output is unavailable.") from error
        if source.artifact.schema_.id != "agent-hub.tool-result-snapshot":
            raise TransformInputValidationError("Artifact is not a retained MCP tool result.")
        if source.artifact.document_version != selection.expected_artifact_version:
            raise TransformInputValidationError("MCP output changed; review the selection again.")
        output = source.payload.get("output")
        if not isinstance(output, dict):
            raise TransformInputValidationError("MCP output has no structured values.")
        try:
            projected = project_value(output, selection.output_path)
        except SelectionValidationError as error:
            raise TransformInputValidationError(str(error)) from error
        values = projected if isinstance(projected, list) else [projected]
        if len(values) > MAX_SOURCE_ROWS:
            raise TransformInputValidationError("MCP output exceeds the source inspection limit.")
        try:
            selected = select_values(
                tuple(
                    SelectionValue(str(index), index, value) for index, value in enumerate(values)
                ),
                selection.rule(),
            )
        except SelectionValidationError as error:
            raise TransformInputValidationError(str(error)) from error
        plan = ArtifactSelectionPlan(
            selection.artifact_id,
            source.artifact.document_version,
            source.artifact.plugin.id,
            source.artifact.type.removeprefix(f"{source.artifact.plugin.id}."),
            selection.output_path,
            selected,
            selection.rule(),
        )
        await self._transforms.validate_captured_input(
            access,
            project_id,
            definition_id,
            plan.input_record(),
            parameters or {},
            expected_revision=selection.expected_definition_revision,
        )
        return plan

    async def start_artifact_run(
        self,
        access: ProjectAccess,
        project_id: str,
        definition_id: str,
        selection: ArtifactSelection,
        parameters: Mapping[str, object],
        initiation: TransformInitiation | None = None,
    ) -> TransformRun:
        plan = await self.plan_artifact_selection(
            access, project_id, definition_id, selection, parameters
        )
        if not plan.selected:
            raise TransformInputValidationError("Selection has no values to run.")
        return await self._transforms.start_captured_run(
            access,
            project_id,
            definition_id,
            plan.input_record(),
            parameters,
            plan.snapshot(),
            selection.expected_definition_revision,
            initiation,
        )

    async def plan_result_set_selection(
        self,
        access: ProjectAccess,
        project_id: str,
        definition_id: str,
        selection: ResultSetSelection,
        parameters: Mapping[str, object] | None = None,
    ) -> ResultSetSelectionPlan:
        try:
            source = await self._batches.load(access, project_id, selection.source_run_id)
        except BatchRunNotFound as error:
            raise TransformInputValidationError("Selected Result Set is unavailable.") from error
        if source.status not in {BatchRunStatus.succeeded, BatchRunStatus.partial}:
            raise TransformInputValidationError("Selected Result Set is not complete.")
        if len(source.records) > MAX_SOURCE_ROWS:
            raise TransformInputValidationError("Result Set exceeds the source inspection limit.")
        source_keys: dict[str, str | None] = {}
        dataset_records = source.definition_snapshot.get("datasetRecords")
        if isinstance(dataset_records, list):
            for record in dataset_records:
                if isinstance(record, dict) and isinstance(record.get("id"), str):
                    source_key = record.get("sourceKey")
                    source_keys[record["id"]] = source_key if isinstance(source_key, str) else None
        candidates: list[SelectionValue] = []
        for position, record in enumerate(source.records):
            if record.structured_output is None:
                continue
            try:
                value = project_value(record.structured_output, selection.output_path)
            except SelectionValidationError as error:
                raise TransformInputValidationError(str(error)) from error
            candidates.append(
                SelectionValue(
                    record.dataset_record_id,
                    position,
                    value,
                    source_keys.get(record.dataset_record_id),
                )
            )
        try:
            selected = select_values(candidates, selection.rule())
        except SelectionValidationError as error:
            raise TransformInputValidationError(str(error)) from error
        plan = ResultSetSelectionPlan(
            source.id,
            source.definition_id,
            source.status,
            len(source.records),
            sum(record.error is not None for record in source.records),
            selection.output_path,
            selected,
            tuple(source.records[item.position].input for item in selected),
            selection.rule(),
        )
        await self._transforms.validate_captured_input(
            access,
            project_id,
            definition_id,
            plan.input_record(),
            parameters or {},
            expected_revision=selection.expected_definition_revision,
        )
        return plan

    async def start_result_set_run(
        self,
        access: ProjectAccess,
        project_id: str,
        definition_id: str,
        selection: ResultSetSelection,
        parameters: Mapping[str, object],
        initiation: TransformInitiation | None = None,
    ) -> TransformRun:
        plan = await self.plan_result_set_selection(
            access, project_id, definition_id, selection, parameters
        )
        if not plan.selected:
            raise TransformInputValidationError("Selection has no values to run.")
        return await self._transforms.start_captured_run(
            access,
            project_id,
            definition_id,
            plan.input_record(),
            parameters,
            plan.snapshot(),
            selection.expected_definition_revision,
            initiation,
        )


def _json_copy(value: object) -> object:
    return json.loads(json.dumps(value, allow_nan=False))
