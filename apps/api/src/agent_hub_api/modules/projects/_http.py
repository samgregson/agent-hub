from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_hub_api.modules.identity import IdentityModule, IdentityUnavailable, RequestContext
from agent_hub_api.modules.projects._application import (
    Project,
    ProjectModule,
    ProjectNotFound,
    Thread,
    ThreadNotFound,
)


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, name: str) -> str:
        normalized = name.strip()
        if not normalized:
            raise ValueError("Project name cannot be blank")
        return normalized


def _camel_case(name: str) -> str:
    first, *rest = name.split("_")
    return first + "".join(part.title() for part in rest)


class ProjectResponse(BaseModel):
    model_config = ConfigDict(alias_generator=lambda name: _camel_case(name), populate_by_name=True)

    id: str
    name: str
    created_at: datetime
    updated_at: datetime


class ThreadCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, title: str) -> str:
        normalized = title.strip()
        if not normalized:
            raise ValueError("Thread title cannot be blank")
        return normalized


class ThreadResponse(BaseModel):
    model_config = ConfigDict(alias_generator=lambda name: _camel_case(name), populate_by_name=True)

    id: str
    project_id: str
    title: str
    created_at: datetime
    updated_at: datetime


def _response(project: Project) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        name=project.name,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def _thread_response(thread: Thread) -> ThreadResponse:
    return ThreadResponse(
        id=thread.id,
        project_id=thread.project_id,
        title=thread.title,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
    )


def create_project_router(
    identity: IdentityModule,
    projects: ProjectModule,
) -> APIRouter:
    router = APIRouter(prefix="/projects", tags=["projects"])

    async def request_context(request: Request) -> RequestContext:
        try:
            return identity.resolve(request)
        except IdentityUnavailable as error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authenticated platform identity is required",
            ) from error

    Context = Annotated[RequestContext, Depends(request_context)]

    @router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
    async def create_project(body: ProjectCreateRequest, context: Context) -> ProjectResponse:
        return _response(await projects.create(context, body.name))

    @router.get("", response_model=list[ProjectResponse])
    async def list_projects(context: Context) -> list[ProjectResponse]:
        return [_response(project) for project in await projects.list(context)]

    @router.get("/{project_id}", response_model=ProjectResponse)
    async def load_project(project_id: str, context: Context) -> ProjectResponse:
        try:
            return _response(await projects.load(context, project_id))
        except ProjectNotFound as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            ) from error

    @router.post(
        "/{project_id}/threads",
        response_model=ThreadResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_thread(
        project_id: str, body: ThreadCreateRequest, context: Context
    ) -> ThreadResponse:
        try:
            return _thread_response(await projects.create_thread(context, project_id, body.title))
        except ProjectNotFound as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            ) from error

    @router.get("/{project_id}/threads", response_model=list[ThreadResponse])
    async def list_threads(project_id: str, context: Context) -> list[ThreadResponse]:
        try:
            return [
                _thread_response(thread)
                for thread in await projects.list_threads(context, project_id)
            ]
        except ProjectNotFound as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            ) from error

    @router.get("/{project_id}/threads/{thread_id}", response_model=ThreadResponse)
    async def load_thread(project_id: str, thread_id: str, context: Context) -> ThreadResponse:
        try:
            return _thread_response(await projects.load_thread(context, project_id, thread_id))
        except ThreadNotFound as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Thread not found",
            ) from error

    return router
