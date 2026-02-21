"""Business logic layer for URL shortening operations.

This module provides the core service functions for URL creation, lookup,
click tracking, and caching with proper error handling and atomic operations.

Flow Diagram — URL Creation
===========================
::
    ┌─────────────┐
    │  POST /api/ │
    │  shorten     │
    └──────┬──────┘
           ▼
    ┌─────────────┐
    │ Validate URL│
    │ (Pydantic)   │
    └──────┬──────┘
           ▼
    ┌─────────────┐
    │ Generate or │
    │ use custom   │
    │ short code   │
    └──────┬──────┘
           ▼
    ┌─────────────┐
    │ Check for   │
    │ uniqueness  │
    │ (PostgreSQL)│
    └──────┬──────┘
           ▼
    ┌─────────────┐
    │ Create URL  │
    │ record      │
    └──────┬──────┘
           ▼
    ┌─────────────┐
    │ Cache in    │
    │ Redis (TTL) │
    └──────┬──────┘
           ▼
    ┌─────────────┐
    │ Return URL  │
    │ response    │
    └─────────────┘

Flow Diagram — URL Lookup & Redirect
=====================================
::
    ┌─────────────┐
    │  GET /:code  │
    └──────┬──────┘
           ▼
    ┌─────────────┐
    │ Check Redis │
    │ cache       │
    └──────┬──────┘
    HIT?  │
    ┌─────┴─────┐
    │ NO         │ YES
    ▼            ▼
┌─────────┐  ┌─────────┐
│ Query   │  │ Return  │
│ PostgreSQL│ │ cached  │
│ DB       │ │ URL     │
└────┬────┘  └────┬────┘
     │            │
     ▼            ▼
┌─────────┐  ┌─────────┐
│ Cache   │  │ Increment│
│ result  │  │ clicks   │
└────┬────┘  └────┬────┘
     │            │
     ▼            ▼
     └─────┬──────┘
           ▼
    ┌─────────────┐
    │ Increment   │
    │ click count │
    │ (atomic)    │
    └──────┬──────┘
           ▼
    ┌─────────────┐
    │ 307 Redirect│
    │ to original │
    │ URL         │
    └─────────────┘

How to Use
===========
**Step 1 — Create a short URL**::
    payload = URLCreate(url="https://example.com")
    url = await create_short_url(payload, db, cache)
    # url is a URL ORM instance

**Step 2 — Lookup for redirect**::
    url = await get_url_by_code("abc123", db, cache)
    if url:
        await increment_clicks(url, db, cache)
        return RedirectResponse(url.original_url)
    else:
        raise HTTPException(404)

**Step 3 — Get statistics**::
    url = await get_url_stats("abc123", db, cache)
    return {"clicks": url.clicks, "created_at": url.created_at}

Key Behaviours
===============
- Short codes are generated using nanoid with configurable length.
- Custom codes are validated for uniqueness before creation.
- Redis cache has 1-hour TTL to balance freshness and performance.
- Click increments are atomic database operations.
- All operations are async and use proper connection management.
- Cache is updated after any database modification.

Functions:
    generate_short_code():  Creates random URL-safe strings.
    get_url_by_code():  Lookup with cache-first strategy.
    create_short_url():  Create new URL with uniqueness checks.
    increment_clicks():  Atomic click counter increment.
    get_url_stats():  Retrieve URL statistics.
    _cache_url():  Internal cache population helper.
"""

import asyncio
import json

import httpx
import redis.asyncio as redis
from nanoid import generate
from prometheus_client import Counter
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.kafka import publish_click_event
from app.models import URL
from app.schemas import CachedURLPayload, URLCreate

__all__ = [
    "generate_short_code",
    "get_url_by_code",
    "create_short_url",
    "increment_clicks",
    "get_url_stats",
]

settings = get_settings()

CACHE_TTL = 3600  # 1 hour
ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

_id_block_next: int = 0
_id_block_end: int = -1

APP_EDGE_DB_READS_TOTAL = Counter(
    "app_edge_db_reads_total",
    "DB read operations initiated by app service",
)
APP_EDGE_DB_WRITES_TOTAL = Counter(
    "app_edge_db_writes_total",
    "DB write operations initiated by app service",
)
APP_EDGE_REDIS_OPS_TOTAL = Counter(
    "app_edge_redis_ops_total",
    "Redis cache operations initiated by app service",
)
APP_EDGE_KAFKA_PUBLISH_TOTAL = Counter(
    "app_edge_kafka_publish_total",
    "Kafka click events successfully published by app service",
)
APP_EDGE_STREAM_FALLBACK_TOTAL = Counter(
    "app_edge_stream_fallback_total",
    "Redis stream fallback events from app service when Kafka publish fails",
)


