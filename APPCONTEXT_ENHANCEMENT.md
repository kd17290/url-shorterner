# AppContext Enhancement Summary

## Current AppContext Components

The unified `AppContext` now includes:

1. **db**: Async database session for write operations
2. **cache_write**: Primary Redis client for write operations  
3. **cache_read**: Read-only Redis client for read operations
4. **logger**: Structured logger for application logging
5. **settings**: Application configuration settings

## Suggested Additional Components

### 1. Request Context
```python
from fastapi import Request
from time import time
from uuid import uuid4

class RequestContext(NamedTuple):
    request_id: str
    start_time: float
    user_agent: str
    ip_address: str
```

### 2. Metrics/Telemetry
```python
from prometheus_client import Counter, Histogram, Gauge

class MetricsContext(NamedTuple):
    http_requests_total: Counter
    http_request_duration: Histogram
    active_connections: Gauge
    cache_operations: Counter
```

### 3. Security Context
```python
from typing import Optional
from datetime import datetime

class SecurityContext(NamedTuple):
    rate_limiter: "RateLimiter"
    auth_token: Optional[str]
    permissions: List[str]
    session_id: Optional[str]
```

### 4. Feature Flags
```python
from typing import Dict, Any

class FeatureFlags(NamedTuple):
    flags: Dict[str, bool]
    get_flag: Callable[[str], bool]
    is_enabled: Callable[[str], bool]
```

### 5. External Service Clients
```python
from httpx import AsyncClient
import aiohttp

class ServiceClients(NamedTuple):
    keygen_client: AsyncClient
    analytics_client: AsyncClient
    notification_client: AsyncClient
```

## Enhanced AppContext Example

```python
class AppContext(NamedTuple):
    # Core dependencies
    db: AsyncSession
    cache_write: redis.Redis
    cache_read: redis.Redis
    
    # Application context
    logger: logging.Logger
    settings: Settings
    request: RequestContext
    
    # Observability
    metrics: MetricsContext
    
    # Security
    security: SecurityContext
    
    # Feature management
    features: FeatureFlags
    
    # External services
    services: ServiceClients
```

## Benefits of Enhanced Context

1. **Centralized Dependencies**: All request-scoped dependencies in one place
2. **Type Safety**: NamedTuple provides compile-time type checking
3. **Testability**: Easy to mock individual components
4. **Performance**: Single dependency injection point
5. **Consistency**: Standardized access pattern across all endpoints
6. **Observability**: Built-in logging, metrics, and tracing
7. **Security**: Centralized authentication and authorization
8. **Feature Management**: Easy feature flag integration

## Implementation Priority

1. **High Priority**: Request context (request_id, timing)
2. **Medium Priority**: Metrics/telemetry integration
3. **Low Priority**: Feature flags and external service clients

## Usage Example

```python
@router.get("/api/shorten")
async def shorten_url(
    payload: URLCreate,
    ctx: AppContext = Depends(get_app_context),
) -> URLResponse:
    # Structured logging with context
    ctx.logger.info(
        "URL shortening requested",
        extra={
            "request_id": ctx.request.request_id,
            "url": payload.url,
            "user_agent": ctx.request.user_agent
        }
    )
    
    # Metrics tracking
    with ctx.metrics.http_request_duration.time():
        # Business logic
        url = await service.create_short_url(payload, ctx.db, ctx.cache_write)
        
        # Feature flag check
        if ctx.features.is_enabled("advanced_analytics"):
            await ctx.services.analytics_client.track_event("url_created")
    
    return URLResponse.from_model(url, ctx.settings.BASE_URL)
```

This enhanced approach provides a comprehensive, maintainable, and scalable dependency injection pattern.
