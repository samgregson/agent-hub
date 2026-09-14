from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated

from ag_ui.core import RunAgentInput, RunErrorEvent
from ag_ui.encoder import EventEncoder
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from agent_hub_api.modules.agent_execution import (
    AgentExecutionModule,
    AgentRun,
    DuplicateAgentRun,
)
from agent_hub_api.modules.identity import IdentityModule, IdentityUnavailable, RequestContext
from agent_hub_api.modules.projects import ProjectModule, ThreadNotFound


def _camel_case(name: str) -> str:
    first, *rest = name.split("_")
    return first + "".join(part.title() for part in rest)


class AgentRunResponse(BaseModel):
    model_config = ConfigDict(alias_generator=_camel_case, populate_by_name=True)

    id: str
    thread_id: str
    status: str
    created_at: datetime
    updated_at: datetime
    error: dict[str, object] | None


class ThreadHistoryResponse(BaseModel):
    messages: list[dict[str, object]]


def _run_response(run: AgentRun) -> AgentRunResponse:
    return AgentRunResponse(
        id=run.id,
        thread_id=run.thread_id,
        status=run.status.value,
        created_at=run.created_at,
        updated_at=run.updated_at,
        error=run.error,
    )


def create_agent_transport_router(
    identity: IdentityModule,
    projects: ProjectModule,
    execution: AgentExecutionModule,
) -> APIRouter:
    router = APIRouter(prefix="/projects/{project_id}/threads/{thread_id}", tags=["agent"])

    async def request_context(request: Request) -> RequestContext:
        try:
            return identity.resolve(request)
        except IdentityUnavailable as error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authenticated platform identity is required",
            ) from error

    Context = Annotated[RequestContext, Depends(request_context)]

    async def authorize_thread(project_id: str, thread_id: str, context: RequestContext) -> None:
        try:
            await projects.load_thread(context, project_id, thread_id)
        except ThreadNotFound as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Thread not found",
            ) from error

    @router.get("/runs", response_model=list[AgentRunResponse])
    async def list_runs(
        project_id: str, thread_id: str, context: Context
    ) -> list[AgentRunResponse]:
        await authorize_thread(project_id, thread_id, context)
        return [_run_response(run) for run in await execution.list_runs(thread_id)]

    @router.get("/history", response_model=ThreadHistoryResponse)
    async def load_history(
        project_id: str, thread_id: str, context: Context
    ) -> ThreadHistoryResponse:
        await authorize_thread(project_id, thread_id, context)
        messages = await execution.load_messages(thread_id)
        return ThreadHistoryResponse(
            messages=[
                message.model_dump(mode="json", by_alias=True, exclude_none=True)
                for message in messages
            ]
        )

    @router.post("/agent")
    async def stream_agent(
        project_id: str,
        thread_id: str,
        input_data: RunAgentInput,
        request: Request,
        context: Context,
    ) -> StreamingResponse:
        await authorize_thread(project_id, thread_id, context)
        if input_data.thread_id != thread_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="AG-UI threadId does not match the authorized Thread",
            )
        if not input_data.run_id or len(input_data.run_id) > 128:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="AG-UI runId must contain between 1 and 128 characters",
            )

        try:
            events = await execution.start(input_data)
        except DuplicateAgentRun as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Agent Run already exists",
            ) from error

        encoder = EventEncoder(accept=request.headers.get("accept") or "")

        async def encoded_events() -> AsyncIterator[str]:
            try:
                async for event in events:
                    yield encoder.encode(event)
            except Exception:
                yield encoder.encode(
                    RunErrorEvent(
                        message="The agent run failed. Retry or inspect its status.",
                        code="AGENT_RUN_FAILED",
                    )
                )

        return StreamingResponse(
            encoded_events(),
            media_type=encoder.get_content_type(),
            headers={"Cache-Control": "no-cache, no-transform"},
        )

    return router
