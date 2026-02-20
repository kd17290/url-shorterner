"""Shorten endpoint behavior tests."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_shorten_valid_url(client: AsyncClient) -> None:
    response = await client.post("/api/shorten", json={"url": "https://www.google.com"})
    assert response.status_code == 201
    data = response.json()
    assert data["original_url"] == "https://www.google.com"
    assert data["short_code"] is not None
    assert len(data["short_code"]) == 7
    assert data["clicks"] == 0
    assert "short_url" in data


@pytest.mark.asyncio
async def test_shorten_invalid_url(client: AsyncClient) -> None:
    response = await client.post("/api/shorten", json={"url": "not-a-url"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_shorten_empty_url(client: AsyncClient) -> None:
    response = await client.post("/api/shorten", json={"url": ""})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_shorten_with_custom_code(client: AsyncClient) -> None:
    response = await client.post("/api/shorten", json={"url": "https://www.github.com", "custom_code": "mycode"})
    assert response.status_code == 201
    data = response.json()
    assert data["short_code"] == "mycode"


@pytest.mark.asyncio
async def test_shorten_duplicate_custom_code(client: AsyncClient) -> None:
    await client.post("/api/shorten", json={"url": "https://www.github.com", "custom_code": "taken1"})
    response = await client.post("/api/shorten", json={"url": "https://www.example.com", "custom_code": "taken1"})
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_shorten_custom_code_too_short(client: AsyncClient) -> None:
    response = await client.post("/api/shorten", json={"url": "https://www.github.com", "custom_code": "ab"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_shorten_custom_code_too_long(client: AsyncClient) -> None:
    response = await client.post(
        "/api/shorten",
        json={"url": "https://www.github.com", "custom_code": "a" * 21},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_shorten_custom_code_non_alphanumeric(client: AsyncClient) -> None:
    response = await client.post(
        "/api/shorten",
        json={"url": "https://www.github.com", "custom_code": "my-code!"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_shorten_multiple_urls(client: AsyncClient) -> None:
    urls = [
        "https://www.google.com",
        "https://www.github.com",
        "https://www.python.org",
    ]
    codes = set()
    for url in urls:
        response = await client.post("/api/shorten", json={"url": url})
        assert response.status_code == 201
        codes.add(response.json()["short_code"])
    # All codes should be unique
    assert len(codes) == 3
