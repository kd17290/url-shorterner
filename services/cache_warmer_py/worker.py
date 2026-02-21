"""Background cache warmer for heavy-read strategy.

Periodically preloads top clicked URLs into Redis to improve cache hit ratio.
"""

import asyncio
import json
import logging

import redis.asyncio as redis
from sqlalchemy import select

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


async def run() -> None:
    """Continuously refresh Redis with hottest URL mappings from OLTP."""

    cache = redis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )

    while True:
        try:
            async with async_session() as session:
                result = await session.execute(
                    select(URL).order_by(URL.clicks.desc()).limit(settings.CACHE_WARMER_TOP_N)
                )
                hottest = result.scalars().all()

            pipe = cache.pipeline(transaction=False)
            for url in hottest:
                if not url.short_code:
                    continue
                pipe.set(
                    f"url:{url.short_code}", json.dumps(_serialize(url).model_dump(mode="json")), ex=CACHE_TTL_SECONDS
                )
            await pipe.execute()
        except Exception:
            logger.warning("cache warmer iteration failed", exc_info=True)
            await asyncio.sleep(2)

        await asyncio.sleep(settings.CACHE_WARMER_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(run())
