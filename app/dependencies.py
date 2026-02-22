"""Optimized dependency injection with singleton service manager.

This module provides a centralized way to inject database and cache dependencies
with consistent naming across all API endpoints, using a singleton pattern for
shared resources to minimize per-request overhead.
"""

import logging
from dataclasses import dataclass
from typing import Optional

import redis.asyncio as redis
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.redis import get_redis, get_redis_read
from app.url_service import URLShorteningService


# ============================================================================
# SINGLETON SERVICE MANAGER
# ============================================================================

class ServiceManager:
    """Singleton service manager for shared resources.
    
    This class manages shared resources that don't need to be created per request,
    significantly reducing per-request overhead and improving performance.
    """
    
    _instance: Optional['ServiceManager'] = None
    _initialized: bool = False
    
    def __new__(cls) -> 'ServiceManager':
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
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        return logger
    
    async def _setup_redis_writer(self) -> redis.Redis:
        """Setup Redis writer once."""
        return redis.from_url(
            self.settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True
        )
    
    async def _setup_redis_reader(self) -> redis.Redis:
        """Setup Redis reader once."""
        # Use replica URL if available, otherwise fall back to main Redis
        redis_url = getattr(self.settings, 'REDIS_REPLICA_URL', None) or self.settings.REDIS_URL
        return redis.from_url(
            redis_url,
            encoding="utf-8",
            decode_responses=True
        )
    
    async def cleanup(self) -> None:
        """Cleanup shared resources at shutdown."""
        if hasattr(self, 'cache_writer'):
            await self.cache_writer.close()
        if hasattr(self, 'cache_reader'):
            await self.cache_reader.close()
        self._initialized = False


# Global singleton instance
_service_manager = ServiceManager()


# ============================================================================
# LIGHTWEIGHT REQUEST CONTEXT
# ============================================================================

@dataclass
class RequestContext:
    """Lightweight context per request with only request-specific data.
    
    Only the database session varies per request. All other resources
    are shared through the singleton service manager.
    """
    database: AsyncSession
    service_manager: ServiceManager
    
    @property
    def cache_writer(self) -> redis.Redis:
        """Get shared Redis writer."""
        return self.service_manager.cache_writer
    
    @property
    def cache_reader(self) -> redis.Redis:
        """Get shared Redis reader."""
        return self.service_manager.cache_reader
    
    @property
    def logger(self) -> logging.Logger:
        """Get shared logger."""
        return self.service_manager.logger
    
    @property
    def settings(self):
        """Get shared settings."""
        return self.service_manager.settings


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
    db: AsyncSession = Depends(get_db),
    manager: ServiceManager = Depends(get_service_manager),
) -> RequestContext:
    """Lightweight request context with shared resources.
    
    Args:
        db: Database session (only per-request resource)
        manager: Singleton service manager with shared resources
        
    Returns:
        RequestContext: Lightweight context for the request
    """
    return RequestContext(database=db, service_manager=manager)


def get_url_service(ctx: RequestContext = Depends(get_request_context)) -> URLShorteningService:
    """Create URL service with optimized context.
    
    Args:
        ctx: Request context with shared resources
        
    Returns:
        URLShorteningService: Service instance with embedded context
    """
    return URLShorteningService(
        database=ctx.database,
        cache_writer=ctx.cache_writer,
        cache_reader=ctx.cache_reader,
        logger=ctx.logger,
        settings=ctx.settings
    )
