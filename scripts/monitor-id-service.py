#!/usr/bin/env python3
"""
ID Allocation Service Monitoring Dashboard

Real-time monitoring of:
- Redis Sentinel cluster health
- PostgreSQL fallback status
- Allocation metrics and performance
- Distributed locks status
- Failover events
"""

import asyncio
import time
from datetime import datetime

import aiohttp
import asyncpg
import redis.asyncio as redis


class IDServiceMonitor:
    """Comprehensive monitoring for ID Allocation Service."""

    def __init__(self):
        self.base_url = "http://localhost:8010"
        self.redis_sentinel_hosts = ["localhost:26379", "localhost:26380", "localhost:26381"]
        self.postgres_url = "postgresql://urlshortener:urlshortener@localhost:5432/urlshortener"

    async def get_service_metrics(self) -> dict:
        """Get metrics from ID allocation service."""
        try:
            async with aiohttp.ClientSession() as session, session.get(f"{self.base_url}/metrics") as response:
                return await response.json()
        except Exception as e:
            return {"error": str(e)}

    async def get_redis_sentinel_status(self) -> dict:
        """Get Redis Sentinel cluster status."""
        sentinel_status = {}

        for i, host in enumerate(self.redis_sentinel_hosts, 1):
            try:
                host, port = host.split(":")
                sentinel = redis.Sentinel([(host, int(port))], socket_timeout=2)

                # Get master info
                master_info = await sentinel.sentinel_master("mymaster")

                # Get replica info
                replicas = await sentinel.sentinel_slaves("mymaster")

                sentinel_status[f"sentinel_{i}"] = {
                    "host": host,
                    "port": port,
                    "master": master_info,
                    "replicas": replicas,
                    "status": "connected",
                }

            except Exception as e:
                sentinel_status[f"sentinel_{i}"] = {
                    "host": host.split(":")[0],
                    "port": host.split(":")[1],
                    "status": "error",
                    "error": str(e),
                }

        return sentinel_status

    async def get_postgresql_status(self) -> dict:
        """Get PostgreSQL sequence status."""
        try:
            conn = await asyncpg.connect(self.postgres_url)

            # Get sequence info
            seq_info = await conn.fetchrow(
                """
                SELECT
                    last_value,
                    log_cnt,
                    is_called
                FROM pg_sequences
                WHERE sequencename = 'url_id_sequence'
            """
            )

            # Get database stats
            db_stats = await conn.fetchrow(
                """
                SELECT
                    datname,
                    numbackends,
                    xact_commit,
                    xact_rollback,
                    blks_read,
                    blks_hit,
                    tup_returned,
                    tup_fetched,
                    tup_inserted,
                    tup_updated,
                    tup_deleted
                FROM pg_stat_database
                WHERE datname = current_database()
            """
            )

            await conn.close()

            return {
                "sequence": dict(seq_info) if seq_info else None,
                "database": dict(db_stats) if db_stats else None,
                "status": "connected",
            }

        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def test_allocation_performance(self, allocations: int = 100) -> dict:
        """Test allocation performance."""
        try:
            async with aiohttp.ClientSession() as session:
                start_time = time.time()
                successful = 0
                failed = 0
                response_times = []

                for _ in range(allocations):
                    req_start = time.time()

                    try:
                        async with session.post(f"{self.base_url}/allocate", json={"size": 10}) as response:
                            if response.status == 200:
                                successful += 1
                            else:
                                failed += 1

                            response_time = (time.time() - req_start) * 1000
                            response_times.append(response_time)

                    except Exception:
                        failed += 1

                total_time = time.time() - start_time

                return {
                    "total_allocations": allocations,
                    "successful": successful,
                    "failed": failed,
                    "success_rate": (successful / allocations) * 100,
                    "total_time": total_time,
                    "allocations_per_second": allocations / total_time,
                    "avg_response_time": sum(response_times) / len(response_times) if response_times else 0,
                    "p95_response_time": (
                        sorted(response_times)[int(len(response_times) * 0.95)] if response_times else 0
                    ),
                    "status": "completed",
                }

        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def print_dashboard(self):
        """Print comprehensive monitoring dashboard."""
        while True:
            # Clear screen
            print("\033[2J\033[H")

            # Header
            print("🔍 ID ALLOCATION SERVICE MONITORING DASHBOARD")
            print("=" * 60)
            print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print()

            # Service Metrics
            print("📊 SERVICE METRICS")
            print("-" * 30)
            metrics = await self.get_service_metrics()

            if "error" not in metrics:
                print(f"Overall Health: {metrics.get('overall_health', 'unknown')}")
                print(f"Redis Health: {metrics.get('redis_health', 'unknown')}")
                print(f"PostgreSQL Health: {metrics.get('postgresql_health', 'unknown')}")
                print(f"Active Locks: {metrics.get('active_locks', 0)}")

                metrics_data = metrics.get("metrics", {})
                print(f"Total Allocations: {metrics_data.get('total_allocations', 0):,}")
                print(f"Redis Allocations: {metrics_data.get('redis_allocations', 0):,}")
                print(f"PostgreSQL Allocations: {metrics_data.get('postgresql_allocations', 0):,}")
                print(f"Avg Response Time: {metrics_data.get('avg_allocation_time_ms', 0):.2f}ms")
            else:
                print(f"❌ Service Error: {metrics['error']}")

            print()

            # Redis Sentinel Status
            print("🛡️ REDIS SENTINEL CLUSTER")
            print("-" * 30)
            sentinel_status = await self.get_redis_sentinel_status()

            for name, status in sentinel_status.items():
                status_icon = "✅" if status["status"] == "connected" else "❌"
                print(f"{status_icon} {name}: {status['host']}:{status['port']}")

                if status["status"] == "connected" and "master" in status:
                    master = status["master"]
                    print(f"    Master: {master.get('ip', 'unknown')}:{master.get('port', 'unknown')}")
                    print(f"    Replicas: {len(status.get('replicas', []))}")

            print()

            # PostgreSQL Status
            print("🐘 POSTGRESQL FALLBACK")
            print("-" * 30)
            pg_status = await self.get_postgresql_status()

            if pg_status["status"] == "connected":
                print("✅ PostgreSQL: Connected")

                if pg_status.get("sequence"):
                    seq = pg_status["sequence"]
                    print(f"    Last Value: {seq.get('last_value', 'unknown')}")
                    print(f"    Is Called: {seq.get('is_called', 'unknown')}")

                if pg_status.get("database"):
                    db = pg_status["database"]
                    print(f"    Active Connections: {db.get('numbackends', 0)}")
                    print(f"    Transactions Committed: {db.get('xact_commit', 0):,}")
            else:
                print(f"❌ PostgreSQL: {pg_status.get('error', 'unknown')}")

            print()

            # Performance Test
            print("⚡ PERFORMANCE TEST (last 100 allocations)")
            print("-" * 40)
            perf = await self.test_allocation_performance(100)

            if perf["status"] == "completed":
                print(f"Success Rate: {perf['success_rate']:.1f}%")
                print(f"Allocations/sec: {perf['allocations_per_second']:.1f}")
                print(f"Avg Response: {perf['avg_response_time']:.1f}ms")
                print(f"P95 Response: {perf['p95_response_time']:.1f}ms")
            else:
                print(f"❌ Performance Test: {perf.get('error', 'unknown')}")

            print()
            print("Press Ctrl+C to exit...")

            # Wait before next update
            await asyncio.sleep(5)


async def main():
    """Main monitoring loop."""
    monitor = IDServiceMonitor()

    try:
        await monitor.print_dashboard()
    except KeyboardInterrupt:
        print("\n👋 Monitoring stopped by user")
    except Exception as e:
        print(f"\n❌ Monitoring error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
