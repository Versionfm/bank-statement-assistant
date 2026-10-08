import pytest
from httpx import ASGITransport, AsyncClient

from bank_statement_assistant.adapters.http.app import create_app


class StubReadiness:
    def __init__(self, ready: bool) -> None:
        self._ready = ready

    async def check(self) -> bool:
        return self._ready


def client_for(*, ready: bool) -> AsyncClient:
    app = create_app(readiness=StubReadiness(ready))
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.anyio
async def test_liveness_reports_that_the_process_is_running() -> None:
    async with client_for(ready=True) as client:
        response = await client.get("/api/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_readiness_reports_database_unavailability() -> None:
    async with client_for(ready=False) as client:
        response = await client.get("/api/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


@pytest.mark.anyio
async def test_readiness_reports_when_dependencies_are_available() -> None:
    async with client_for(ready=True) as client:
        response = await client.get("/api/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_describes_health_response_contracts() -> None:
    schema = create_app(readiness=StubReadiness(True)).openapi()

    assert schema["paths"]["/api/health/ready"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"] == {"$ref": "#/components/schemas/HealthResponse"}
