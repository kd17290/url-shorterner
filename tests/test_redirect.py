"""Redirect endpoint behavior tests."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_redirect_valid_code(client: AsyncClient) -> None:
    # Create a short URL first
    create_resp = await client.post("/api/shorten", json={"url": "https://www.google.com"})
    short_code = create_resp.json()["short_code"]

    # Follow redirect (httpx won't follow by default)
    response = await client.get(f"/{short_code}", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "https://www.google.com"


@pytest.mark.asyncio
async def test_redirect_invalid_code(client: AsyncClient) -> None:
    response = await client.get("/nonexistent", follow_redirects=False)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_redirect_increments_clicks(client: AsyncClient) -> None:
    # Create a short URL
    create_resp = await client.post("/api/shorten", json={"url": "https://www.python.org"})
    short_code = create_resp.json()["short_code"]

    # Visit 3 times
    for _ in range(3):
        await client.get(f"/{short_code}", follow_redirects=False)

    # Check stats
    stats_resp = await client.get(f"/api/stats/{short_code}")
    assert stats_resp.status_code == 200
    assert stats_resp.json()["clicks"] == 3


@pytest.mark.asyncio
async def test_redirect_with_custom_code(client: AsyncClient) -> None:
    await client.post(
        "/api/shorten",
        json={"url": "https://www.github.com", "custom_code": "ghub"},
    )
    response = await client.get("/ghub", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "https://www.github.com"