def _base62_encode(value: int) -> str:
    assert isinstance(value, int) and value >= 0, f"value must be non-negative int, got {value!r}"
    if value == 0:
        return ALPHABET[0]

    base = len(ALPHABET)
    encoded_chars: list[str] = []
    current = value
    while current > 0:
        current, remainder = divmod(current, base)
        encoded_chars.append(ALPHABET[remainder])
    encoded_chars.reverse()
    return "".join(encoded_chars)


async def _allocate_id_block(cache: redis.Redis) -> None:
    global _id_block_next, _id_block_end
    assert cache is not None, "cache must not be None"

    start_value: int
    end_value: int
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.post(
                f"{settings.KEYGEN_SERVICE_URL}/allocate",
                json={"size": settings.ID_BLOCK_SIZE},
            )
        response.raise_for_status()
        payload = response.json()
        start_value = int(payload["start"])
        end_value = int(payload["end"])
    except Exception:
        # Fallback for local/test mode where external keygen service may not run.
        end_value = await cache.incrby(settings.ID_ALLOCATOR_KEY, settings.ID_BLOCK_SIZE)
        start_value = end_value - settings.ID_BLOCK_SIZE + 1

    _id_block_next = start_value
    _id_block_end = end_value


async def _generate_short_code_from_allocator(cache: redis.Redis) -> str:
    global _id_block_next, _id_block_end
    assert cache is not None, "cache must not be None"

    if _id_block_next > _id_block_end:
        await _allocate_id_block(cache)

    allocated_id = _id_block_next
    _id_block_next += 1

    encoded = _base62_encode(allocated_id)
    return encoded.rjust(settings.SHORT_CODE_LENGTH, ALPHABET[0])


async def _acquire_cache_lock(cache: redis.Redis, short_code: str) -> bool:
    lock_key = f"lock:url:{short_code}"
    locked = await cache.set(lock_key, "1", ex=settings.CACHE_LOCK_TTL_SECONDS, nx=True)
    return bool(locked)


async def _release_cache_lock(cache: redis.Redis, short_code: str) -> None:
    await cache.delete(f"lock:url:{short_code}")
    APP_EDGE_REDIS_OPS_TOTAL.inc()


async def _get_buffered_click_count(short_code: str, cache: redis.Redis) -> int:
    key = f"{settings.CLICK_BUFFER_KEY_PREFIX}:{short_code}"
    value = await cache.get(key)
    APP_EDGE_REDIS_OPS_TOTAL.inc()
    if value is None:
        return 0
    return int(value)


async def _flush_click_buffer(short_code: str, db: AsyncSession, cache: redis.Redis) -> None:
    assert short_code, "short_code must be non-empty"
    lock_key = f"lock:click_flush:{short_code}"
    acquired = await cache.set(lock_key, "1", ex=2, nx=True)
    if not acquired:
        return

    buffer_key = f"{settings.CLICK_BUFFER_KEY_PREFIX}:{short_code}"
    try:
        buffered = await cache.get(buffer_key)
        if buffered is None:
            return

        buffered_count = int(buffered)
        if buffered_count <= 0:
            return

        await db.execute(update(URL).where(URL.short_code == short_code).values(clicks=URL.clicks + buffered_count))
        await db.commit()

        await cache.delete(buffer_key)
        await cache.delete(f"url:{short_code}")
    finally:
        await cache.delete(lock_key)


def generate_short_code(length: int = settings.SHORT_CODE_LENGTH) -> str:
    assert isinstance(length, int) and length > 0, f"length must be a positive integer, got {length!r}"
    return generate(ALPHABET, length)


