from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from agent_hub_api.modules.datasets._application import (
    BatchDefinition,
    Dataset,
    DatasetModule,
    DatasetNotFound,
    DatasetRecord,
    DatasetRecordInput,
    DatasetValidationError,
)
from agent_hub_api.modules.identity import (
    IdentityEvidence,
    IdentityModule,
    IdentityUnavailable,
    RequestContext,
)
from agent_hub_api.modules.plugin_gateway import (
    PluginNotAvailable,
    PluginNotEnabled,
    PluginToolNotAllowed,
)
from agent_hub_api.modules.projects import ProjectAccess


class _Model(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class DatasetRecordRequest(_Model):
    value: dict[str, object]
    source_key: str | None = None
    id: str | None = None


class DatasetRequest(_Model):
    name: str
    records: list[DatasetRecordRequest] = Field(default_factory=list)


class DatasetRecordResponse(_Model):
    id: str
    position: int
    value: dict[str, object]
    source_key: str | None


class DatasetResponse(_Model):
    id: str
    name: str
    records: list[DatasetRecordResponse]


class BatchDefinitionRequest(_Model):
    dataset_id: str
    name: str
    plugin_id: str | None = None
    tool_name: str | None = None
    transform_definition_id: str | None = None
    argument_mappings: dict[str, str] = Field(default_factory=dict)


class BatchDefinitionResponse(_Model):
    id: str
    dataset_id: str
    dataset_available: bool
    name: str
    plugin_id: str | None
    tool_name: str | None
    transform_definition_id: str | None
    argument_mappings: dict[str, str]


class TransformBatchCreator(Protocol):
    async def define_transform_batch(
        self, access: ProjectAccess, project_id: str, dataset_id: str,
        name: str, transform_definition_id: str,
    ) -> BatchDefinition: ...


def _record_response(record: DatasetRecord) -> DatasetRecordResponse:
    return DatasetRecordResponse(
        id=record.id,
        position=record.position,
        value=dict(record.value),
        source_key=record.source_key,
    )


def _dataset_response(dataset: Dataset) -> DatasetResponse:
    return DatasetResponse(
        id=dataset.id,
        name=dataset.name,
        records=[_record_response(record) for record in dataset.records],
    )


async def _definition_response(
    datasets: DatasetModule, access: ProjectAccess, definition: BatchDefinition
) -> BatchDefinitionResponse:
    try:
        await datasets.load_dataset(access, definition.project_id, definition.dataset_id)
    except DatasetNotFound:
        available = False
    else:
        available = True
    return BatchDefinitionResponse(
        id=definition.id,
        dataset_id=definition.dataset_id,
        dataset_available=available,
        name=definition.name,
        plugin_id=definition.plugin_id,
        tool_name=definition.tool_name,
        transform_definition_id=definition.transform_definition_id,
        argument_mappings=dict(definition.argument_mappings),
    )


def create_dataset_router(
    identity: IdentityModule, datasets: DatasetModule,
    transform_batches: TransformBatchCreator | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/projects/{project_id}", tags=["datasets"])

    async def context(request: Request) -> RequestContext:
        try:
            return identity.resolve(IdentityEvidence(headers=request.headers))
        except IdentityUnavailable as error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authenticated platform identity is required",
            ) from error

    Context = Annotated[RequestContext, Depends(context)]

    def access(context: RequestContext) -> ProjectAccess:
        return ProjectAccess(subject=context.subject)

    def failure(error: Exception) -> HTTPException:
        if isinstance(error, DatasetNotFound):
            return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
        if isinstance(error, (PluginNotAvailable, PluginNotEnabled, PluginToolNotAllowed)):
            return HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Tool unavailable"
            )
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error))

    @router.get("/datasets", response_model=list[DatasetResponse])
    async def list_datasets(project_id: str, request_context: Context) -> list[DatasetResponse]:
        try:
            items = await datasets.list_datasets(access(request_context), project_id)
        except DatasetNotFound as error:
            raise failure(error) from error
        return [_dataset_response(item) for item in items]

    @router.post("/datasets", response_model=DatasetResponse, status_code=status.HTTP_201_CREATED)
    async def create_dataset(
        project_id: str, body: DatasetRequest, request_context: Context
    ) -> DatasetResponse:
        try:
            dataset = await datasets.create_dataset(
                access(request_context),
                project_id,
                body.name,
                [DatasetRecordInput(item.value, item.source_key, item.id) for item in body.records],
            )
        except (DatasetNotFound, DatasetValidationError) as error:
            raise failure(error) from error
        return _dataset_response(dataset)

    @router.get("/datasets/{dataset_id}", response_model=DatasetResponse)
    async def load_dataset(
        project_id: str, dataset_id: str, request_context: Context
    ) -> DatasetResponse:
        try:
            return _dataset_response(
                await datasets.load_dataset(access(request_context), project_id, dataset_id)
            )
        except DatasetNotFound as error:
            raise failure(error) from error

    @router.put("/datasets/{dataset_id}", response_model=DatasetResponse)
    async def update_dataset(
        project_id: str, dataset_id: str, body: DatasetRequest, request_context: Context
    ) -> DatasetResponse:
        try:
            dataset = await datasets.update_dataset(
                access(request_context),
                project_id,
                dataset_id,
                body.name,
                [DatasetRecordInput(item.value, item.source_key, item.id) for item in body.records],
            )
        except (DatasetNotFound, DatasetValidationError) as error:
            raise failure(error) from error
        return _dataset_response(dataset)

    @router.delete("/datasets/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_dataset(project_id: str, dataset_id: str, request_context: Context) -> None:
        try:
            await datasets.delete_dataset(access(request_context), project_id, dataset_id)
        except DatasetNotFound as error:
            raise failure(error) from error

    @router.get("/batch-definitions", response_model=list[BatchDefinitionResponse])
    async def list_definitions(
        project_id: str, request_context: Context
    ) -> list[BatchDefinitionResponse]:
        request_access = access(request_context)
        try:
            definitions = await datasets.list_definitions(request_access, project_id)
        except DatasetNotFound as error:
            raise failure(error) from error
        return [
            await _definition_response(datasets, request_access, definition)
            for definition in definitions
        ]

    @router.post(
        "/batch-definitions",
        response_model=BatchDefinitionResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_definition(
        project_id: str, body: BatchDefinitionRequest, request_context: Context
    ) -> BatchDefinitionResponse:
        request_access = access(request_context)
        try:
            if body.transform_definition_id is not None:
                if (
                    body.plugin_id is not None
                    or body.tool_name is not None
                    or body.argument_mappings
                ):
                    raise DatasetValidationError("Choose one Batch Definition target.")
                if transform_batches is None:
                    raise DatasetValidationError("Transform execution is unavailable.")
                definition = await transform_batches.define_transform_batch(
                    request_access, project_id, body.dataset_id, body.name,
                    body.transform_definition_id,
                )
            else:
                if body.plugin_id is None or body.tool_name is None:
                    raise DatasetValidationError("An MCP tool target is required.")
                definition = await datasets.create_definition(
                    request_access, project_id, body.dataset_id, body.name,
                    body.plugin_id, body.tool_name, body.argument_mappings,
                )
        except (
            DatasetNotFound,
            DatasetValidationError,
            PluginNotAvailable,
            PluginNotEnabled,
            PluginToolNotAllowed,
        ) as error:
            raise failure(error) from error
        return await _definition_response(datasets, request_access, definition)

    @router.put("/batch-definitions/{definition_id}", response_model=BatchDefinitionResponse)
    async def update_definition(
        project_id: str,
        definition_id: str,
        body: BatchDefinitionRequest,
        request_context: Context,
    ) -> BatchDefinitionResponse:
        request_access = access(request_context)
        try:
            if body.transform_definition_id is not None:
                raise DatasetValidationError("Create a new Transform Batch Definition instead.")
            if body.plugin_id is None or body.tool_name is None:
                raise DatasetValidationError("An MCP tool target is required.")
            definition = await datasets.update_definition(
                request_access,
                project_id,
                definition_id,
                body.dataset_id,
                body.name,
                body.plugin_id,
                body.tool_name,
                body.argument_mappings,
            )
        except (
            DatasetNotFound,
            DatasetValidationError,
            PluginNotAvailable,
            PluginNotEnabled,
            PluginToolNotAllowed,
        ) as error:
            raise failure(error) from error
        return await _definition_response(datasets, request_access, definition)

    @router.delete("/batch-definitions/{definition_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_definition(
        project_id: str, definition_id: str, request_context: Context
    ) -> None:
        try:
            await datasets.delete_definition(access(request_context), project_id, definition_id)
        except DatasetNotFound as error:
            raise failure(error) from error

    return router
