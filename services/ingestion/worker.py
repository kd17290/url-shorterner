"""Separate ingestion consumer service for click events.

Consumes click deltas from Kafka and writes batched updates to OLTP DB,
then ingests analytics rows into ClickHouse.
"""

import asyncio
import datetime
import json
import logging
import os
from collections.abc import Awaitable
from typing import cast as typing_cast  # used for hgetall return type narrowing

import clickhouse_connect
import redis.asyncio as redis
from aiokafka import AIOKafkaConsumer
from clickhouse_connect.driver.client import Client as ClickHouseClient
from prometheus_client import Counter, start_http_server
from pydantic import BaseModel, Field
from redis.asyncio.client import Redis as AsyncRedis
from sqlalchemy import update

from app.config import get_settings
from app.database import async_session
from app.models import URL
from app.schemas import ClickEvent

__all__ = ["run"]

settings = get_settings()
logger = logging.getLogger(__name__)

CLICK_EVENTS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS click_events (
    short_code String,
    delta UInt32,
    event_time DateTime
) ENGINE = MergeTree
ORDER BY (short_code, event_time)
"""

INGESTION_KAFKA_EVENTS_TOTAL = Counter(
    "ingestion_kafka_events_total",
    "Kafka click events consumed by ingestion workers",
)
INGESTION_REDIS_BUFFER_TOTAL = Counter(
    "ingestion_redis_buffer_total",
    "Click deltas buffered into Redis aggregation hash by ingestion workers",
)
INGESTION_DB_UPDATES_TOTAL = Counter(
    "ingestion_db_updates_total",
    "Aggregated short-code updates applied to OLTP DB by ingestion workers",
)
INGESTION_CLICKHOUSE_ROWS_TOTAL = Counter(
    "ingestion_clickhouse_rows_total",
    "Analytics rows inserted into ClickHouse by ingestion workers",
)


class ClickAggregates(BaseModel):
    """Aggregated click deltas ready to be flushed.

    Represents a *batch* of click increments grouped by short code.

    Example::

        {"abc123": 57, "zzz999": 12}

    Meaning:
        - "abc123" received 57 clicks since the last flush
        - "zzz999" received 12 clicks since the last flush
    """

    by_short_code: dict[str, int] = Field(
        default_factory=dict,
        description="Mapping of short_code -> aggregated click delta to apply to Postgres.",
        examples=[{"abc123": 57, "zzz999": 12}],
    )

    @property
    def total_deltas(self) -> int:
        return sum(self.by_short_code.values())


class ClickHouseClickEventRow(BaseModel):
    """One analytics row to be inserted into ClickHouse click_events table."""

    short_code: str
    delta: int
    event_time: datetime.datetime


def _consumer_name() -> str:
    return os.getenv("INGESTION_CONSUMER_NAME", settings.INGESTION_CONSUMER_NAME)


def _agg_hash_key() -> str:
    return f"{settings.INGESTION_AGG_KEY_PREFIX}:{_consumer_name()}"


async def _buffer_batch_to_redis(
    client: AsyncRedis,
    batch: list[ClickEvent],
) -> bool:
    aggregates = ClickAggregates()
    for click_event in batch:
        if not click_event.short_code:
            continue
        aggregates.by_short_code[click_event.short_code] = (
            aggregates.by_short_code.get(click_event.short_code, 0) + click_event.delta
        )

    if not aggregates.by_short_code:
        return False

    INGESTION_REDIS_BUFFER_TOTAL.inc(aggregates.total_deltas)

    pipe = client.pipeline(transaction=False)
    key = _agg_hash_key()
    for short_code, delta in aggregates.by_short_code.items():
        pipe.hincrby(key, short_code, delta)
    await pipe.execute()
    return True


async def _process_batch(
    client: AsyncRedis,
    clickhouse_client: ClickHouseClient,
    aggregated: ClickAggregates,
) -> None:
    analytics_rows: list[ClickHouseClickEventRow] = [
        ClickHouseClickEventRow(
            short_code=short_code,
            delta=delta,
            event_time=datetime.datetime.utcnow(),
        )
        for short_code, delta in aggregated.by_short_code.items()
    ]

    if not aggregated.by_short_code:
        return

    async with async_session() as session:
        for short_code, delta in aggregated.by_short_code.items():
            await session.execute(update(URL).where(URL.short_code == short_code).values(clicks=URL.clicks + delta))
            INGESTION_DB_UPDATES_TOTAL.inc()
        await session.commit()

    pipe = client.pipeline(transaction=True)
    for short_code, delta in aggregated.by_short_code.items():
        buffer_key = f"{settings.CLICK_BUFFER_KEY_PREFIX}:{short_code}"
        pipe.decrby(buffer_key, delta)
        pipe.delete(f"url:{short_code}")
    await pipe.execute()

    clickhouse_client.command(CLICK_EVENTS_TABLE_DDL)
    clickhouse_client.insert(
        table="click_events",
        data=[[row.short_code, row.delta, row.event_time] for row in analytics_rows],
        column_names=["short_code", "delta", "event_time"],
    )
    INGESTION_CLICKHOUSE_ROWS_TOTAL.inc(len(analytics_rows))


async def _flush_aggregates(
    client: AsyncRedis,
    clickhouse_client: ClickHouseClient,
) -> None:
    key = _agg_hash_key()
    raw = await typing_cast(Awaitable[dict[str, str]], client.hgetall(key))
    if not raw:
        return

    aggregated = ClickAggregates(
        by_short_code={short_code: int(delta) for short_code, delta in raw.items() if int(delta) > 0}
    )
    if not aggregated.by_short_code:
        await client.delete(key)
        return

    await _process_batch(client, clickhouse_client, aggregated)
    await client.delete(key)


async def _process_redis_fallback_stream(client: AsyncRedis) -> None:
    streams = await client.xreadgroup(
        groupname=settings.INGESTION_CONSUMER_GROUP,
        consumername=_consumer_name(),
        streams={settings.CLICK_STREAM_KEY: ">"},
        count=settings.INGESTION_BATCH_SIZE,
        block=settings.INGESTION_BLOCK_MS,
    )
    if not streams:
        return

    for _, messages in streams:
        fallback_batch: list[ClickEvent] = []
        for message_id, payload in messages:
            try:
                fallback_batch.append(ClickEvent.model_validate(payload))
            except Exception:
                logger.warning("invalid fallback click payload", exc_info=True)
            await client.xack(
                settings.CLICK_STREAM_KEY,
                settings.INGESTION_CONSUMER_GROUP,
                message_id,
            )
        if fallback_batch:
            await _buffer_batch_to_redis(client, fallback_batch)


async def _ensure_fallback_group(client: AsyncRedis) -> None:
    try:
        await client.xgroup_create(
            settings.CLICK_STREAM_KEY,
            settings.INGESTION_CONSUMER_GROUP,
            id="0",
            mkstream=True,
        )
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def run() -> None:
    metrics_port = int(os.getenv("INGESTION_METRICS_PORT", "9200"))
    start_http_server(metrics_port)

    client = redis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )
    clickhouse_client = clickhouse_connect.get_client(
        host=settings.CLICKHOUSE_URL.replace("http://", "").split(":")[0],
        port=int(settings.CLICKHOUSE_URL.rsplit(":", maxsplit=1)[1]),
        username=settings.CLICKHOUSE_USERNAME,
        password=settings.CLICKHOUSE_PASSWORD,
        database=settings.CLICKHOUSE_DATABASE,
    )
    clickhouse_client.command(CLICK_EVENTS_TABLE_DDL)

    consumer = AIOKafkaConsumer(
        settings.KAFKA_CLICK_TOPIC,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=settings.INGESTION_CONSUMER_GROUP,
        value_deserializer=lambda payload: json.loads(payload.decode("utf-8")),
        client_id=_consumer_name(),
    )

    await _ensure_fallback_group(client)
    await consumer.start()
    last_flush = asyncio.get_running_loop().time()

    while True:
        try:
            records = await consumer.getmany(
                timeout_ms=settings.INGESTION_BLOCK_MS, max_records=settings.INGESTION_BATCH_SIZE
            )
            batch: list[ClickEvent] = []
            for topic_partition_records in records.values():
                for record in topic_partition_records:
                    try:
                        batch.append(ClickEvent.model_validate(record.value))
                    except Exception:
                        logger.warning("invalid kafka click payload", exc_info=True)

            if batch:
                INGESTION_KAFKA_EVENTS_TOTAL.inc(len(batch))
                await _buffer_batch_to_redis(client, batch)

            await _process_redis_fallback_stream(client)

            now = asyncio.get_running_loop().time()
            if now - last_flush >= settings.INGESTION_FLUSH_INTERVAL_SECONDS:
                await _flush_aggregates(client, clickhouse_client)
                last_flush = now
        except Exception:
            logger.warning("ingestion loop iteration failed", exc_info=True)
            await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(run())
