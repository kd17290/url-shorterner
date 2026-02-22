"""Optimized dependency injection with singleton service manager.

This module provides a centralized way to inject database and cache dependencies
with consistent naming across all API endpoints, using a singleton pattern for
shared resources to minimize per-request overhead.
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

import redis.asyncio as redis
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.url_service import URLShorteningService


# ============================================================================
# SINGLETON SERVICE MANAGER
# ============================================================================


class ServiceManager:
    """Singleton service manager for shared resources.

    This class manages shared resources that don't need to be created per request,
    significantly reducing per-request overhead and improving performance.
    """

    _instance: Optional["ServiceManager"] = None
    _initialized: bool = False

    def __new__(cls) -> "ServiceManager":
        """Implement singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def initialize(self) -> None:
        """Initialize shared resources once at startup."""
        if not self._initialized:
            self.settings = get_settings()
            self.logger = self._setup_logger()
            self.cache_writer = await self._setup_redis_writer()
            self.cache_reader = await self._setup_redis_reader()
            self._initialized = True

    def _setup_logger(self) -> logging.Logger:
        """Setup logger once."""
        logger = logging.getLogger("urlshortener")
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        return logger

    async def _setup_redis_writer(self) -> redis.Redis:
        """Setup Redis writer once."""
        return redis.from_url(self.settings.REDIS_URL, encoding="utf-8", decode_responses=True)

    async def _setup_redis_reader(self) -> redis.Redis:
        """Setup Redis reader once."""
        # Use replica URL if available, otherwise fall back to main Redis
        redis_url = getattr(self.settings, "REDIS_REPLICA_URL", None) or self.settings.REDIS_URL
        return redis.from_url(redis_url, encoding="utf-8", decode_responses=True)

    async def cleanup(self) -> None:
        """Cleanup shared resources at shutdown."""
        if hasattr(self, "cache_writer"):
            await self.cache_writer.close()
        if hasattr(self, "cache_reader"):
            await self.cache_reader.close()
        self._initialized = False


# Global singleton instance
_service_manager = ServiceManager()


# ============================================================================
# LIGHTWEIGHT REQUEST CONTEXT
# ============================================================================


@dataclass
class RequestContext:
    """Comprehensive request context with tracking and observability.

    This context provides complete request lifecycle tracking with
    unique identifiers, timing information, and shared resource access.

    Attributes:
        database: Async database session (only per-request resource)
        service_manager: Singleton service manager with shared resources
        request_id: Unique identifier for this request
        trace_id: Correlation ID for distributed tracing
        user_agent: Client user agent string
        client_ip: Client IP address
        start_time: Request start timestamp
        parent_request_id: Parent request ID for nested calls
        tags: Request tags for categorization
    """

    database: AsyncSession
    service_manager: ServiceManager
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: Optional[str] = None
    user_agent: Optional[str] = None
    client_ip: Optional[str] = None
    start_time: float = field(default_factory=lambda: time.time())
    parent_request_id: Optional[str] = None
    tags: list[str] = field(default_factory=list)

    @property
    def cache_writer(self) -> redis.Redis:
        """Get shared Redis writer."""
        return self.service_manager.cache_writer

    @property
    def cache_reader(self) -> redis.Redis:
        """Get shared Redis reader."""
        return self.service_manager.cache_reader

    @property
    def logger(self) -> logging.LoggerAdapter:
        """Get shared logger with request context."""
        logger = self.service_manager.logger
        # Add request context to all log messages
        return self._add_context_to_logger(logger)

    @property
    def settings(self):
        """Get shared settings."""
        return self.service_manager.settings

    def _add_context_to_logger(self, logger: logging.Logger) -> logging.LoggerAdapter:
        """Add request context to logger for structured logging."""
        # Create a logger adapter that adds context to all messages
        return logging.LoggerAdapter(
            logger,
            {
                "request_id": self.request_id,
                "trace_id": self.trace_id or self.request_id,
                "client_ip": self.client_ip,
                "user_agent": self.user_agent,
                "tags": ",".join(self.tags),
            },
        )

    def add_tag(self, tag: str) -> None:
        """Add a tag to the request context."""
        if tag not in self.tags:
            self.tags.append(tag)

    def get_duration(self) -> float:
        """Get request duration in milliseconds."""
        return (time.time() - self.start_time) * 1000

    def get_context_headers(self) -> dict[str, str]:
        """Get context headers for downstream services."""
        headers = {
            "X-Request-ID": self.request_id,
            "X-Trace-ID": self.trace_id or self.request_id,
        }
        if self.parent_request_id:
            headers["X-Parent-Request-ID"] = self.parent_request_id
        return headers


# ============================================================================
# DEPENDENCY FUNCTIONS
# ============================================================================


async def get_service_manager() -> ServiceManager:
    """Get the singleton service manager.

    Returns:
        ServiceManager: Initialized singleton service manager
    """
    if not _service_manager._initialized:
        await _service_manager.initialize()
    return _service_manager


async def get_request_context(
    request: Request,
    db: AsyncSession = Depends(get_db),
    manager: ServiceManager = Depends(get_service_manager),
) -> RequestContext:
    """Comprehensive request context with tracking and observability.

    Args:
        db: Database session (only per-request resource)
        manager: Singleton service manager with shared resources
        request: FastAPI Request object for extracting client info

    Returns:
        RequestContext: Comprehensive context for the request
    """
    # Extract client information from request
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    # Extract trace ID from headers (for distributed tracing)
    trace_id = request.headers.get("x-trace-id") or request.headers.get("x-trace-id")
    parent_request_id = request.headers.get("x-parent-request-id")

    return RequestContext(
        database=db,
        service_manager=manager,
        trace_id=trace_id,
        user_agent=user_agent,
        client_ip=client_ip,
        parent_request_id=parent_request_id,
    )


def get_url_service(ctx: RequestContext = Depends(get_request_context)) -> URLShorteningService:
    """Create URL service with comprehensive context using factory pattern.

    Args:
        ctx: Request context with shared resources and tracking

    Returns:
        URLShorteningService: Service instance with embedded context
    """
    return URLShorteningService.from_context(ctx)
