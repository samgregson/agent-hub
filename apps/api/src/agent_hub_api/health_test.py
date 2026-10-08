from collections.abc import Awaitable, Callable
from typing import cast

import pytest
from httpx import ASGITransport, AsyncClient

from agent_hub_api.main import create_app
from agent_hub_api.modules.plugin_gateway import PluginGatewayModule
from agent_hub_api.settings import Settings


def client_with(
    readiness_check: Callable[[Settings], Awaitable[None]],
) -> AsyncClient:
    app = create_app(settings=Settings(environment="test"), readiness_check=readiness_check)
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )


@pytest.mark.asyncio
async def test_liveness_does_not_depend_on_database() -> None:
    async def unavailable(_: Settings) -> None:
        raise RuntimeError("database unavailable")

    async with client_with(unavailable) as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_readiness_reports_ready_dependency() -> None:
    async def available(_: Settings) -> None:
        return None

    async with client_with(available) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


@pytest.mark.asyncio
async def test_readiness_reports_unavailable_dependency() -> None:
    async def unavailable(_: Settings) -> None:
        raise RuntimeError("database unavailable")

    async with client_with(unavailable) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


@pytest.mark.asyncio
async def test_remote_plugin_is_not_a_readiness_dependency() -> None:
    async def available(_: Settings) -> None:
        return None

    class UnavailablePlugin:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"Readiness must not access the Plugin: {name}")

    app = create_app(
        settings=Settings(environment="test"),
        readiness_check=available,
        plugin_gateway=cast(PluginGatewayModule, UnavailablePlugin()),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
