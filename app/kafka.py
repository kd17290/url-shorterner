"""Kafka producer management for click events."""

import json

from aiokafka import AIOKafkaProducer

from app.config import get_settings
from app.schemas import ClickEvent

__all__ = ["close_kafka", "init_kafka", "publish_click_event"]

settings = get_settings()

_producer: AIOKafkaProducer | None = None


async def init_kafka() -> None:
    global _producer
    if _producer is not None:
        return

    producer = AIOKafkaProducer(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        value_serializer=lambda payload: json.dumps(payload).encode("utf-8"),
    )
    try:
        await producer.start()
        _producer = producer
    except Exception:
        await producer.stop()
        _producer = None


async def close_kafka() -> None:
    global _producer
    if _producer is None:
        return
    await _producer.stop()
    _producer = None


async def publish_click_event(short_code: str, delta: int = 1) -> bool:
    assert isinstance(short_code, str) and short_code, f"short_code must be non-empty str, got {short_code!r}"
    assert isinstance(delta, int) and delta > 0, f"delta must be positive int, got {delta!r}"

    if _producer is None:
        return False

    payload = ClickEvent(short_code=short_code, delta=delta).model_dump(mode="json")
    await _producer.send_and_wait(
        settings.KAFKA_CLICK_TOPIC,
        payload,
        key=short_code.encode("utf-8"),
    )
    return True
