"""Pydantic schemas for request/response validation in the URL shortener.

This module defines Pydantic models for API input validation and output serialization,
ensuring type safety and automatic OpenAPI documentation generation.

Schema Hierarchy
=================
::
    URLCreate (Input)
    ├─ url: str (validated URL)
    └─ custom_code: str | None (optional, validated)

    URLResponse (Output)
    ├─ id: int
    ├─ short_code: str
    ├─ original_url: str
    ├─ short_url: str (computed)
    ├─ clicks: int
    ├─ created_at: datetime
    └─ updated_at: datetime

    URLStats (Output)
    └─ Same as URLResponse

    HealthResponse (Output)
    ├─ status: str
    ├─ database: str
    └─ cache: str

How to Use
===========
**Step 1 — Input validation**::
    @app.post("/api/shorten")
    async def shorten_url(payload: URLCreate):
        # payload is already validated
        return await create_short_url(payload.url, payload.custom_code)

**Step 2 — Response serialization**::
    url = await get_url_by_code(short_code)
    return URLResponse(
        id=url.id,
        short_code=url.short_code,
        original_url=url.original_url,
        short_url=f"{settings.BASE_URL}/{url.short_code}",
        clicks=url.clicks,
        created_at=url.created_at,
        updated_at=url.updated_at,
    )

**Step 3 — Error handling**::
    try:
        payload = URLCreate(url=invalid_url)
    except ValidationError as e:
        return JSONResponse(status_code=422, content=e.errors())

Key Behaviours
===============
- URL validation uses the validators library for RFC compliance.
- Custom codes must be alphanumeric and 3-20 characters long.
- All datetime fields are timezone-aware.
- Models are configured for ORM attribute mapping.
- FastAPI automatically generates OpenAPI docs from these schemas.

Classes:
    URLCreate:  Input schema for URL shortening requests.
    URLResponse:  Output schema for created URLs.
    URLStats:  Output schema for URL statistics.
    HealthResponse:  Output schema for health checks.
"""

import datetime

import validators
from pydantic import BaseModel, Field, field_validator

from app.enums import HealthStatus

__all__ = [
    "URLCreate",
    "URLResponse",
    "URLStats",
    "HealthResponse",
    "ClickEvent",
    "CachedURLPayload",
]


class URLCreate(BaseModel):
    url: str
    custom_code: str | None = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not validators.url(v):
            raise ValueError("Invalid URL provided")
        return v

    @field_validator("custom_code")
    @classmethod
    def validate_custom_code(cls, v: str | None) -> str | None:
        if v is not None:
            if len(v) < 3 or len(v) > 20:
                raise ValueError("Custom code must be between 3 and 20 characters")
            if not v.isalnum():
                raise ValueError("Custom code must be alphanumeric")
        return v


class URLResponse(BaseModel):
    id: int
    short_code: str
    original_url: str
    short_url: str
    clicks: int
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}


class URLStats(BaseModel):
    id: int
    short_code: str
    original_url: str
    short_url: str
    clicks: int
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}


class HealthResponse(BaseModel):
    status: HealthStatus
    database: HealthStatus
    cache: HealthStatus


class ClickEvent(BaseModel):
    """Kafka click event payload, keyed by short_code for partition affinity."""

    short_code: str = Field(..., description="Short code being clicked, e.g. 'abc123'")
    delta: int = Field(
        1,
        description="How many clicks to add for this short_code (typically 1).",
        ge=1,
    )


class CachedURLPayload(BaseModel):
    """Redis cache payload for a shortened URL — shared between app and cache warmer."""

    id: int
    short_code: str
    original_url: str
    clicks: int
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}
