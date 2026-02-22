"""
Unified Redis Sentinel Service for All Applications

This service provides centralized Redis Sentinel connectivity
for all application services, ensuring consistent high availability
and automatic failover across the entire system.
"""

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import redis.asyncio as redis

from services.config.config_service import get_config_service


class RedisRole(Enum):
    """Redis connection roles."""

    MASTER = "master"
    REPLICA = "replica"
    ANY = "any"


@dataclass
class RedisConnectionStats:
    """Redis connection statistics."""

    total_requests: int = 0
    failed_requests: int = 0
    avg_response_time_ms: float = 0.0
    last_response_time: float = 0.0
    connection_errors: int = 0
    failover_count: int = 0


class RedisSentinelService:
    """
    Unified Redis Sentinel service for all applications.

    Features:
    - Automatic master/replica detection
    - Connection pooling and health monitoring
    - Failover handling
    - Performance metrics
    - Circuit breaker pattern
    """

    _instance: Optional["RedisSentinelService"] = None
    _initialized: bool = False

    def __new__(cls) -> "RedisSentinelService":
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self.settings = get_config_service().get_settings()
            self.logger = self._setup_logger()

            # Redis Sentinel configuration
            self.sentinel = None
            self.master_client = None
            self.replica_clients = []

            # Connection management
            self.last_master_check = 0
            self.master_check_interval = 30  # seconds
            self.current_master_info = None

            # Statistics
            self.stats = RedisConnectionStats()
            self.response_times = []

            # Circuit breaker
            self.circuit_open = False
            self.circuit_open_until = 0
            self.consecutive_failures = 0
            self.max_failures = 5

            self._initialized = True

    def _setup_logger(self) -> logging.Logger:
        """Setup structured logger."""
        logger = logging.getLogger("redis-sentinel-service")
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        return logger

    async def initialize(self) -> None:
        """Initialize Redis Sentinel connections with fallback to direct Redis."""
        try:
            # Check if Sentinel hosts are configured
            if not self.settings.REDIS_SENTINEL_HOSTS or self.settings.REDIS_SENTINEL_HOSTS.strip() == "":
                # Fallback to direct Redis connection
                await self._initialize_direct_redis()
                return

            # Parse sentinel hosts
            sentinel_hosts = [
                (host.split(":")[0], int(host.split(":")[1])) for host in self.settings.REDIS_SENTINEL_HOSTS.split(",")
            ]

            self.logger.info(f"Connecting to Redis Sentinel hosts: {sentinel_hosts}")

            # Create sentinel client
            self.sentinel = redis.Sentinel(
                sentinel_hosts,
                socket_timeout=5,
                socket_connect_timeout=5,
                retry_on_timeout=True,
            )

            # Initialize master connection
            await self._ensure_master_connection()

            # Initialize replica connections
            await self._ensure_replica_connections()

            self.logger.info("Redis Sentinel service initialized successfully")

        except Exception as e:
            self.logger.error(f"Failed to initialize Redis Sentinel: {e}")
            # Try fallback to direct Redis connection
            try:
                await self._initialize_direct_redis()
            except Exception as fallback_error:
                self.logger.error(f"Failed to initialize direct Redis fallback: {fallback_error}")
                raise

    async def _initialize_direct_redis(self) -> None:
        """Initialize direct Redis connection for testing/fallback."""
        self.logger.info("Initializing direct Redis connection")

        # Use direct Redis connection
        self.master_client = redis.from_url(
            self.settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5,
            retry_on_timeout=True,
        )

        # For direct connection, use same client for both master and replica
        self.replica_clients = [self.master_client]

        # Test connection
        await self.master_client.ping()
        self.logger.info("Direct Redis connection established successfully")

    async def _ensure_master_connection(self) -> None:
        """Ensure master connection is available."""
        try:
            if self.master_client:
                await self.master_client.ping()
                return

            # Get master from sentinel
            self.master_client = self.sentinel.master_for(
                self.settings.REDIS_SENTINEL_MASTER_NAME,
                socket_timeout=5,
                decode_responses=True,
            )

            # Test connection
            await self.master_client.ping()
            self.current_master_info = await self.sentinel.sentinel_master(self.settings.REDIS_SENTINEL_MASTER_NAME)

            self.logger.info(f"Connected to Redis master: {self.current_master_info}")
            self._reset_circuit_breaker()

        except Exception as e:
            self.logger.error(f"Failed to connect to Redis master: {e}")
            self._record_failure()
            raise

    async def _ensure_replica_connections(self) -> None:
        """Ensure replica connections are available."""
        try:
            # Clear existing replicas
            for replica in self.replica_clients:
                await replica.close()
            self.replica_clients.clear()

            # Get replicas from sentinel
            replicas = await self.sentinel.sentinel_slaves(self.settings.REDIS_SENTINEL_MASTER_NAME)

            # Connect to healthy replicas
            for replica_info in replicas:
                if replica_info.get("flags", "").startswith("slave"):
                    try:
                        replica_client = self.sentinel.slave_for(
                            self.settings.REDIS_SENTINEL_MASTER_NAME,
                            socket_timeout=5,
                            decode_responses=True,
                        )
                        await replica_client.ping()
                        self.replica_clients.append(replica_client)

                    except Exception as e:
                        self.logger.warning(f"Failed to connect to replica {replica_info}: {e}")

            self.logger.info(f"Connected to {len(self.replica_clients)} Redis replicas")

        except Exception as e:
            self.logger.warning(f"Failed to connect to Redis replicas: {e}")

    async def get_client(self, role: RedisRole = RedisRole.ANY) -> redis.Redis:
        """Get Redis client based on role preference."""
        if self.circuit_open and time.time() < self.circuit_open_until:
            raise RuntimeError("Redis circuit breaker is open")

        try:
            if role == RedisRole.MASTER:
                await self._ensure_master_connection()
                return self.master_client

            elif role == RedisRole.REPLICA:
                # Try to get a healthy replica
                if self.replica_clients:
                    return self.replica_clients[0]
                # Fallback to master
                await self._ensure_master_connection()
                return self.master_client

            else:  # ANY
                # Prefer replicas for reads, master for writes
                if self.replica_clients:
                    return self.replica_clients[0]
                await self._ensure_master_connection()
                return self.master_client

        except Exception:
            self._record_failure()
            raise

    async def execute_with_retry(self, command: str, role: RedisRole = RedisRole.ANY, *args, **kwargs):
        """Execute Redis command with automatic retry and failover."""
        start_time = time.time()

        try:
            client = await self.get_client(role)
            result = await getattr(client, command)(*args, **kwargs)

            # Record success
            self._record_success(time.time() - start_time)
            return result

        except Exception as e:
            self.logger.warning(f"Redis command failed: {command} - {e}")

            # Try failover recovery
            if "master" in str(e).lower() or role == RedisRole.MASTER:
                try:
                    await self._ensure_master_connection()
                    client = await self.get_client(role)
                    result = await getattr(client, command)(*args, **kwargs)
                    self._record_success(time.time() - start_time)
                    return result
                except Exception as e2:
                    self.logger.error(f"Failover recovery failed: {e2}")

            self._record_failure()
            raise

    def _record_success(self, response_time: float) -> None:
        """Record successful operation."""
        self.stats.total_requests += 1
        self.stats.last_response_time = response_time

        # Update response times
        self.response_times.append(response_time * 1000)  # Convert to ms
        if len(self.response_times) > 1000:
            self.response_times.pop(0)

        self.stats.avg_response_time_ms = sum(self.response_times) / len(self.response_times)

        # Reset circuit breaker on success
        if self.consecutive_failures > 0:
            self.consecutive_failures = 0
            if self.circuit_open:
                self.circuit_open = False
                self.logger.info("Redis circuit breaker closed")

    def _record_failure(self) -> None:
        """Record failed operation."""
        self.stats.total_requests += 1
        self.stats.failed_requests += 1
        self.consecutive_failures += 1

        # Open circuit breaker if too many failures
        if self.consecutive_failures >= self.max_failures and not self.circuit_open:
            self.circuit_open = True
            self.circuit_open_until = time.time() + 60  # Open for 60 seconds
            self.logger.warning("Redis circuit breaker opened")

    def _reset_circuit_breaker(self) -> None:
        """Reset circuit breaker."""
        self.consecutive_failures = 0
        self.circuit_open = False
        self.circuit_open_until = 0

    async def get_stats(self) -> dict:
        """Get Redis service statistics."""
        return {
            "total_requests": self.stats.total_requests,
            "failed_requests": self.stats.failed_requests,
            "success_rate": (
                (self.stats.total_requests - self.stats.failed_requests) / max(self.stats.total_requests, 1) * 100
            ),
            "avg_response_time_ms": round(self.stats.avg_response_time_ms, 2),
            "last_response_time_ms": round(self.stats.last_response_time * 1000, 2),
            "connection_errors": self.stats.connection_errors,
            "failover_count": self.stats.failover_count,
            "circuit_breaker_open": self.circuit_open,
            "master_info": self.current_master_info,
            "replica_count": len(self.replica_clients),
            "sentinel_hosts": self.settings.REDIS_SENTINEL_HOSTS,
        }

    async def health_check(self) -> dict:
        """Comprehensive health check."""
        health = {"status": "healthy", "master": False, "replicas": 0, "sentinel": False, "issues": []}

        try:
            # Check master
            if self.master_client:
                await self.master_client.ping()
                health["master"] = True
            else:
                health["issues"].append("No master connection")
        except Exception as e:
            health["issues"].append(f"Master connection failed: {e}")

        try:
            # Check replicas
            healthy_replicas = 0
            for replica in self.replica_clients:
                try:
                    await replica.ping()
                    healthy_replicas += 1
                except Exception:
                    pass
            health["replicas"] = healthy_replicas

            if healthy_replicas == 0 and self.replica_clients:
                health["issues"].append("No healthy replicas")
        except Exception as e:
            health["issues"].append(f"Replica check failed: {e}")

        try:
            # Check sentinel
            if self.sentinel:
                masters = await self.sentinel.sentinel_masters()
                health["sentinel"] = len(masters) > 0
            else:
                health["issues"].append("No sentinel connection")
        except Exception as e:
            health["issues"].append(f"Sentinel connection failed: {e}")

        # Determine overall status
        if health["issues"]:
            health["status"] = "degraded" if health["master"] else "failed"

        return health

    async def cleanup(self) -> None:
        """Cleanup all connections."""
        self.logger.info("Cleaning up Redis Sentinel service...")

        if self.master_client:
            await self.master_client.close()

        for replica in self.replica_clients:
            await replica.close()

        if self.sentinel:
            await self.sentinel.close()

        self.logger.info("Redis Sentinel service cleanup completed")


# Global service instance
_redis_sentinel_service: RedisSentinelService | None = None


def get_redis_sentinel_service() -> RedisSentinelService:
    """Get the singleton Redis Sentinel service instance."""
    global _redis_sentinel_service
    if _redis_sentinel_service is None:
        _redis_sentinel_service = RedisSentinelService()
    return _redis_sentinel_service
