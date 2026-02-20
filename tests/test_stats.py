"""Stats endpoint behavior tests."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_stats_valid_code(client: AsyncClient) -> None:
    # Create a short URL
    create_resp = await client.post("/api/shorten", json={"url": "https://www.google.com"})
    short_code = create_resp.json()["short_code"]

    response = await client.get(f"/api/stats/{short_code}")
    assert response.status_code == 200
    data = response.json()
    assert data["short_code"] == short_code
    assert data["original_url"] == "https://www.google.com"
    assert data["clicks"] == 0
    assert "short_url" in data
    assert "created_at" in data


@pytest.mark.asyncio
async def test_stats_invalid_code(client: AsyncClient) -> None:
    response = await client.get("/api/stats/nonexistent")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_stats_after_clicks(client: AsyncClient) -> None:
    create_resp = await client.post("/api/shorten", json={"url": "https://www.example.com"})
    short_code = create_resp.json()["short_code"]

    # Generate clicks
    for _ in range(5):
        await client.get(f"/{short_code}", follow_redirects=False)

    response = await client.get(f"/api/stats/{short_code}")
    assert response.status_code == 200
    assert response.json()["clicks"] == 5
