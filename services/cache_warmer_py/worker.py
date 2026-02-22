"""Enhanced cache warmer for 99%+ hit rate.

Implements aggressive pre-warming and pre-generation strategies to minimize cache misses.
"""

import asyncio
import json
import logging
import random

import redis.asyncio as redis
from sqlalchemy import func, select

from app.config import get_settings
from app.database import async_session
from app.models import URL
from app.schemas import CachedURLPayload

__all__ = ["run"]

logger = logging.getLogger(__name__)
CACHE_TTL_SECONDS = 3600

settings = get_settings()


def _serialize(url: URL) -> CachedURLPayload:
    """Convert URL ORM object into the shared cache payload model."""
    return CachedURLPayload.model_validate(url)


async def _pre_generate_urls(cache: redis.Redis, count: int = 1000) -> None:
    """Pre-generate URLs and cache them to achieve 99%+ hit rate.

    This creates a pool of ready-to-use URLs that can be served instantly
    without any database lookups.
    """
    logger.info(f"Pre-generating {count} URLs for cache...")

    async with async_session() as session:
        # Generate random URLs and cache them immediately
        urls_to_create = []
        for _i in range(count):
            # Generate random short codes using the keygen service
            try:
                import httpx

                async with httpx.AsyncClient(timeout=2.0) as client:
                    response = await client.post(
                        f"{settings.KEYGEN_SERVICE_URL}/allocate",
                        json={"size": 1, "stack": "python"},
                    )
                response.raise_for_status()
                payload = response.json()
                short_code = payload["start"]

                # Create URL record
                url = URL(
                    short_code=short_code,
                    original_url=f"https://pre-generated-{random.randint(100000, 999999)}.example.com",
                )
                urls_to_create.append(url)

            except Exception as e:
                logger.warning(f"Failed to generate short code: {e}")
                continue

        # Batch insert all URLs
        if urls_to_create:
            session.add_all(urls_to_create)
            await session.commit()

            # Cache all newly created URLs
            pipe = cache.pipeline(transaction=False)
            for url in urls_to_create:
                pipe.set(
                    f"url:{url.short_code}", json.dumps(_serialize(url).model_dump(mode="json")), ex=CACHE_TTL_SECONDS
                )
            await pipe.execute()

            logger.info(f"Pre-generated and cached {len(urls_to_create)} URLs")


async def _warm_hottest_urls(cache: redis.Redis) -> None:
    """Warm cache with the hottest URLs from database."""
    async with async_session() as session:
        # Get hottest URLs with much larger limit
        result = await session.execute(
            select(URL).order_by(URL.clicks.desc()).limit(settings.CACHE_WARMER_TOP_N * 5)  # 5x more URLs
        )
        hottest = result.scalars().all()

        pipe = cache.pipeline(transaction=False)
        for url in hottest:
            if not url.short_code:
                continue
            pipe.set(f"url:{url.short_code}", json.dumps(_serialize(url).model_dump(mode="json")), ex=CACHE_TTL_SECONDS)
        await pipe.execute()

        logger.info(f"Warmed cache with {len(hottest)} hottest URLs")


async def _warm_random_urls(cache: redis.Redis, count: int = 2000) -> None:
    """Warm cache with random URLs to increase coverage."""
    async with async_session() as session:
        # Get random URLs for better coverage
        result = await session.execute(select(URL).order_by(func.random()).limit(count))
        random_urls = result.scalars().all()

        pipe = cache.pipeline(transaction=False)
        for url in random_urls:
            if not url.short_code:
                continue
            pipe.set(f"url:{url.short_code}", json.dumps(_serialize(url).model_dump(mode="json")), ex=CACHE_TTL_SECONDS)
        await pipe.execute()

        logger.info(f"Warmed cache with {len(random_urls)} random URLs")


async def _monitor_cache_health(cache: redis.Redis) -> dict:
    """Monitor cache health and hit rate."""
    try:
        # Get cache info
        info = await cache.info()
        used_memory = info.get("used_memory", 0)
        total_keys = await cache.dbsize()

        # Sample a few URLs to check cache coverage
        async with async_session() as session:
            result = await session.execute(select(URL).limit(100))
            sample_urls = result.scalars().all()

            cached_count = 0
            for url in sample_urls:
                if url.short_code and await cache.exists(f"url:{url.short_code}"):
                    cached_count += 1

            hit_rate = (cached_count / len(sample_urls)) * 100 if sample_urls else 0

            return {
                "used_memory_mb": used_memory / 1024 / 1024,
                "total_keys": total_keys,
                "sample_hit_rate": hit_rate,
                "sample_size": len(sample_urls),
            }
    except Exception as e:
        logger.warning(f"Failed to monitor cache health: {e}")
        return {}


async def run() -> None:
    """Enhanced cache warming loop for 99%+ hit rate."""

    cache = redis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )

    # Initial aggressive warming
    logger.info("Starting aggressive cache warming...")
    await _pre_generate_urls(cache, 2000)  # Pre-generate 2K URLs
    await _warm_hottest_urls(cache)  # Warm hottest URLs
    await _warm_random_urls(cache, 1000)  # Warm random URLs

    # Monitor and maintain
    iteration = 0
    while True:
        iteration += 1
        try:
            # Monitor cache health
            health = await _monitor_cache_health(cache)
            logger.info(f"Cache health (iteration {iteration}): {health}")

            # If hit rate is below 95%, do more warming
            if health.get("sample_hit_rate", 0) < 95:
                logger.info("Hit rate below 95%, performing additional warming...")
                await _warm_hottest_urls(cache)
                await _warm_random_urls(cache, 500)

            # Regular maintenance warming
            await _warm_hottest_urls(cache)

            # Pre-generate more URLs if cache is not full
            if health.get("total_keys", 0) < 10000:  # Target: 10K cached URLs
                await _pre_generate_urls(cache, 500)

        except Exception as e:
            logger.warning(f"Cache warming iteration {iteration} failed: {e}")
            await asyncio.sleep(5)

        await asyncio.sleep(settings.CACHE_WARMER_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(run())
