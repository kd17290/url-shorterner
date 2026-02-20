"""SQLAlchemy ORM models for the URL shortener application.

This module defines the database schema using SQLAlchemy declarative models
with proper indexing and timestamp management for URL mappings.

Data Model Layout
=================
::
    urls table
    ├─ id (SERIAL PRIMARY KEY)
    ├─ short_code (VARCHAR(20) UNIQUE, INDEXED)
    ├─ original_url (TEXT NOT NULL)
    ├─ clicks (INTEGER DEFAULT 0)
    ├─ created_at (TIMESTAMPTZ, DEFAULT NOW())
    └─ updated_at (TIMESTAMPTZ, DEFAULT NOW(), ON UPDATE)

Class Relationship Diagram
=========================
::
    URL
    ├─ id: int (PK)
    ├─ short_code: str (UNIQUE, INDEXED)
    ├─ original_url: str
    ├─ clicks: int
    ├─ created_at: datetime
    └─ updated_at: datetime

How to Use
===========
**Step 1 — Import**::
    from app.models import URL

**Step 2 — Create a new URL**::
    url = URL(short_code="abc123", original_url="https://example.com")
    db.add(url)
    await db.commit()

**Step 3 — Query URLs**::
    result = await db.execute(select(URL).where(URL.short_code == "abc123"))
    url = result.scalar_one_or_none()

**Step 4 — Update clicks**::
    url.clicks += 1
    db.add(url)
    await db.commit()

Key Behaviours
===============
- short_code is indexed for fast lookups during redirects.
- created_at and updated_at are automatically managed by PostgreSQL.
- clicks counter starts at 0 and increments on each redirect.
- original_url stores the full target URL without length limits.

Classes:
    URL:  Represents a shortened URL mapping with click tracking.
"""

import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

__all__ = ["URL"]


class URL(Base):
    __tablename__ = "urls"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    short_code: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    original_url: Mapped[str] = mapped_column(Text, nullable=False)
    clicks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<URL(id={self.id}, short_code='{self.short_code}', clicks={self.clicks})>"
