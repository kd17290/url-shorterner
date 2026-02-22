#!/usr/bin/env python3
"""
Comprehensive Load Testing Script for URL Shortener
Tests high concurrency and performance under various scenarios
"""

import argparse
import asyncio
import json
import logging
import random
import statistics
import time
from datetime import datetime
from typing import Any

import aiohttp

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class LoadTester:
    def __init__(self, base_url: str, max_concurrent: int = 1000):
        self.base_url = base_url.rstrip("/")
        self.max_concurrent = max_concurrent
        self.session = None
        self.stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "response_times": [],
            "errors": {},
            "created_urls": [],
            "accessed_urls": [],
        }

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30), connector=aiohttp.TCPConnector(limit=self.max_concurrent)
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def create_url(self, url_data: dict[str, Any]) -> dict[str, Any]:
        """Create a short URL"""
        start_time = time.perf_counter()
        try:
            async with self.session.post(f"{self.base_url}/api/shorten", json=url_data) as response:
                response_time = (time.perf_counter() - start_time) * 1000
                self.stats["response_times"].append(response_time)

                if response.status == 200:
                    result = await response.json()
                    self.stats["successful_requests"] += 1
                    self.stats["created_urls"].append(result["short_code"])
                    return result
                else:
                    self.stats["failed_requests"] += 1
                    error_text = await response.text()
                    error_key = f"HTTP {response.status}"
                    self.stats["errors"][error_key] = self.stats["errors"].get(error_key, 0) + 1
                    logger.error(f"Create URL failed: {response.status} - {error_text}")
                    return None
        except Exception as e:
            response_time = (time.perf_counter() - start_time) * 1000
            self.stats["response_times"].append(response_time)
            self.stats["failed_requests"] += 1
            error_key = str(e)
            self.stats["errors"][error_key] = self.stats["errors"].get(error_key, 0) + 1
            logger.error(f"Create URL error: {e}")
            return None
        finally:
            self.stats["total_requests"] += 1

    async def access_url(self, short_code: str) -> bool:
        """Access a short URL"""
        start_time = time.perf_counter()
        try:
            async with self.session.get(f"{self.base_url}/api/{short_code}", allow_redirects=False) as response:
                response_time = (time.perf_counter() - start_time) * 1000
                self.stats["response_times"].append(response_time)

                if response.status in [200, 301, 302]:
                    self.stats["successful_requests"] += 1
                    self.stats["accessed_urls"].append(short_code)
                    return True
                else:
                    self.stats["failed_requests"] += 1
                    error_key = f"HTTP {response.status}"
                    self.stats["errors"][error_key] = self.stats["errors"].get(error_key, 0) + 1
                    logger.error(f"Access URL failed: {response.status}")
                    return False
        except Exception as e:
            response_time = (time.perf_counter() - start_time) * 1000
            self.stats["response_times"].append(response_time)
            self.stats["failed_requests"] += 1
            error_key = str(e)
            self.stats["errors"][error_key] = self.stats["errors"].get(error_key, 0) + 1
            logger.error(f"Access URL error: {e}")
            return False
        finally:
            self.stats["total_requests"] += 1

    async def get_stats(self) -> dict[str, Any]:
        """Get service statistics"""
        try:
            async with self.session.get(f"{self.base_url}/api/stats") as response:
                if response.status == 200:
                    return await response.json()
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
        return {}


async def warmup_phase(tester: LoadTester, duration: int = 30):
    """Warmup phase with moderate load"""
    logger.info(f"🔥 Starting warmup phase for {duration} seconds...")

    end_time = time.time() + duration
    tasks = []

    while time.time() < end_time:
        # Create URLs during warmup
        url_data = {"url": f"https://warmup-{random.randint(1000, 9999)}.example.com", "custom_code": None}
        task = asyncio.create_task(tester.create_url(url_data))
        tasks.append(task)

        # Control warmup rate (moderate)
        await asyncio.sleep(0.1)

        # Limit concurrent tasks
        if len(tasks) >= 50:
            await asyncio.gather(*tasks)
            tasks = []

    # Complete remaining tasks
    if tasks:
        await asyncio.gather(*tasks)

    logger.info("✅ Warmup phase completed")


