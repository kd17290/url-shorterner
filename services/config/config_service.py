"""Configuration service for centralized settings management.

This service provides a singleton pattern for configuration management
with environment variable support and caching for performance.
"""

from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized configuration settings for the URL shortener application.

    This class defines all configuration values with environment variable support.
    Environment variables automatically override defaults.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",  # Ignore extra fields in env
    )

    # Application settings
    APP_NAME: str = "url-shortener"
    APP_ENV: str = "development"
    DEBUG: bool = False
    VERSION: str = "1.0.0"

    # Server settings
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Database settings
    DATABASE_URL: str
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10

    # Redis settings
    REDIS_URL: str
    REDIS_REPLICA_URL: str | None = None
    REDIS_POOL_SIZE: int = 10

    # Redis Sentinel settings
    REDIS_SENTINEL_HOSTS: str = "localhost:26379,localhost:26380,localhost:26381"
    REDIS_SENTINEL_MASTER_NAME: str = "mymaster"
    REDIS_SENTINEL_QUORUM: int = 2

    # Kafka settings
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_TOPIC_URL_EVENTS: str = "url-events"
    KAFKA_TOPIC_CLICK_EVENTS: str = "click_events"
    KAFKA_CLICK_TOPIC: str = "click_events"

    # Keygen service settings
    KEYGEN_SERVICE_URL: str = "http://localhost:8010"
    KEYGEN_PRIMARY_REDIS_URL: str
    KEYGEN_SECONDARY_REDIS_URL: str
    ID_ALLOCATOR_KEY: str = "global_id_allocator"
    ID_BLOCK_SIZE: int = 1000

    # Cache settings
    CACHE_TTL_SECONDS: int = 3600
    CACHE_WARMER_TOP_N: int = 1000
    CACHE_WARMER_INTERVAL_SECONDS: int = 30
    CACHE_LOCK_TTL_SECONDS: int = 3
    CACHE_LOCK_RETRY_COUNT: int = 3
    CACHE_LOCK_RETRY_DELAY_SECONDS: float = 0.05

    # Ingestion settings
    INGESTION_CONSUMER_GROUP: str = "url-shortener-ingestion"
    INGESTION_CONSUMER_NAME: str = "ingestion-consumer-1"
    INGESTION_BATCH_SIZE: int = 100
    INGESTION_FLUSH_INTERVAL_SECONDS: int = 1
    CLICK_BUFFER_KEY_PREFIX: str = "click_buffer"
    CLICK_BUFFER_TTL_SECONDS: int = 300
    CLICK_FLUSH_THRESHOLD: int = 100
    INGESTION_AGG_KEY_PREFIX: str = "ingestion_agg"

    # URL shortening settings
    BASE_URL: str = "http://localhost:8000"
    SHORT_CODE_LENGTH: int = 6
    MAX_URL_LENGTH: int = 2048

    # Metrics and monitoring
    METRICS_PORT: int = 9090
    PROMETHEUS_ENABLED: bool = True

    # ClickHouse settings
    CLICKHOUSE_URL: str = "http://localhost:8123"
    CLICKHOUSE_USERNAME: str = "default"
    CLICKHOUSE_PASSWORD: str = "clickhouse"
    CLICKHOUSE_DATABASE: str = "default"

    # Security settings
    SECRET_KEY: str = "your-secret-key-change-in-production"
    CORS_ORIGINS: list[str] = ["*"]

    # Rate limiting
    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_WINDOW_SECONDS: int = 60


class ConfigurationService:
    """Singleton service for configuration management."""

    _instance: Optional["ConfigurationService"] = None
    _settings: Settings | None = None

    def __new__(cls) -> "ConfigurationService":
        """Implement singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize the configuration service."""
        if not hasattr(self, "_initialized"):
            self._settings = None
            self._initialized = True

    def get_settings(self) -> Settings:
        """Get cached settings instance.

        Returns:
            Settings: Configuration settings instance
        """
        if self._settings is None:
            self._settings = Settings()
        return self._settings

    def reload_settings(self) -> Settings:
        """Reload settings from environment.

        Returns:
            Settings: Fresh configuration settings instance
        """
        # Clear the cache
        self.get_settings.cache_clear()
        # Force recreation
        self._settings = None
        return self.get_settings()

    def validate_settings(self) -> bool:
        """Validate all required settings are present.

        Returns:
            bool: True if all required settings are valid
        """
        try:
            self.get_settings()
            # This will raise ValidationError if required fields are missing
            return True
        except Exception:
            return False


# Global service instance
_config_service = ConfigurationService()


def get_config_service() -> ConfigurationService:
    """Get the singleton configuration service instance.

    Returns:
        ConfigurationService: The configuration service instance
    """
    return _config_service
