from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from agent_hub_api.modules.datasets._application import (
    Dataset,
    DatasetModule,
    DatasetNotFound,
    DatasetRecord,
    DatasetRecordInput,
    DatasetValidationError,
    DatasetVersionConflict,
)
from agent_hub_api.modules.identity import (
    IdentityEvidence,
    IdentityModule,
    IdentityUnavailable,
    RequestContext,
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
    expected_version: int | None = None


class DatasetRecordResponse(_Model):
    id: str
    position: int
    value: dict[str, object]
    source_key: str | None


class DatasetResponse(_Model):
    id: str
    name: str
    records: list[DatasetRecordResponse]
    version: int
    file_path: str


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
        version=dataset.version,
        file_path=f"/project/.datasets/{dataset.id}.json",
    )


def create_dataset_router(
    identity: IdentityModule,
    datasets: DatasetModule,
) -> APIRouter:
    router = APIRouter(prefix="/projects/{project_id}", tags=["datasets"])

    async def context(request: Request) -> RequestContext:
        try:
            return identity.resolve(
                IdentityEvidence(
                    headers=request.headers, request_id=getattr(request.state, "request_id", None)
                )
            )
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
                expected_version=body.expected_version,
            )
        except DatasetVersionConflict as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
        except (DatasetNotFound, DatasetValidationError) as error:
            raise failure(error) from error
        return _dataset_response(dataset)

    @router.delete("/datasets/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_dataset(project_id: str, dataset_id: str, request_context: Context) -> None:
        try:
            await datasets.delete_dataset(access(request_context), project_id, dataset_id)
        except DatasetNotFound as error:
            raise failure(error) from error

    return router