async def burst_test(tester: LoadTester, rps: int, duration: int):
    """Burst test with high RPS"""
    logger.info(f"💥 Starting burst test: {rps} RPS for {duration} seconds...")

    end_time = time.time() + duration
    interval = 1.0 / rps
    tasks = []

    while time.time() < end_time:
        start_time = time.perf_counter()

        # Mix of operations (70% reads, 30% writes)
        if random.random() < 0.3 and tester.stats["created_urls"]:
            # Read operation
            short_code = random.choice(tester.stats["created_urls"])
            task = asyncio.create_task(tester.access_url(short_code))
        else:
            # Write operation
            url_data = {"url": f"https://burst-{random.randint(1000, 9999)}.example.com", "custom_code": None}
            task = asyncio.create_task(tester.create_url(url_data))

        tasks.append(task)

        # Rate limiting
        elapsed = time.perf_counter() - start_time
        if elapsed < interval:
            await asyncio.sleep(interval - elapsed)

        # Limit concurrent tasks
        if len(tasks) >= tester.max_concurrent:
            await asyncio.gather(*tasks[:100])
            tasks = tasks[100:]

    # Complete remaining tasks
    if tasks:
        await asyncio.gather(*tasks)

    logger.info("✅ Burst test completed")


async def sustained_load(tester: LoadTester, rps: int, duration: int):
    """Sustained load test"""
    logger.info(f"⏱️ Starting sustained load: {rps} RPS for {duration} seconds...")

    end_time = time.time() + duration
    interval = 1.0 / rps
    tasks = []

    while time.time() < end_time:
        start_time = time.perf_counter()

        # Realistic mix (80% reads, 20% writes)
        if random.random() < 0.2 and tester.stats["created_urls"]:
            # Read operation
            short_code = random.choice(tester.stats["created_urls"])
            task = asyncio.create_task(tester.access_url(short_code))
        else:
            # Write operation
            url_data = {"url": f"https://sustained-{random.randint(1000, 9999)}.example.com", "custom_code": None}
            task = asyncio.create_task(tester.create_url(url_data))

        tasks.append(task)

        # Rate limiting
        elapsed = time.perf_counter() - start_time
        if elapsed < interval:
            await asyncio.sleep(interval - elapsed)

        # Limit concurrent tasks
        if len(tasks) >= tester.max_concurrent:
            await asyncio.gather(*tasks[:100])
            tasks = tasks[100:]

    # Complete remaining tasks
    if tasks:
        await asyncio.gather(*tasks)

    logger.info("✅ Sustained load completed")


async def stress_test(tester: LoadTester, max_rps: int, duration: int):
    """Stress test with increasing load"""
    logger.info(f"🚀 Starting stress test: up to {max_rps} RPS for {duration} seconds...")

    end_time = time.time() + duration
    current_rps = 100
    increment_time = duration / 10  # Increase RPS every 1/10 of duration

    while time.time() < end_time:
        # Calculate current target RPS
        elapsed = time.time() + duration - end_time
        if elapsed > increment_time:
            current_rps = min(current_rps + 100, max_rps)
            logger.info(f"📈 Increasing to {current_rps} RPS...")

        # Run burst at current RPS for 10 seconds
        await burst_test(tester, current_rps, 10)

        # Brief pause between increments
        await asyncio.sleep(2)

    logger.info("✅ Stress test completed")


