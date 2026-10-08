from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from agent_hub_api.modules.request_limits import RequestBodyLimitMiddleware


def client_with_limit(max_bytes: int) -> AsyncClient:
    async def echo(request: Request) -> PlainTextResponse:
        return PlainTextResponse(str(len(await request.body())))

    app = RequestBodyLimitMiddleware(
        Starlette(routes=[Route("/echo", echo, methods=["POST"])]), max_bytes=max_bytes
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_declared_oversized_body_is_rejected_before_parsing() -> None:
    async with client_with_limit(4) as client:
        response = await client.post("/echo", content=b"12345")

    assert response.status_code == 413
    assert response.json() == {"detail": "Request body exceeds the size limit"}


@pytest.mark.asyncio
async def test_streamed_body_is_bounded_and_allowed_body_is_replayed() -> None:
    async def chunks() -> AsyncIterator[bytes]:
        yield b"123"
        yield b"45"

    async with client_with_limit(4) as client:
        too_large = await client.post("/echo", content=chunks())
        accepted = await client.post("/echo", content=b"1234")

    assert too_large.status_code == 413
    assert accepted.status_code == 200
    assert accepted.text == "4"


@pytest.mark.asyncio
async def test_many_empty_body_frames_are_rejected() -> None:
    async def empty_chunks() -> AsyncIterator[bytes]:
        for _ in range(1_025):
            yield b""

    async with client_with_limit(4) as client:
        response = await client.post("/echo", content=empty_chunks())

    assert response.status_code == 413
