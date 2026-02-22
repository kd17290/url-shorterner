#!/usr/bin/env python3
"""
High-Traffic Generator for URL Shortener

Generates realistic traffic patterns to test the robust architecture.
"""

import asyncio
import random
import time
from collections import defaultdict
from dataclasses import dataclass

import aiohttp


@dataclass
class TrafficConfig:
    """Traffic generation configuration."""

    base_url: str = "http://localhost:8080"
    duration_seconds: int = 60
    concurrent_writers: int = 20
    concurrent_readers: int = 100
    concurrent_celebrities: int = 50
    celebrity_pool_size: int = 10
    warmup_urls: int = 1000
    timeout_seconds: int = 5


class TrafficGenerator:
    """High-traffic generator for URL shortener testing."""

    def __init__(self, config: TrafficConfig):
        self.config = config
        self.client = None
        self.warmup_urls = []
        self.stats = defaultdict(int)
        self.response_times = []

    async def warmup(self):
        """Warm up with URLs for testing."""
        print(f"Warming up {self.config.warmup_urls} URLs...")

        for i in range(self.config.warmup_urls):
            try:
                original_url = f"https://warmup-{i}-{random.randint(1000, 9999)}.example.com"
                response = await self.client.post(
                    f"{self.config.base_url}/api/shorten",
                    json={"url": original_url},
                    timeout=self.config.timeout_seconds,
                )
                if response.status_code == 201:
                    data = response.json()
                    self.warmup_urls.append(data["short_code"])

                if i % 100 == 0:
                    print(f"Warmup progress: {i}/{self.config.warmup_urls}")

            except Exception as e:
                print(f"Warmup error: {e}")

        print(f"Warmup complete: {len(self.warmup_urls)} URLs created")

    async def writer_task(self, task_id: int, results: list):
        """Writer task: Create new URLs."""
        start_time = time.time()
        requests = 0
        errors = 0
        response_times = []

        while time.time() - start_time < self.config.duration_seconds:
            try:
                original_url = f"https://traffic-{task_id}-{requests}-{random.randint(1000, 9999)}.example.com"
                req_start = time.time()

                response = await self.client.post(
                    f"{self.config.base_url}/api/shorten",
                    json={"url": original_url},
                    timeout=self.config.timeout_seconds,
                )

                response_time = time.time() - req_start
                response_times.append(response_time * 1000)
                requests += 1

                if response.status_code != 201:
                    errors += 1

            except Exception:
                errors += 1

        results.append(
            {"task": f"writer-{task_id}", "requests": requests, "errors": errors, "response_times": response_times}
        )

    async def reader_task(self, task_id: int, results: list):
        """Reader task: Access random warmup URLs."""
        if not self.warmup_urls:
            results.append({"task": f"reader-{task_id}", "requests": 0, "errors": 0, "response_times": []})
            return

        start_time = time.time()
        requests = 0
        errors = 0
        response_times = []

        while time.time() - start_time < self.config.duration_seconds:
            try:
                short_code = random.choice(self.warmup_urls)
                req_start = time.time()

                response = await self.client.get(
                    f"{self.config.base_url}/{short_code}", follow_redirects=False, timeout=self.config.timeout_seconds
                )

                response_time = time.time() - req_start
                response_times.append(response_time * 1000)
                requests += 1

                if response.status_code not in [301, 302]:
                    errors += 1

            except Exception:
                errors += 1

        results.append(
            {"task": f"reader-{task_id}", "requests": requests, "errors": errors, "response_times": response_times}
        )

    async def celebrity_task(self, task_id: int, results: list):
        """Celebrity task: High traffic to popular URLs."""
        if not self.warmup_urls:
            results.append({"task": f"celebrity-{task_id}", "requests": 0, "errors": 0, "response_times": []})
            return

        # Use first few URLs as "celebrity" URLs
        celebrity_urls = self.warmup_urls[: self.config.celebrity_pool_size]

        start_time = time.time()
        requests = 0
        errors = 0
        response_times = []

        while time.time() - start_time < self.config.duration_seconds:
            try:
                short_code = random.choice(celebrity_urls)
                req_start = time.time()

                response = await self.client.get(
                    f"{self.config.base_url}/{short_code}", follow_redirects=False, timeout=self.config.timeout_seconds
                )

                response_time = time.time() - req_start
                response_times.append(response_time * 1000)
                requests += 1

                if response.status_code not in [301, 302]:
                    errors += 1

            except Exception:
                errors += 1

        results.append(
            {"task": f"celebrity-{task_id}", "requests": requests, "errors": errors, "response_times": response_times}
        )

    def calculate_stats(self, results: list[dict]) -> dict:
        """Calculate traffic statistics."""
        total_requests = sum(r["requests"] for r in results)
        total_errors = sum(r["errors"] for r in results)
        all_response_times = []

        for r in results:
            all_response_times.extend(r["response_times"])

        if all_response_times:
            all_response_times.sort()
            avg_response_time = sum(all_response_times) / len(all_response_times)
            p95_index = int(0.95 * len(all_response_times))
            p99_index = int(0.99 * len(all_response_times))
            p95_response_time = all_response_times[p95_index]
            p99_response_time = all_response_times[p99_index]
        else:
            avg_response_time = p95_response_time = p99_response_time = 0

        return {
            "requests": total_requests,
            "errors": total_errors,
            "avg_response_time_ms": avg_response_time,
            "p95_response_time_ms": p95_response_time,
            "p99_response_time_ms": p99_response_time,
        }

    async def run_traffic_test(self):
        """Run complete traffic test."""
        print("Starting traffic test with config:")
        print(f"  Duration: {self.config.duration_seconds}s per phase")
        print(f"  Timeout: {self.config.timeout_seconds}s")
        print(f"  Writers: {self.config.concurrent_writers}")
        print(f"  Readers: {self.config.concurrent_readers}")
        print(f"  Celebrities: {self.config.concurrent_celebrities}")
        print(f"  Celebrity Pool: {self.config.celebrity_pool_size}")
        print(f"  Warmup URLs: {self.config.warmup_urls}")
        print()

        # Warmup phase
        await self.warmup()

        print("Starting traffic generation phases...")

        # Writer phase
        print(f"\n=== WRITER PHASE ({self.config.concurrent_writers} workers) ===")
        writer_results = []
        writer_tasks = [
            asyncio.create_task(self.writer_task(i, writer_results)) for i in range(self.config.concurrent_writers)
        ]
        await asyncio.gather(*writer_tasks)
        writer_stats = self.calculate_stats(writer_results)

        # Reader phase
        print(f"\n=== READER PHASE ({self.config.concurrent_readers} workers) ===")
        reader_results = []
        reader_tasks = [
            asyncio.create_task(self.reader_task(i, reader_results)) for i in range(self.config.concurrent_readers)
        ]
        await asyncio.gather(*reader_tasks)
        reader_stats = self.calculate_stats(reader_results)

        # Celebrity phase
        print(f"\n=== CELEBRITY PHASE ({self.config.concurrent_celebrities} workers) ===")
        celebrity_results = []
        celebrity_tasks = [
            asyncio.create_task(self.celebrity_task(i, celebrity_results))
            for i in range(self.config.concurrent_celebrities)
        ]
        await asyncio.gather(*celebrity_tasks)
        celebrity_stats = self.calculate_stats(celebrity_results)

        # Print results
        print("\n=== TRAFFIC TEST RESULTS ===")
        print(f"Duration: {self.config.duration_seconds}s per phase")
        print(f"Timeout: {self.config.timeout_seconds}s")
        print()

        self.print_phase_results("WRITER", writer_stats)
        self.print_phase_results("READER", reader_stats)
        self.print_phase_results("CELEBRITY", celebrity_stats)

        # Summary
        total_requests = writer_stats["requests"] + reader_stats["requests"] + celebrity_stats["requests"]
        total_errors = writer_stats["errors"] + reader_stats["errors"] + celebrity_stats["errors"]
        total_rps = total_requests / (self.config.duration_seconds * 3)

        print("\n=== SUMMARY ===")
        print(f"Total Requests: {total_requests:,}")
        print(f"Total Errors: {total_errors:,}")
        print(f"Error Rate: {(total_errors/total_requests*100):.2f}%")
        print(f"Overall RPS: {total_rps:.1f}")

        # Performance analysis
        print("\n=== PERFORMANCE ANALYSIS ===")
        if total_rps > 1000:
            print("🚀 High Performance: > 1000 RPS")
        elif total_rps > 500:
            print("✅ Good Performance: > 500 RPS")
        elif total_rps > 200:
            print("⚠️ Moderate Performance: > 200 RPS")
        else:
            print("❌ Low Performance: < 200 RPS")

        if total_errors / total_requests < 0.05:
            print("✅ Excellent Reliability: < 5% errors")
        elif total_errors / total_requests < 0.1:
            print("⚠️ Good Reliability: < 10% errors")
        else:
            print("❌ Poor Reliability: > 10% errors")

        return {
            "total_requests": total_requests,
            "total_errors": total_errors,
            "total_rps": total_rps,
            "error_rate": total_errors / total_requests,
            "writer_stats": writer_stats,
            "reader_stats": reader_stats,
            "celebrity_stats": celebrity_stats,
        }

    def print_phase_results(self, phase: str, stats: dict):
        """Print phase results."""
        rps = stats["requests"] / self.config.duration_seconds
        error_rate = (stats["errors"] / stats["requests"] * 100) if stats["requests"] > 0 else 0

        print(f"{phase}:")
        print(f"  Requests: {stats['requests']:,} ({rps:.1f} RPS)")
        print(f"  Errors: {stats['errors']:,} ({error_rate:.2f}%)")
        print(f"  Avg Response: {stats['avg_response_time_ms']:.1f}ms")
        print(f"  P95 Response: {stats['p95_response_time_ms']:.1f}ms")
        print(f"  P99 Response: {stats['p99_response_time_ms']:.1f}ms")


async def main():
    """Main traffic generator entry point."""
    config = TrafficConfig(
        base_url="http://localhost:8080",
        duration_seconds=30,  # Shorter for demo
        concurrent_writers=15,
        concurrent_readers=50,
        concurrent_celebrities=25,
        celebrity_pool_size=10,
        warmup_urls=500,
        timeout_seconds=3,
    )

    generator = TrafficGenerator(config)

    async with aiohttp.ClientSession() as client:
        generator.client = client
        results = await generator.run_traffic_test()

        print("\n🎯 Traffic Test Complete!")
        print(f"📊 Final RPS: {results['total_rps']:.1f}")
        print(f"📈 Error Rate: {results['error_rate']*100:.2f}%")
        print(f"🔗 Total Requests: {results['total_requests']:,}")


if __name__ == "__main__":
    asyncio.run(main())
