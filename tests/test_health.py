"""Health endpoint tests."""

import pytest
from httpx import AsyncClient
from app.enums import HealthStatus


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == HealthStatus.HEALTHY.value
    assert data["database"] == HealthStatus.HEALTHY.value
    assert data["cache"] == HealthStatus.HEALTHY.value
