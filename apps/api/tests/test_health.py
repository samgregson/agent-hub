from collections.abc import Awaitable, Callable

from fastapi.testclient import TestClient

from agent_hub_api.main import create_app
from agent_hub_api.settings import Settings


def client_with(
    readiness_check: Callable[[Settings], Awaitable[None]],
) -> TestClient:
    return TestClient(
        create_app(settings=Settings(environment="test"), readiness_check=readiness_check)
    )


def test_liveness_does_not_depend_on_database() -> None:
    async def unavailable(_: Settings) -> None:
        raise RuntimeError("database unavailable")

    with client_with(unavailable) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_ready_dependency() -> None:
    async def available(_: Settings) -> None:
        return None

    with client_with(available) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readiness_reports_unavailable_dependency() -> None:
    async def unavailable(_: Settings) -> None:
        raise RuntimeError("database unavailable")

    with client_with(unavailable) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
