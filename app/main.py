"""FastAPI application entry point for the URL shortener service.

This module configures and initializes the FastAPI application with middleware,
lifecycle management, and route registration for the URL shortening service.

Application Lifecycle Diagram
===========================
::
    ┌─────────────┐
    │  uvicorn    │
    │  startup    │
    └──────┬──────┘
           ▼
    ┌─────────────┐
    │ Create FastAPI│
    │ app instance │
    └──────┬──────┘
           ▼
    ┌─────────────┐
    │ Add CORS    │
    │ middleware  │
    └──────┬────┘
           ▼
    ┌─────────────┐
    │ Include     │
    │ routes      │
    └──────┬──────┘
           ▼
    ┌─────────────┐
    │ lifespan()  │
    │ startup:    │
    │ init_db()   │
    └──────┬──────┘
           ▼
    ┌─────────────┐
    │ Serve HTTP  │
    │ requests   │
    └──────┬──────┘
           ▼
    ┌─────────────┐
    │ lifespan()  │
    │ shutdown:   │
    │ close_db()  │
    │ close_redis()│
    └─────────────┘

How to Use
===========
**Step 1 — Run with uvicorn**::
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

**Step 2 — Access interactive docs**::
    # Swagger UI
    http://localhost:8000/docs

    # ReDoc
    http://localhost:8000/redoc

**Step 3 — Make API calls**::
    # Health check
    curl http://localhost:8000/health

    # Shorten URL
    curl -X POST http://localhost:8000/api/shorten \
         -H "Content-Type: application/json" \
         -d '{"url": "https://example.com"}'

Key Behaviours
===============
- Database tables are created automatically on startup.
- Redis connection is established lazily on first use.
- CORS is enabled for all origins (configure for production).
- Application gracefully shuts down database and Redis connections.
- Auto-generated OpenAPI documentation available at /docs and /redoc.

Configuration:
    The app uses environment variables for configuration.
    See app/config.py for all available settings.

Routes:
    All API routes are defined in app/routes.py and included here.
"""

__all__ = ["app"]

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from app.config import get_settings
from app.database import close_db, init_db
from app.dependencies import _service_manager
from app.kafka import close_kafka, init_kafka
from app.redis import close_redis
from app.routes import router

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup
    await init_db()
    await init_kafka()
    await _service_manager.initialize()
    yield
    # Shutdown
    await _service_manager.cleanup()
    await close_kafka()
    await close_db()
    await close_redis()


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="A modern, scalable URL shortener API",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=False,
    should_respect_env_var=False,
).instrument(app).expose(app)

app.include_router(router)
