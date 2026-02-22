"""Click event ingestion worker entry point."""

import asyncio
import logging
import signal
import sys

from services.config.config_service import get_config_service
from services.ingestion.ingestion_service import get_ingestion_service


async def main() -> None:
    """Main ingestion worker."""
    settings = get_config_service().get_settings()

    # Setup logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    logger = logging.getLogger(f"ingestion-{settings.INGESTION_CONSUMER_NAME}")

    logger.info(f"Starting ingestion worker: {settings.INGESTION_CONSUMER_NAME}")

    # Get service and run
    service = get_ingestion_service(logger)

    try:
        # Run continuous ingestion
        await service.run_continuous_ingestion(settings.INGESTION_FLUSH_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        logger.info("Ingestion worker stopped by user")
    except Exception as e:
        logger.error(f"Ingestion worker failed: {e}")
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
