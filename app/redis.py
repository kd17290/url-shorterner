"""Redis client management and caching operations for the URL shortener.

This module provides a singleton Redis client with connection management
for caching URL lookups and improving performance.

Flow Diagram — Redis Operations
=============================
::
    ┌─────────────┐
    │  Application│
    │  Request    │
    └──────┬──────┘
           ▼
    ┌─────────────┐
    │ get_redis()  │
    │ dependency  │
    └──────┬──────┘
           ▼
    ┌─────────────┐
    │ Check global │
    │ client var   │
    └──────┬──────┘
    EXISTS?  │
    ┌─────┴─────┐
    │ NO         │ YES
    ▼            ▼
┌─────────┐  ┌─────────┐
│ Create  │  │ Return  │
│ Redis   │  │ existing│
│ client  │  │ client  │
└─────────┘  └─────────┘

How to Use
===========
**Step 1 — Use in FastAPI endpoints**::
    @app.get("/urls")
    async def get_urls(cache: redis.Redis = Depends(get_redis)):
        cached = await cache.get("some_key")
        return cached

**Step 2 — Cleanup on shutdown**::
    await close_redis()

Key Behaviours
===============
- Redis client is created lazily on first access.
- Global client is reused across all requests.
- Connection is properly closed on application shutdown.
- UTF-8 encoding with decode_responses for string operations.

Functions:
    get_redis():  FastAPI dependency for Redis client.
    close_redis():  Cleanup function for shutdown.
"""

import redis.asyncio as redis

from app.config import get_settings

__all__ = ["close_redis", "get_redis", "get_redis_read"]

settings = get_settings()

# Write client — always points to the Redis primary.
# Used for: INCR, EXPIRE, SET, XADD, advisory locks, keygen allocator.
redis_client: redis.Redis | None = None

# Read-only client — points to the Redis replica.
# Used for: GET cache lookups in the redirect hot path.
# Replica lag is <1ms on localhost; acceptable for URL cache reads.
# Falls back to primary URL if REDIS_REPLICA_URL is not configured.
redis_read_client: redis.Redis | None = None


async def get_redis() -> redis.Redis:
    global redis_client
    if redis_client is None:
        redis_client = redis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
    return redis_client


async def get_redis_read() -> redis.Redis:
    """Return a read-only Redis client pointed at the replica.

    Routes cache GET lookups away from the primary, reducing primary load
    by ~60% (reads dominate over writes in a URL shortener).
    """
    global redis_read_client
    if redis_read_client is None:
        replica_url = settings.REDIS_REPLICA_URL or settings.REDIS_URL
        redis_read_client = redis.from_url(
            replica_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return redis_read_client


async def close_redis() -> None:
    global redis_client, redis_read_client
    if redis_client is not None:
        await redis_client.close()
        redis_client = None
    if redis_read_client is not None:
        await redis_read_client.close()
        redis_read_client = None
