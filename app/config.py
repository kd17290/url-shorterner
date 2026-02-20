"""Configuration management for the URL shortener application.

This module provides centralized configuration management using Pydantic BaseSettings
with environment variable support and caching for performance.

Flow Diagram — get_settings()
=============================
::
    ┌─────────────┐
    │  Call get_  │
    │  settings() │
    └──────┬──────┘
           ▼
    ┌─────────────┐
    │ Check cache  │
    │ (lru_cache)  │
    └──────┬──────┘
    HIT?  │
    ┌─────┴─────┐
    │ NO         │ YES
    ▼            ▼
┌─────────┐  ┌─────────┐
│ Create  │  │ Return  │
│ Settings│  │ cached  │
│ instance│  │ value   │
└─────────┘  └─────────┘

How to Use
===========
**Step 1 — Import**::
    from app.config import get_settings

**Step 2 — Get settings**::
    settings = get_settings()
    db_url = settings.DATABASE_URL

**Step 3 — Access values**::
    print(f"App: {settings.APP_NAME}")
    print(f"Environment: {settings.APP_ENV}")

Key Behaviours
===============
- Settings are cached after first access for performance.
- Environment variables override defaults automatically.
- Missing required environment variables raise ValidationError.

Classes:
    Settings:  Pydantic model for all configuration values.

"""

__all__ = ["Settings", "get_settings"]

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "url-shortener"
    APP_ENV: str = "development"
    BASE_URL: str = "http://localhost:8080"

    # PostgreSQL base vars (used by compose and available in env files)
    POSTGRES_USER: str = "urlshortener"
    POSTGRES_PASSWORD: str = "urlshortener"
    POSTGRES_DB: str = "urlshortener"

    # PostgreSQL
    DATABASE_URL: str = "postgresql+asyncpg://urlshortener:urlshortener@db:5432/urlshortener"

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"
    REDIS_REPLICA_URL: str = "redis://redis-replica:6379/0"

    # Short URL config
    SHORT_CODE_LENGTH: int = 8
    ID_ALLOCATOR_KEY: str = "id_allocator:url"
    ID_BLOCK_SIZE: int = 1000
    KEYGEN_SERVICE_URL: str = "http://keygen:8010"
    KEYGEN_PRIMARY_REDIS_URL: str = "redis://keygen-redis-primary:6379/0"
    KEYGEN_SECONDARY_REDIS_URL: str = "redis://keygen-redis-secondary:6379/0"

    # Click buffering / async-ish ingestion tuning
    CLICK_BUFFER_KEY_PREFIX: str = "click_buffer"
    CLICK_BUFFER_TTL_SECONDS: int = 300
    CLICK_FLUSH_THRESHOLD: int = 100
    CLICK_STREAM_KEY: str = "click_events"
    INGESTION_CONSUMER_GROUP: str = "click_ingestion_group"
    INGESTION_CONSUMER_NAME: str = "ingestion-consumer-1"
    INGESTION_BATCH_SIZE: int = 500
    INGESTION_BLOCK_MS: int = 1000
    INGESTION_FLUSH_INTERVAL_SECONDS: int = 5
    INGESTION_AGG_KEY_PREFIX: str = "ingestion_agg"

    # Kafka queue
    KAFKA_BOOTSTRAP_SERVERS: str = "kafka:9092"
    KAFKA_CLICK_TOPIC: str = "click_events"

    # ClickHouse analytics ingestion
    CLICKHOUSE_URL: str = "http://clickhouse:8123"
    CLICKHOUSE_USERNAME: str = "default"
    CLICKHOUSE_PASSWORD: str = "clickhouse"
    CLICKHOUSE_DATABASE: str = "default"

    # Background cache warmer
    CACHE_WARMER_INTERVAL_SECONDS: int = 30
    CACHE_WARMER_TOP_N: int = 5000

    # Cache stampede protection
    CACHE_LOCK_TTL_SECONDS: int = 3
    CACHE_LOCK_RETRY_COUNT: int = 3
    CACHE_LOCK_RETRY_DELAY_SECONDS: float = 0.05

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
    )


@lru_cache()
def get_settings() -> Settings:
    return Settings()