def print_statistics(stats: dict[str, Any], test_duration: float):
    """Print comprehensive statistics"""
    print("\n" + "=" * 80)
    print("📊 COMPREHENSIVE LOAD TEST RESULTS")
    print("=" * 80)

    # Basic stats
    total_requests = stats["total_requests"]
    successful_requests = stats["successful_requests"]
    failed_requests = stats["failed_requests"]
    success_rate = (successful_requests / total_requests * 100) if total_requests > 0 else 0
    actual_rps = total_requests / test_duration if test_duration > 0 else 0

    print("\n🎯 PERFORMANCE METRICS:")
    print(f"  Total Requests: {total_requests:,}")
    print(f"  Successful: {successful_requests:,} ({success_rate:.2f}%)")
    print(f"  Failed: {failed_requests:,} ({100-success_rate:.2f}%)")
    print(f"  Actual RPS: {actual_rps:.1f}")
    print(f"  Test Duration: {test_duration:.1f}s")

    # Response time stats
    response_times = stats["response_times"]
    if response_times:
        print("\n⏱️ RESPONSE TIME ANALYSIS:")
        print(f"  Average: {statistics.mean(response_times):.2f}ms")
        print(f"  Median: {statistics.median(response_times):.2f}ms")
        print(f"  P95: {statistics.quantiles(response_times, n=20)[18]:.2f}ms")
        print(f"  P99: {statistics.quantiles(response_times, n=100)[98]:.2f}ms")
        print(f"  Min: {min(response_times):.2f}ms")
        print(f"  Max: {max(response_times):.2f}ms")

    # Error analysis
    if stats["errors"]:
        print("\n❌ ERROR ANALYSIS:")
        for error, count in sorted(stats["errors"].items(), key=lambda x: x[1], reverse=True):
            percentage = (count / failed_requests * 100) if failed_requests > 0 else 0
            print(f"  {error}: {count} ({percentage:.1f}%)")

    # URL operations
    print("\n🔗 URL OPERATIONS:")
    print(f"  URLs Created: {len(stats['created_urls'])}")
    print(f"  URLs Accessed: {len(stats['accessed_urls'])}")

    # Performance rating
    print("\n🏆 PERFORMANCE RATING:")
    if success_rate >= 99 and actual_rps >= 1000:
        print("  🌟 EXCELLENT - Production Ready!")
    elif success_rate >= 95 and actual_rps >= 500:
        print("  ✅ GOOD - Near Production Ready")
    elif success_rate >= 90 and actual_rps >= 200:
        print("  ⚠️ MODERATE - Needs Optimization")
    else:
        print("  ❌ POOR - Significant Issues Found")

    print("=" * 80)


async def main():
    parser = argparse.ArgumentParser(description="Comprehensive Load Testing for URL Shortener")
    parser.add_argument("--target", default="http://localhost:8080", help="Target URL")
    parser.add_argument("--max-concurrent", type=int, default=1000, help="Maximum concurrent requests")
    parser.add_argument("--warmup", type=int, default=30, help="Warmup duration in seconds")
    parser.add_argument("--burst-rps", type=int, default=500, help="Burst test RPS")
    parser.add_argument("--burst-duration", type=int, default=60, help="Burst test duration")
    parser.add_argument("--sustained-rps", type=int, default=200, help="Sustained load RPS")
    parser.add_argument("--sustained-duration", type=int, default=300, help="Sustained load duration")
    parser.add_argument("--stress-max-rps", type=int, default=2000, help="Stress test max RPS")
    parser.add_argument("--stress-duration", type=int, default=300, help="Stress test duration")
    parser.add_argument("--skip-warmup", action="store_true", help="Skip warmup phase")
    parser.add_argument("--skip-burst", action="store_true", help="Skip burst test")
    parser.add_argument("--skip-sustained", action="store_true", help="Skip sustained load")
    parser.add_argument("--skip-stress", action="store_true", help="Skip stress test")

    args = parser.parse_args()

    logger.info(f"🚀 Starting comprehensive load test against {args.target}")
    logger.info(f"⚙️ Configuration: Max Concurrent={args.max_concurrent}")

    start_time = time.perf_counter()

    async with LoadTester(args.target, args.max_concurrent) as tester:
        # Warmup phase
        if not args.skip_warmup:
            await warmup_phase(tester, args.warmup)

        # Burst test
        if not args.skip_burst:
            await burst_test(tester, args.burst_rps, args.burst_duration)

        # Sustained load
        if not args.skip_sustained:
            await sustained_load(tester, args.sustained_rps, args.sustained_duration)

        # Stress test
        if not args.skip_stress:
            await stress_test(tester, args.stress_max_rps, args.stress_duration)

        # Get final service stats
        service_stats = await tester.get_stats()
        if service_stats:
            logger.info(f"📈 Service Stats: {json.dumps(service_stats, indent=2)}")

    total_duration = time.perf_counter() - start_time
    print_statistics(tester.stats, total_duration)

    # Save results to file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_file = f"load_test_results_{timestamp}.json"

    results = {
        "timestamp": timestamp,
        "test_duration": total_duration,
        "configuration": vars(args),
        "statistics": tester.stats,
        "service_stats": service_stats,
    }

    with open(results_file, "w") as f:
        json.dump(results, f, indent=2)

    logger.info(f"💾 Results saved to {results_file}")


if __name__ == "__main__":
    asyncio.run(main())
