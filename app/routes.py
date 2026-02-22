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
- Database and cache connections are injected via unified AppContext dependency.
- Consistent naming: cache_write for primary Redis, cache_read for replica.
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

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import text

from app.dependencies import get_request_context, get_url_service, get_service_manager
from app.enums import HealthStatus
from app.schemas import HealthResponse, URLCreate, URLResponse, URLStats
from app.url_service import URLShorteningService

__all__ = ["router"]

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["health"])
async def health_check(
    ctx = Depends(get_request_context),
    manager = Depends(get_service_manager)
) -> HealthResponse:
    ctx.logger.info("Health check requested")
    db_status = HealthStatus.HEALTHY
    cache_status = HealthStatus.HEALTHY

    try:
        await ctx.database.execute(text("SELECT 1"))
        ctx.logger.debug("Database health check passed")
    except Exception as e:
        ctx.logger.error(f"Database health check failed: {e}")
        db_status = HealthStatus.UNHEALTHY

    try:
        await ctx.cache_writer.ping()
        ctx.logger.debug("Cache health check passed")
    except Exception as e:
        ctx.logger.error(f"Cache health check failed: {e}")
        cache_status = HealthStatus.UNHEALTHY

    status = (
        HealthStatus.HEALTHY
        if db_status is HealthStatus.HEALTHY and cache_status is HealthStatus.HEALTHY
        else HealthStatus.UNHEALTHY
    )
    
    ctx.logger.info(f"Health check completed: {status.value}")
    return HealthResponse(status=status, database=db_status, cache=cache_status)


@router.post("/api/shorten", response_model=URLResponse, status_code=201, tags=["urls"])
async def shorten_url(
    payload: URLCreate,
    ctx = Depends(get_request_context),
    service: URLShorteningService = Depends(get_url_service),
) -> URLResponse:
    # Add context tags for better observability
    ctx.add_tag("url_creation")
    ctx.add_tag("api_endpoint")
    
    ctx.logger.info(
        f"URL shortening requested: {payload.url}",
        extra={
            "operation": "create_short_url",
            "target_url": payload.url,
            "custom_code": payload.custom_code
        }
    )
    
    try:
        url = await service.create_short_url(payload)
        ctx.logger.info(
            f"URL shortened successfully: {url.short_code}",
            extra={
                "operation": "create_short_url",
                "short_code": url.short_code,
                "url_id": url.id,
                "duration_ms": ctx.get_duration()
            }
        )
    except ValueError as exc:
        ctx.logger.warning(
            f"URL shortening failed: {exc}",
            extra={
                "operation": "create_short_url",
                "error": str(exc),
                "duration_ms": ctx.get_duration()
            }
        )
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return URLResponse(
        id=url.id,
        short_code=url.short_code,
        original_url=url.original_url,
        short_url=f"{ctx.settings.BASE_URL}/{url.short_code}",
        clicks=url.clicks,
        created_at=url.created_at,
        updated_at=url.updated_at,
    )


@router.get("/api/stats/{short_code}", response_model=URLStats, tags=["urls"])
async def get_stats(
    short_code: str,
    ctx = Depends(get_request_context),
    service: URLShorteningService = Depends(get_url_service),
) -> URLStats:
    ctx.logger.info(f"Stats requested for short code: {short_code}")
    url = await service.get_url_statistics(short_code)
    if not url:
        ctx.logger.warning(f"Stats not found for short code: {short_code}")
        raise HTTPException(status_code=404, detail="Short URL not found")

    return URLStats(
        id=url.id,
        short_code=url.short_code,
        original_url=url.original_url,
        short_url=f"{ctx.settings.BASE_URL}/{url.short_code}",
        clicks=url.clicks,
        created_at=url.created_at,
        updated_at=url.updated_at,
    )


@router.get("/{short_code}", tags=["redirect"])
async def redirect_to_url(
    short_code: str,
    ctx = Depends(get_request_context),
    service: URLShorteningService = Depends(get_url_service),
) -> RedirectResponse:
    # Add context tags for better observability
    ctx.add_tag("redirect")
    ctx.add_tag("lookup")
    
    ctx.logger.info(
        f"Redirect requested for short code: {short_code}",
        extra={
            "operation": "redirect",
            "short_code": short_code,
            "user_agent": ctx.user_agent,
            "client_ip": ctx.client_ip
        }
    )
    
    # cache_read → replica (read-only GET lookup, hot path)
    # cache_write → primary (INCR click buffer, XADD fallback stream)
    url = await service.lookup_url_by_code(short_code)
    if not url:
        ctx.logger.warning(
            f"Redirect failed - short code not found: {short_code}",
            extra={
                "operation": "redirect",
                "short_code": short_code,
                "error": "not_found",
                "duration_ms": ctx.get_duration()
            }
        )
        raise HTTPException(status_code=404, detail="Short URL not found")

    await service.track_url_click(url)
    
    ctx.logger.info(
        f"Redirect successful: {short_code} -> {url.original_url}",
        extra={
            "operation": "redirect",
            "short_code": short_code,
            "target_url": url.original_url,
            "url_id": url.id,
            "duration_ms": ctx.get_duration()
        }
    )
    
    return RedirectResponse(url=url.original_url, status_code=307)