async def get_url_by_code(short_code: str, db: AsyncSession, cache: redis.Redis, cache_write: redis.Redis | None = None) -> URL | None:
    assert isinstance(short_code, str) and short_code, f"short_code must be a non-empty string, got {short_code!r}"
    assert db is not None, "db must not be None"
    assert cache is not None, "cache must not be None"
    # cache_write is the primary Redis used for lock acquisition (writes).
    # Falls back to cache if not provided (backwards-compatible).
    _write = cache_write if cache_write is not None else cache
    cache_key = f"url:{short_code}"
    cached = await cache.get(cache_key)
    APP_EDGE_REDIS_OPS_TOTAL.inc()
    if cached:
        data = json.loads(cached)
        return URL(**data)

    acquired_lock = await _acquire_cache_lock(_write, short_code)
    if not acquired_lock:
        for _ in range(settings.CACHE_LOCK_RETRY_COUNT):
            await asyncio.sleep(settings.CACHE_LOCK_RETRY_DELAY_SECONDS)
            cached_retry = await cache.get(cache_key)
            if cached_retry:
                data = json.loads(cached_retry)
                return URL(**data)

    try:
        # Cache miss fallback to database.
        result = await db.execute(select(URL).where(URL.short_code == short_code))
        APP_EDGE_DB_READS_TOTAL.inc()
        url = result.scalar_one_or_none()

        if url:
            await _cache_url(url, _write)
    finally:
        if acquired_lock:
            await _release_cache_lock(_write, short_code)

    return url


async def create_short_url(payload: URLCreate, db: AsyncSession, cache: redis.Redis) -> URL:
    assert payload is not None, "payload must not be None"
    assert db is not None, "db must not be None"
    assert cache is not None, "cache must not be None"
    if payload.custom_code:
        short_code = payload.custom_code
        existing = await db.execute(select(URL).where(URL.short_code == short_code))
        APP_EDGE_DB_READS_TOTAL.inc()
        if existing.scalar_one_or_none():
            raise ValueError(f"Custom code '{short_code}' is already taken")
    else:
        # Ensure uniqueness for mixed-mode deployments where historic codes may exist.
        while True:
            short_code = await _generate_short_code_from_allocator(cache)
            existing = await db.execute(select(URL).where(URL.short_code == short_code))
            APP_EDGE_DB_READS_TOTAL.inc()
            if not existing.scalar_one_or_none():
                break

    url = URL(short_code=short_code, original_url=str(payload.url))
    db.add(url)
    await db.commit()
    APP_EDGE_DB_WRITES_TOTAL.inc()
    await db.refresh(url)
    assert url.id is not None, "url.id must be set after commit"

    await _cache_url(url, cache)

    return url


async def increment_clicks(url: URL, db: AsyncSession, cache: redis.Redis) -> None:
    assert url is not None, "url must not be None"
    assert isinstance(url, URL), f"url must be URL instance, got {type(url).__name__}"
    assert db is not None, "db must not be None"
    assert cache is not None, "cache must not be None"
    assert url.id is not None, "url.id must be set for increment"

    buffer_key = f"{settings.CLICK_BUFFER_KEY_PREFIX}:{url.short_code}"
    buffered_count = await cache.incr(buffer_key)
    APP_EDGE_REDIS_OPS_TOTAL.inc()
    if buffered_count == 1:
        await cache.expire(buffer_key, settings.CLICK_BUFFER_TTL_SECONDS)
        APP_EDGE_REDIS_OPS_TOTAL.inc()

    published = await publish_click_event(url.short_code, 1)
    if not published:
        APP_EDGE_STREAM_FALLBACK_TOTAL.inc()
        await cache.xadd(
            settings.CLICK_STREAM_KEY,
            {
                "short_code": url.short_code,
                "delta": "1",
            },
        )
        APP_EDGE_REDIS_OPS_TOTAL.inc()
    else:
        APP_EDGE_KAFKA_PUBLISH_TOTAL.inc()


async def get_url_stats(short_code: str, db: AsyncSession, cache: redis.Redis) -> URL | None:
    assert isinstance(short_code, str) and short_code, f"short_code must be a non-empty string, got {short_code!r}"
    assert db is not None, "db must not be None"
    assert cache is not None, "cache must not be None"
    result = await db.execute(select(URL).where(URL.short_code == short_code))
    APP_EDGE_DB_READS_TOTAL.inc()
    url = result.scalar_one_or_none()
    if not url:
        return None

    buffered_clicks = await _get_buffered_click_count(short_code, cache)
    if buffered_clicks > 0:
        url.clicks += buffered_clicks
    return url


async def _cache_url(url: URL, cache: redis.Redis) -> None:
    assert url is not None, "url must not be None"
    assert isinstance(url, URL), f"url must be URL instance, got {type(url).__name__}"
    assert cache is not None, "cache must not be None"
    assert url.id is not None, "url.id must be set for caching"
    assert url.short_code, "url.short_code must be set for caching"
    payload = CachedURLPayload.model_validate(url)
    await cache.set(f"url:{url.short_code}", json.dumps(payload.model_dump(mode="json")), ex=CACHE_TTL)
    APP_EDGE_REDIS_OPS_TOTAL.inc()
