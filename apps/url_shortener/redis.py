"""Redis Sentinel setup for the URL shortener application."""

import redis.asyncio as redis

from services.redis.redis_sentinel_service import RedisRole, get_redis_sentinel_service

__all__ = ["close_redis", "get_redis", "get_redis_read"]

# Global Redis Sentinel service
_redis_service = None


async def _get_service():
    """Get Redis Sentinel service instance."""
    global _redis_service
    if _redis_service is None:
        _redis_service = get_redis_sentinel_service()
        await _redis_service.initialize()
    return _redis_service


async def get_redis() -> redis.Redis:
    """FastAPI dependency for Redis write client (master)."""
    service = await _get_service()
    return await service.get_client(role=RedisRole.MASTER)


async def get_redis_read() -> redis.Redis:
    """FastAPI dependency for Redis read client (replica or master)."""
    service = await _get_service()
    return await service.get_client(role=RedisRole.REPLICA)


async def close_redis() -> None:
    """Cleanup Redis connections."""
    global _redis_service
    if _redis_service is not None:
        await _redis_service.cleanup()
        _redis_service = None
