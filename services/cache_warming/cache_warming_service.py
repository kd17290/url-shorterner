"""Cache warming service for maintaining high cache hit rates."""

import asyncio
import logging

from sqlalchemy import select

from apps.url_shortener.database import SessionLocal
from apps.url_shortener.dependencies import ServiceManager
from common.models import URL
from common.schemas import CachedURLPayload
from services.config.config_service import get_config_service


class CacheWarmingService:
    """Service for maintaining cache temperature and hit rates."""

    def __init__(self, logger: logging.Logger, service_manager):
        self.logger = logger
        self.service_manager = service_manager
        self.settings = get_config_service().get_settings()
        self.cache_ttl_seconds = 3600

    async def warm_cache(self, target_urls: int = 1000) -> None:
        """Warm up cache with hybrid strategy (popular + newest + high buffer activity).

        High-Scale Strategy:
        - 50% most clicked URLs (PostgreSQL persistent clicks)
        - 30% newest URLs (likely to be accessed soon)
        - 20% URLs with high Redis buffer activity (real-time hot content)
        - Uses database indexes + Redis stats to avoid full scans
        - Accounts for eventual consistency at scale
        """
        self.logger.info(f"Starting high-scale hybrid cache warming for {target_urls} URLs")

        # Calculate split ratios for high scale
        popular_count = int(target_urls * 0.5)  # 50% from PostgreSQL clicks
        newest_count = int(target_urls * 0.3)  # 30% newest URLs
        buffer_count = target_urls - popular_count - newest_count  # 20% from Redis buffers

        async with SessionLocal() as session:
            # Get most clicked URLs (uses clicks index)
            popular_result = await session.execute(select(URL).order_by(URL.clicks.desc()).limit(popular_count))
            popular_urls = popular_result.scalars().all()

            # Get newest URLs (uses created_at index)
            newest_result = await session.execute(select(URL).order_by(URL.created_at.desc()).limit(newest_count))
            newest_urls = newest_result.scalars().all()

            # Get URLs with high Redis buffer activity
            buffer_urls = await self._get_high_buffer_urls(buffer_count, session)

            # Combine and deduplicate results
            all_urls = self._combine_url_lists(list(popular_urls), list(newest_urls), list(buffer_urls))
            self.logger.info(
                f"Selected {len(popular_urls)} popular + {len(newest_urls)} newest + {len(buffer_urls)} buffer URLs"
            )

            # Use Service Manager's Redis writer
            cache = self.service_manager.cache_writer

            for url in all_urls:
                payload = CachedURLPayload.model_validate(url)
                await cache.setex(f"url:{url.short_code}", self.cache_ttl_seconds, payload.model_dump_json())

            self.logger.info(f"Warmed {len(all_urls)} URLs in cache")

    async def _get_high_buffer_urls(self, target_count: int, session) -> list[URL]:
        """Get URLs with high Redis buffer activity.

        This identifies URLs that are getting lots of clicks but haven't
        been persisted to PostgreSQL yet - indicating real-time hot content.
        """
        self.logger.info(f"Scanning Redis buffers for {target_count} high-activity URLs")

        cache = self.service_manager.cache_writer

        # Scan click buffer keys
        buffer_pattern = f"{self.settings.CLICK_BUFFER_KEY_PREFIX}:*"
        buffer_keys = await cache.keys(buffer_pattern)

        # Aggregate buffer counts by short code
        buffer_counts = {}
        for key in buffer_keys:
            try:
                short_code = key.decode().split(":")[-1]
                count_data = await cache.hgetall(key)
                total_count = sum(int(count) for count in count_data.values())
                buffer_counts[short_code] = buffer_counts.get(short_code, 0) + total_count
            except Exception as e:
                self.logger.warning(f"Error processing buffer key {key}: {e}")
                continue

        # Sort by buffer activity and get top URLs
        sorted_buffers = sorted(buffer_counts.items(), key=lambda x: x[1], reverse=True)

        # Get URL objects for high-activity buffers
        high_activity_urls = []
        if sorted_buffers:
            # Get short codes for top buffer activity
            top_short_codes = [code for code, _ in sorted_buffers[:target_count]]

            # Query URLs from PostgreSQL
            result = await session.execute(select(URL).where(URL.short_code.in_(top_short_codes)))
            urls_by_short_code = {url.short_code: url for url in result.scalars().all()}

            # Combine buffer data with URL objects
            for short_code, buffer_count in sorted_buffers[:target_count]:
                if short_code in urls_by_short_code:
                    url = urls_by_short_code[short_code]
                    # Add buffer count to clicks for accurate popularity
                    url.clicks += buffer_count
                    high_activity_urls.append(url)

        self.logger.info(f"Found {len(high_activity_urls)} URLs with high buffer activity")
        return high_activity_urls

    def _combine_url_lists(self, *url_lists: list[URL]) -> list[URL]:
        """Combine multiple URL lists, removing duplicates and maintaining order."""
        seen_short_codes = set()
        combined_urls = []

        for url_list in url_lists:
            for url in url_list:
                if url.short_code not in seen_short_codes:
                    seen_short_codes.add(url.short_code)
                    combined_urls.append(url)

        return combined_urls

    async def pre_generate_urls(self, count: int = 100) -> None:
        """Pre-generate new URLs for cache."""
        self.logger.info(f"Pre-generating {count} new URLs")

        import httpx

        async with httpx.AsyncClient(timeout=5.0) as client:
            for i in range(count):
                try:
                    # Allocate ID range from keygen service
                    response = await client.post(f"{self.settings.KEYGEN_SERVICE_URL}/allocate", json={"size": 1})
                    if response.status_code == 200:
                        data = response.json()
                        self.logger.debug(f"Allocated ID range: {data}")
                except Exception as e:
                    self.logger.warning(f"Failed to allocate ID {i}: {e}")
                    await asyncio.sleep(0.1)  # Brief delay on failure

    async def get_cache_stats(self) -> dict[str, int | str]:
        """Get cache statistics."""
        from services.redis.redis_sentinel_service import RedisRole, get_redis_sentinel_service

        redis_service = get_redis_sentinel_service()
        cache = await redis_service.get_client(role=RedisRole.REPLICA)

        try:
            info = await cache.info("memory")
            return {
                "used_memory": info.get("used_memory", 0),
                "used_memory_human": info.get("used_memory_human", "0B"),
            }
        except Exception as e:
            self.logger.error(f"Failed to get cache stats: {e}")
            return {"used_memory": 0, "used_memory_human": "0B"}

    async def run_continuous_warming(self, interval_seconds: int = 30) -> None:
        """Run continuous cache warming loop."""
        self.logger.info(f"Starting continuous warming every {interval_seconds}s")

        while True:
            try:
                await self.warm_cache()
                await asyncio.sleep(interval_seconds)
            except Exception as e:
                self.logger.error(f"Cache warming error: {e}")
                await asyncio.sleep(interval_seconds)


# Global service instance
_cache_warming_service = None


def get_cache_warming_service(logger: logging.Logger, service_manager: "ServiceManager") -> CacheWarmingService:
    """Get the singleton cache warming service instance.

    Args:
        logger: Logger instance for the service
        service_manager: Service manager for Redis and other dependencies

    Returns:
        CacheWarmingService: The cache warming service instance
    """
    global _cache_warming_service
    if _cache_warming_service is None:
        _cache_warming_service = CacheWarmingService(logger, service_manager)
    return _cache_warming_service
