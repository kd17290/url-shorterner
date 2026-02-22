"""Click event ingestion service for analytics processing."""

import asyncio
import json
import logging

from sqlalchemy import update

from apps.url_shortener.database import async_session
from common.models import URL
from services.config.config_service import get_config_service
from services.redis.redis_sentinel_service import get_redis_sentinel_service


class IngestionService:
    """Service for processing click events and updating analytics."""

    def __init__(self, logger: logging.Logger):
        self.settings = get_config_service().get_settings()
        self.logger = logger
        self.consumer_group = self.settings.INGESTION_CONSUMER_GROUP
        self.consumer_name = self.settings.INGESTION_CONSUMER_NAME
        self.batch_size = self.settings.INGESTION_BATCH_SIZE

    async def process_click_buffer(self) -> int:
        """Process buffered click events from Redis."""
        processed = 0

        async with async_session() as session:
            # Get Redis Sentinel service
            redis_service = get_redis_sentinel_service()
            cache = await redis_service.get_client(role="master")

            try:
                # Scan for click buffer keys
                pattern = f"{self.settings.CLICK_BUFFER_KEY_PREFIX}:*"
                keys = await cache.keys(pattern)

                if not keys:
                    return 0

                # Process each buffer
                for key in keys:
                    try:
                        # Get all clicks in this buffer
                        clicks_data = await cache.hgetall(key)

                        if not clicks_data:
                            await cache.delete(key)
                            continue

                        # Extract short code from key
                        short_code = key.decode().split(":")[-1]

                        # Update database with total clicks
                        total_clicks = sum(int(count) for count in clicks_data.values())

                        await session.execute(
                            update(URL).where(URL.short_code == short_code).values(clicks=URL.clicks + total_clicks)
                        )
                        await session.commit()

                        # Delete processed buffer
                        await cache.delete(key)

                        processed += total_clicks
                        self.logger.debug(f"Processed {total_clicks} clicks for {short_code}")

                    except Exception as e:
                        self.logger.error(f"Error processing buffer {key}: {e}")
                        continue

                self.logger.info(f"Processed {processed} total clicks from {len(keys)} buffers")
                return processed

            except Exception as e:
                self.logger.error(f"Error in click buffer processing: {e}")
                return 0

    async def aggregate_clicks(self, time_window_seconds: int = 60) -> dict[str, int]:
        """Aggregate clicks by time window."""
        redis_service = get_redis_sentinel_service()
        cache = await redis_service.get_client(role="replica")

        try:
            # Get aggregation keys for the time window
            pattern = f"{self.settings.INGESTION_AGG_KEY_PREFIX}:*"
            keys = await cache.keys(pattern)

            aggregates = {}
            for key in keys:
                try:
                    agg_data = await cache.get(key)
                    if agg_data:
                        data = json.loads(agg_data)
                        aggregates[key.decode()] = data.get("click_count", 0)
                except Exception as e:
                    self.logger.warning(f"Error reading aggregation {key}: {e}")
                    continue

            return aggregates

        except Exception as e:
            self.logger.error(f"Error aggregating clicks: {e}")
            return {}

    async def cleanup_old_buffers(self, max_age_seconds: int = 300) -> int:
        """Clean up old click buffers."""
        redis_service = get_redis_sentinel_service()
        cache = await redis_service.get_client(role="master")
        cleaned = 0

        try:
            pattern = f"{self.settings.CLICK_BUFFER_KEY_PREFIX}:*"
            keys = await cache.keys(pattern)

            for key in keys:
                try:
                    ttl = await cache.ttl(key)
                    if ttl == -1 or ttl > max_age_seconds:
                        await cache.delete(key)
                        cleaned += 1
                except Exception as e:
                    self.logger.warning(f"Error cleaning buffer {key}: {e}")
                    continue

            if cleaned > 0:
                self.logger.info(f"Cleaned up {cleaned} old buffers")

            return cleaned

        except Exception as e:
            self.logger.error(f"Error cleaning buffers: {e}")
            return 0

    async def get_ingestion_stats(self) -> dict[str, int]:
        """Get ingestion service statistics."""
        redis_service = get_redis_sentinel_service()
        cache = await redis_service.get_client(role="replica")

        try:
            # Count active buffers
            pattern = f"{self.settings.CLICK_BUFFER_KEY_PREFIX}:*"
            buffer_count = len(await cache.keys(pattern))

            # Count aggregations
            agg_pattern = f"{self.settings.INGESTION_AGG_KEY_PREFIX}:*"
            agg_count = len(await cache.keys(agg_pattern))

            return {
                "active_buffers": buffer_count,
                "active_aggregations": agg_count,
            }

        except Exception as e:
            self.logger.error(f"Error getting stats: {e}")
            return {"active_buffers": 0, "active_aggregations": 0}

    async def run_continuous_ingestion(self, interval_seconds: int = 1) -> None:
        """Run continuous ingestion loop."""
        self.logger.info(f"Starting continuous ingestion every {interval_seconds}s")

        while True:
            try:
                # Process click buffers
                processed = await self.process_click_buffer()

                # Cleanup old buffers periodically
                if processed > 0:
                    await self.cleanup_old_buffers()

                await asyncio.sleep(interval_seconds)

            except Exception as e:
                self.logger.error(f"Ingestion loop error: {e}")
                await asyncio.sleep(interval_seconds)


# Global service instance
_ingestion_service = None


def get_ingestion_service(logger: logging.Logger) -> IngestionService:
    """Get the singleton ingestion service instance.

    Args:
        logger: Logger instance for the service

    Returns:
        IngestionService: The ingestion service instance
    """
    global _ingestion_service
    if _ingestion_service is None:
        _ingestion_service = IngestionService(logger)
    return _ingestion_service
