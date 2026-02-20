"""Database configuration and session management for the URL shortener.

This module provides SQLAlchemy async engine setup, session management,
and database lifecycle operations using PostgreSQL as the backend.

Flow Diagram — Database Operations
=================================
::
    ┌─────────────┐
    │  Application│
    │  Request    │
    └──────┬──────┘
           ▼
    ┌─────────────┐
    │ get_db()     │
    │ dependency  │
    └──────┬──────┘
           ▼
    ┌─────────────┐
    │ Create async │
    │ session     │
    └──────┬──────┘
           ▼
    ┌─────────────┐
    │ Yield to     │
    │ request     │
    │ handler     │
    └──────┬──────┘
           ▼
    ┌─────────────┐
    │ Auto-close   │
    │ (finally)    │
    └─────────────┘

How to Use
===========
**Step 1 — Initialize on startup**::
    await init_db()  # Creates tables

**Step 2 — Use in FastAPI endpoints**::
    @app.get("/urls")
    async def get_urls(db: AsyncSession = Depends(get_db)):
        result = await db.execute(select(URL))
        return result.scalars().all()

**Step 3 — Cleanup on shutdown**::
    await close_db()

Key Behaviours
===============
- Async sessions are automatically closed after each request.
- Connection pooling is configured for production workloads.
- Tables are created automatically on application startup.
- Engine is properly disposed on application shutdown.

Classes:
    Base:  SQLAlchemy declarative base for all models.

Functions:
    get_db():  FastAPI dependency for database sessions.
    init_db():  Creates all tables on startup.
    close_db():  Disposes the engine on shutdown.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

__all__ = ["Base", "get_db", "init_db", "close_db"]

settings = get_settings()

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=(settings.APP_ENV == "development"),
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
)

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    await engine.dispose()
