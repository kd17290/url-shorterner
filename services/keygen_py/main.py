"""Standalone key generation service using Redis-backed range allocation."""

import redis.asyncio as redis
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.config import get_settings
from app.enums import HealthStatus

__all__ = ["app"]

settings = get_settings()
app = FastAPI(title="keygen-service", version="1.0.0")


async def _allocate_from_with_fallback(size: int) -> tuple[int, int]:
    redis_clients = [app.state.redis_primary, app.state.redis_secondary]
    for client in redis_clients:
        try:
            end_value = await client.incrby(settings.ID_ALLOCATOR_KEY, size)
            start_value = end_value - size + 1
            return start_value, end_value
        except Exception:
            continue
    raise HTTPException(status_code=503, detail="key allocation backends unavailable")


class AllocateRequest(BaseModel):
    size: int = settings.ID_BLOCK_SIZE


class AllocateResponse(BaseModel):
    start: int
    end: int


class HealthResponse(BaseModel):
    status: HealthStatus
    primary: HealthStatus
    secondary: HealthStatus


@app.on_event("startup")
async def startup() -> None:
    app.state.redis_primary = redis.from_url(
        settings.KEYGEN_PRIMARY_REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )
    app.state.redis_secondary = redis.from_url(
        settings.KEYGEN_SECONDARY_REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )


@app.on_event("shutdown")
async def shutdown() -> None:
    if app.state.redis_primary is not None:
        await app.state.redis_primary.aclose()
    if app.state.redis_secondary is not None:
        await app.state.redis_secondary.aclose()


@app.get("/health")
async def health() -> HealthResponse:
    primary_status = HealthStatus.HEALTHY
    secondary_status = HealthStatus.HEALTHY

    try:
        await app.state.redis_primary.ping()
    except Exception:  # pragma: no cover - defensive runtime guard
        primary_status = HealthStatus.UNHEALTHY

    try:
        await app.state.redis_secondary.ping()
    except Exception:  # pragma: no cover - defensive runtime guard
        secondary_status = HealthStatus.UNHEALTHY

    overall_status = (
        HealthStatus.HEALTHY
        if primary_status is HealthStatus.HEALTHY or secondary_status is HealthStatus.HEALTHY
        else HealthStatus.UNHEALTHY
    )
    return HealthResponse(status=overall_status, primary=primary_status, secondary=secondary_status)


@app.post("/allocate", response_model=AllocateResponse)
async def allocate(req: AllocateRequest) -> AllocateResponse:
    if req.size <= 0:
        raise HTTPException(status_code=400, detail="size must be > 0")

    start_value, end_value = await _allocate_from_with_fallback(req.size)
    return AllocateResponse(start=start_value, end=end_value)
