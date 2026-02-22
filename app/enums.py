"""Shared enums for the URL shortener application.

This module defines all status and state enums used across the codebase.
Using enums instead of string literals provides type safety and prevents typos.
"""

from enum import StrEnum

__all__ = ["HealthStatus", "ServiceStatus", "RequestStatus", "CacheStatus"]


class HealthStatus(StrEnum):
    """Health check status values."""

    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"

    @classmethod
    def from_str(cls, value: str) -> "HealthStatus":
        """Safely parse from string, falling back to UNHEALTHY for unknown values."""
        try:
            return cls(value)
        except ValueError:
            return cls.UNHEALTHY


class ServiceStatus(StrEnum):
    """Service operational status values."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

    @classmethod
    def from_str(cls, value: str) -> "ServiceStatus":
        """Safely parse from string, falling back to FAILED for unknown values."""
        try:
            return cls(value)
        except ValueError:
            return cls.FAILED


class RequestStatus(StrEnum):
    """Request status values for metrics and logging."""

    SUCCESS = "success"
    VALIDATION_ERROR = "validation_error"
    ERROR = "error"
    NOT_FOUND = "not_found"

    @classmethod
    def from_str(cls, value: str) -> "RequestStatus":
        """Safely parse from string, falling back to ERROR for unknown values."""
        try:
            return cls(value)
        except ValueError:
            return cls.ERROR


class CacheStatus(StrEnum):
    """Cache status values for metrics."""

    HIT = "true"
    MISS = "false"

    @classmethod
    def from_str(cls, value: str) -> "CacheStatus":
        """Safely parse from string, falling back to MISS for unknown values."""
        try:
            return cls(value)
        except ValueError:
            return cls.MISS
