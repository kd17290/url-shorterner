"""Pydantic schemas for the ID allocation API."""

from pydantic import BaseModel

__all__ = ["AllocateRequest", "AllocateResponse", "HealthResponse"]


class AllocateRequest(BaseModel):
    size: int = 1000


class AllocateResponse(BaseModel):
    start: int
    end: int
    source: str = "robust_allocation"
    timestamp: float = 0.0


class HealthResponse(BaseModel):
    status: str
    redis_health: str = "unknown"
    postgresql_health: str = "unknown"
    active_locks: int = 0
    metrics: dict = {}
