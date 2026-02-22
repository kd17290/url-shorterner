"""
Keygen App with Robust ID Allocation Service

Features:
- Redis Sentinel + AOF + PostgreSQL fallback
- Distributed locking
- Comprehensive monitoring
- Zero collision guarantee
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from apps.keygen_app.schemas import AllocateRequest, AllocateResponse, HealthResponse
from apps.url_shortener.database import SessionLocal
from services.id_allocator.id_allocator_service import get_id_allocation_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    # Initialize ID allocation service
    id_service = get_id_allocation_service()
    async with SessionLocal() as db_session:
        await id_service.initialize(db_session)

    logger.info("Keygen service started successfully")

    yield

    # Shutdown
    await id_service.cleanup()
    logger.info("Keygen service stopped")


# Create FastAPI app
app = FastAPI(
    title="Robust ID Allocation API",
    description="High-availability ID allocation with Redis Sentinel + PostgreSQL fallback",
    version="2.0.0",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Comprehensive health check endpoint."""
    id_service = get_id_allocation_service()
    health_status = await id_service.get_service_health()

    return HealthResponse(
        status=health_status["overall_health"],
        redis_health=health_status["redis_health"],
        postgresql_health=health_status["postgresql_health"],
        active_locks=health_status["active_locks"],
        metrics=health_status["metrics"],
    )


@app.post("/allocate", response_model=AllocateResponse)
async def allocate_id_range(request: AllocateRequest):
    """
    Allocate a unique ID range with zero collision guarantee.

    The allocation strategy:
    1. Primary: Redis Sentinel with AOF persistence
    2. Secondary: PostgreSQL sequence
    3. Distributed locking prevents race conditions
    """
    id_service = get_id_allocation_service()

    try:
        start_id, end_id = await id_service.allocate_unique_id_range(request.size)

        return AllocateResponse(
            start=start_id, end=end_id, source="robust_allocation", timestamp=asyncio.get_event_loop().time()
        )

    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from None
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {e!s}") from None


@app.get("/metrics")
async def get_metrics():
    """Get detailed allocation metrics."""
    id_service = get_id_allocation_service()
    return await id_service.get_service_health()


@app.get("/status")
async def get_status():
    """Get service status and configuration."""
    id_service = get_id_allocation_service()
    health = await id_service.get_service_health()

    return {
        "service": "id-allocation-service",
        "version": "2.0.0",
        "architecture": "redis-sentinel-postgresql-fallback",
        "health": health,
        "features": [
            "redis-sentinel-ha",
            "aof-persistence",
            "postgresql-fallback",
            "distributed-locking",
            "zero-collision-guarantee",
            "comprehensive-monitoring",
        ],
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8010)
