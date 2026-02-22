#!/usr/bin/env python3
"""
High-Performance Traffic Generator for URL Shortener
Capable of generating 2000+ requests per second with configurable patterns.
"""

import argparse
import asyncio
import logging
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class Metrics:
    """Thread-safe metrics tracking"""

    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    min_latency_ms: float = float("inf")
    created_urls: list[str] = field(default_factory=list)

    def record_request(self, success: bool, latency_ms: float, url: str | None = None):
        self.total_requests += 1

        if success:
            self.successful_requests += 1
            self.total_latency_ms += latency_ms
            self.max_latency_ms = max(self.max_latency_ms, latency_ms)
            self.min_latency_ms = min(self.min_latency_ms, latency_ms)
            if url:
                self.created_urls.append(url)
        else:
            self.failed_requests += 1

    def get_stats(self, elapsed_seconds: float) -> dict[str, Any]:
        success_rate = (self.successful_requests / self.total_requests * 100) if self.total_requests > 0 else 0
        avg_latency = (self.total_latency_ms / self.successful_requests) if self.successful_requests > 0 else 0
        rps = self.total_requests / elapsed_seconds if elapsed_seconds > 0 else 0

        return {
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "success_rate": success_rate,
            "avg_latency_ms": avg_latency,
            "min_latency_ms": self.min_latency_ms if self.min_latency_ms != float("inf") else 0,
            "max_latency_ms": self.max_latency_ms,
            "rps": rps,
            "urls_created": len(self.created_urls),
        }


