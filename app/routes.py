"""FastAPI route definitions for the URL shortener REST API.

This module provides all HTTP endpoints with proper dependency injection,
error handling, and response serialization for the URL shortening service.

API Endpoint Overview
=====================
::
    GET  /health
        └─ HealthResponse (200)

    POST /api/shorten
        ├─ URLCreate (request body)
        └─ URLResponse (201) or 409/422

    GET  /api/stats/:short_code
        └─ URLStats (200) or 404

    GET  /:short_code
        └─ 307 Redirect or 404

Request Flow Diagram
====================
::
    ┌─────────────┐
    │  HTTP       │
    │  Request    │
    └──────┬──────┘
           ▼
    ┌─────────────┐
    │ FastAPI     │
    │ Router      │
    └──────┬──────┘
           ▼
    ┌─────────────┐
    │ Validate &  │
    │ Parse       │
    │ (Pydantic)   │
    └──────┬──────┘
           ▼
    ┌─────────────┐
    │ Inject      │
    │ Dependencies│
    │ (DB, Cache) │
    └──────┬──────┘
           ▼
    ┌─────────────┐
    │ Call Service│
    │ Layer       │
    └──────┬──────┘
           ▼
    ┌─────────────┐
    │ Serialize   │
    │ Response    │
    │ (Pydantic)   │
    └──────┬──────┘
           ▼
    ┌─────────────┐
    │ HTTP        │
    │ Response    │
    └─────────────┘

How to Use
===========
**Step 1 — Import and include router**::
    from app.routes import router
    app.include_router(router)

**Step 2 — Access endpoints**::
    # Health check
    GET http://localhost:8000/health
    
    # Shorten URL
    POST http://localhost:8000/api/shorten
    {"url": "https://example.com"}
    
    # Redirect
    GET http://localhost:8000/abc123
    
    # Stats
    GET http://localhost:8000/api/stats/abc123

Key Behaviours
===============
- All endpoints use async/await for non-blocking I/O.
- Database and Redis connections are injected as dependencies.
- Proper HTTP status codes and error responses.
- CORS is enabled for cross-origin requests.
- Auto-generated OpenAPI documentation at /docs.
- 307 redirects preserve HTTP method for analytics.

Endpoints:
    /health:  Health check for monitoring.
    /api/shorten:  Create new short URLs.
    /api/stats/:code:  Get URL statistics.
    /:code:  Redirect to original URL.
"""

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import service
from app.config import get_settings
from app.database import get_db
from app.redis import get_redis
from app.schemas import HealthResponse, URLCreate, URLResponse, URLStats

__all__ = ["router"]

settings = get_settings()

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["health"])
async def health_check(
    db: AsyncSession = Depends(get_db),
    cache: redis.Redis = Depends(get_redis),
) -> HealthResponse:
    db_status = "healthy"
    cache_status = "healthy"

    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        db_status = "unhealthy"

    try:
        await cache.ping()
    except Exception:
        cache_status = "unhealthy"

    status = "healthy" if db_status == "healthy" and cache_status == "healthy" else "unhealthy"
    return HealthResponse(status=status, database=db_status, cache=cache_status)


@router.post("/api/shorten", response_model=URLResponse, status_code=201, tags=["urls"])
async def shorten_url(
    payload: URLCreate,
    db: AsyncSession = Depends(get_db),
    cache: redis.Redis = Depends(get_redis),
) -> URLResponse:
    try:
        url = await service.create_short_url(payload, db, cache)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return URLResponse(
        id=url.id,
        short_code=url.short_code,
        original_url=url.original_url,
        short_url=f"{settings.BASE_URL}/{url.short_code}",
        clicks=url.clicks,
        created_at=url.created_at,
        updated_at=url.updated_at,
    )


@router.get("/api/stats/{short_code}", response_model=URLStats, tags=["urls"])
async def get_stats(
    short_code: str,
    db: AsyncSession = Depends(get_db),
    cache: redis.Redis = Depends(get_redis),
) -> URLStats:
    url = await service.get_url_stats(short_code, db, cache)
    if not url:
        raise HTTPException(status_code=404, detail="Short URL not found")

    return URLStats(
        id=url.id,
        short_code=url.short_code,
        original_url=url.original_url,
        short_url=f"{settings.BASE_URL}/{url.short_code}",
        clicks=url.clicks,
        created_at=url.created_at,
        updated_at=url.updated_at,
    )


@router.get("/{short_code}", tags=["redirect"])
async def redirect_to_url(
    short_code: str,
    db: AsyncSession = Depends(get_db),
    cache: redis.Redis = Depends(get_redis),
) -> RedirectResponse:
    url = await service.get_url_by_code(short_code, db, cache)
    if not url:
        raise HTTPException(status_code=404, detail="Short URL not found")

    await service.increment_clicks(url, db, cache)
    return RedirectResponse(url=url.original_url, status_code=307)
