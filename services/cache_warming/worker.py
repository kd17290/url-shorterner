"""Cache warming worker entry point."""

import asyncio
import logging
import signal
import sys
from dataclasses import dataclass

import redis.asyncio as redis

from services.cache_warming.cache_warming_service import get_cache_warming_service
from services.config.config_service import get_config_service
from services.redis.redis_sentinel_service import RedisRole, get_redis_sentinel_service


@dataclass
class ServiceManager:
    """Simple service manager for cache warming worker."""

    def __init__(self):
        self.settings = get_config_service().get_settings()
        self.logger = self._setup_logger()
        self.redis_service = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize Redis Sentinel service."""
        if not self._initialized:
            self.redis_service = get_redis_sentinel_service()
            await self.redis_service.initialize()
            self._initialized = True

    def _setup_logger(self) -> logging.Logger:
        """Setup logger."""
        logger = logging.getLogger("cache-warming-service-manager")
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        return logger

    @property
    async def cache_writer(self) -> redis.Redis:
        """Get Redis writer (master)."""
        if self.redis_service is None:
            raise RuntimeError("Service manager not initialized. Call initialize() first.")
        return await self.redis_service.get_client(role=RedisRole.MASTER)


async def main() -> None:
    """Main cache warming worker."""
    settings = get_config_service().get_settings()

    # Setup logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    logger = logging.getLogger("cache-warming-worker")

    logger.info("Starting cache warming worker")

    # Create and initialize service manager
    service_manager = ServiceManager()
    await service_manager.initialize()

    # Get service and run
    service = get_cache_warming_service(logger, service_manager)

    try:
        # Initial warm-up
        await service.warm_cache(settings.CACHE_WARMER_TOP_N)

        # Continuous warming
        await service.run_continuous_warming(settings.CACHE_WARMER_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        logger.info("Cache warming worker stopped by user")
    except Exception as e:
        logger.error(f"Cache warming worker failed: {e}")
        sys.exit(1)


def signal_handler(signum, frame):
    """Handle shutdown signals."""
    print(f"\nReceived signal {signum}, shutting down...")
    sys.exit(0)


if __name__ == "__main__":
    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Run the worker
    asyncio.run(main())
