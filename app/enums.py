"""Shared enums for the URL shortener application.

This module defines all status and state enums used across the codebase.
Using enums instead of string literals provides type safety and prevents typos.
"""

from enum import StrEnum

__all__ = ["HealthStatus", "ServiceStatus"]


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
