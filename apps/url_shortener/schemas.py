"""Re-exports common schemas for the URL shortener app.

This module simply re-exports the schemas defined in common.schemas to provide
a clean import path for the app layer.
"""

from common.schemas import CachedURLPayload, ClickEvent, HealthResponse, URLCreate, URLResponse, URLStats

__all__ = [
    "CachedURLPayload",
    "ClickEvent",
    "HealthResponse",
    "URLCreate",
    "URLResponse",
    "URLStats",
]