class TrafficGenerator:
    """High-performance traffic generator"""

    def __init__(self, target_url: str, rps: int, duration: int, pattern: str, workers: int = 100):
        self.target_url = target_url
        self.rps = rps
        self.duration = duration
        self.pattern = pattern
        self.workers = workers
        self.metrics = Metrics()
        self.client = None

    async def __aenter__(self):
        # Create high-performance HTTP client
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            limits=httpx.Limits(max_keepalive_connections=100, max_connections=200),
            http2=False,  # Disable HTTP2 to avoid dependency issues
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.aclose()

    async def warmup(self, warmup_duration: int = 5):
        """Warmup phase to establish connections"""
        logger.info(f"🔥 Warming up for {warmup_duration} seconds...")

        start_time = time.time()
        while time.time() - start_time < warmup_duration:
            # Generate low-intensity traffic during warmup
            tasks = []
            for _ in range(10):
                tasks.append(self.send_request())
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.sleep(0.1)

        logger.info("✅ Warmup completed")

    async def run(self):
        """Main traffic generation loop"""
        logger.info("🚀 Starting traffic generator")
        logger.info(f"📊 Target: {self.rps} RPS for {self.duration} seconds")
        logger.info(f"🎯 Pattern: {self.pattern}")
        logger.info(f"👥 Workers: {self.workers}")

        # Warmup
        await self.warmup()

        # Start metrics reporter
        metrics_task = asyncio.create_task(self.report_metrics())

        # Main traffic generation
        start_time = time.time()
        await self.generate_traffic(start_time)

        # Stop metrics reporter
        metrics_task.cancel()

        # Final report
        self.print_final_report(time.time() - start_time)

    async def report_metrics(self):
        """Real-time metrics reporting"""
        start_time = time.time()

        while True:
            try:
                await asyncio.sleep(5)  # Report every 5 seconds
                elapsed = time.time() - start_time
                stats = self.metrics.get_stats(elapsed)

                logger.info(
                    f"📈 [{elapsed:.0f}s] RPS: {stats['rps']:.1f}, "
                    f"Success: {stats['success_rate']:.1f}%, "
                    f"Avg Latency: {stats['avg_latency_ms']:.2f}ms, "
                    f"Min/Max: {stats['min_latency_ms']:.2f}ms/{stats['max_latency_ms']:.2f}ms"
                )
            except asyncio.CancelledError:
                break

    async def generate_traffic(self, start_time: float):
        """Generate traffic with multiple workers"""
        duration = self.duration
        interval_between_requests = 1.0 / self.rps

        # Create worker tasks
        tasks = []
        for worker_id in range(self.workers):
            task = asyncio.create_task(self.worker_loop(worker_id, start_time, duration, interval_between_requests))
            tasks.append(task)

        # Wait for all workers to complete
        await asyncio.gather(*tasks, return_exceptions=True)

    async def worker_loop(self, worker_id: int, start_time: float, duration: int, interval: float):
        """Individual worker loop"""
        next_request_time = start_time + (random.random() * 0.1)  # Stagger workers

        while time.time() - start_time < duration:
            now = time.time()

            if now >= next_request_time:
                await self.send_request()
                next_request_time = now + interval
            else:
                await asyncio.sleep(next_request_time - now)

    async def send_request(self):
        """Send a single request"""
        start_time = time.time()

        try:
            if self.pattern == "create":
                success, url = await self.send_create_request()
            elif self.pattern == "redirect":
                success = await self.send_redirect_request()
                url = None
            else:  # mixed
                if random.random() < 0.7:  # 70% create, 30% redirect
                    success, url = await self.send_create_request()
                else:
                    success = await self.send_redirect_request()
                    url = None

            latency_ms = (time.time() - start_time) * 1000
            self.metrics.record_request(success, latency_ms, url)

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            logger.error(f"Request error: {e}")
            self.metrics.record_request(False, latency_ms)

    async def send_create_request(self) -> tuple[bool, str]:
        """Send URL creation request"""
        url = f"https://example-{uuid.uuid4()}.com"

        try:
            response = await self.client.post(f"{self.target_url}/api/shorten", json={"url": url})

            if response.status_code == 201:
                data = response.json()
                short_url = data.get("short_url", "")
                return True, short_url
            else:
                logger.warning(f"Create request failed: {response.status_code}")
                return False, None

        except Exception as e:
            logger.error(f"Create request error: {e}")
            return False, None

    async def send_redirect_request(self) -> bool:
        """Send redirect request"""
        if not self.metrics.created_urls:
            return False

        random_url = random.choice(self.metrics.created_urls)

        # Extract short code from URL
        if "/" in random_url:
            short_code = random_url.split("/")[-1]

            try:
                response = await self.client.get(f"{self.target_url}/{short_code}")
                return response.status_code in [200, 307]
            except Exception as e:
                logger.error(f"Redirect request error: {e}")
                return False

        return False

    def print_final_report(self, elapsed: float):
        """Print final performance report"""
        stats = self.metrics.get_stats(elapsed)

        print("\n🎯 📊 🚀 TRAFFIC GENERATION COMPLETE 🚀 📊 🎯\n")
        print("📈 Performance Summary:")
        print(f"   Total Requests: {stats['total_requests']}")
        print(f"   Successful: {stats['successful_requests']}")
        print(f"   Failed: {stats['failed_requests']}")
        print(f"   Success Rate: {stats['success_rate']:.2f}%")
        print(f"   Avg RPS: {stats['rps']:.2f}")
        print(f"   Avg Latency: {stats['avg_latency_ms']:.2f}ms")
        print(f"   Min Latency: {stats['min_latency_ms']:.2f}ms")
        print(f"   Max Latency: {stats['max_latency_ms']:.2f}ms")
        print(f"   URLs Created: {stats['urls_created']}")

        if stats["total_requests"] > 0:
            print("\n🎯 Target vs Actual:")
            print(f"   Target RPS: {self.rps}")
            print(f"   Actual RPS: {stats['rps']:.2f}")
            achievement = (stats["rps"] / self.rps) * 100
            print(f"   Achievement: {achievement:.1f}%")

        print("\n✅ Traffic generation completed successfully!")


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="High-performance traffic generator")
    parser.add_argument("--target", default="http://localhost:8080", help="Target URL")
    parser.add_argument("--rps", type=int, default=2000, help="Target requests per second")
    parser.add_argument("--duration", type=int, default=60, help="Test duration in seconds")
    parser.add_argument("--pattern", choices=["create", "redirect", "mixed"], default="mixed", help="Traffic pattern")
    parser.add_argument("--workers", type=int, default=100, help="Number of worker tasks")
    parser.add_argument("--warmup", type=int, default=5, help="Warmup duration in seconds")

    args = parser.parse_args()

    async with TrafficGenerator(
        target_url=args.target, rps=args.rps, duration=args.duration, pattern=args.pattern, workers=args.workers
    ) as generator:
        await generator.run()


if __name__ == "__main__":
    asyncio.run(main())
