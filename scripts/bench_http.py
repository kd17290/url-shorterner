#!/usr/bin/env python3
"""
HTTP benchmark script for URL shortener performance testing.

Tests three scenarios:
1. Writer: Create new URLs
2. Reader: Access existing URLs
3. Celebrity: High traffic to popular URLs
"""

import asyncio
import os
import random
import time
from collections import defaultdict
from dataclasses import dataclass

import httpx


@dataclass
class BenchConfig:
    base_url: str = "http://host.docker.internal:8080"
    duration_seconds: int = 15
    timeout_seconds: int = 2
    writer_concurrency: int = 10
    reader_concurrency: int = 60
    celebrity_concurrency: int = 30
    celebrity_pool_size: int = 5
    warmup_urls: int = 200


@dataclass
class BenchResult:
    requests: int
    errors: int
    total_time: float
    avg_response_time: float
    p95_response_time: float
    p99_response_time: float


class BenchClient:
    def __init__(self, config: BenchConfig):
        self.config = config
        self.client = httpx.AsyncClient(timeout=config.timeout_seconds)
        self.response_times = []
        self.errors = defaultdict(int)
        self.warmup_urls = []

    async def warmup(self):
        """Create warmup URLs for testing."""
        print(f"Warming up {self.config.warmup_urls} URLs...")

        for i in range(self.config.warmup_urls):
            try:
                original_url = f"https://example{i}.com"
                response = await self.client.post(f"{self.config.base_url}/api/shorten", json={"url": original_url})
                if response.status_code == 201:
                    data = response.json()
                    self.warmup_urls.append(data["short_code"])
                else:
                    print(f"Warmup failed: {response.status_code}")

                if i % 50 == 0:
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
                original_url = f"https://bench-{task_id}-{requests}.example.com"
                req_start = time.time()

                response = await self.client.post(f"{self.config.base_url}/api/shorten", json={"url": original_url})

                response_time = time.time() - req_start
                response_times.append(response_time)
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

                response = await self.client.get(f"{self.config.base_url}/{short_code}", follow_redirects=False)

                response_time = time.time() - req_start
                response_times.append(response_time)
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

                response = await self.client.get(f"{self.config.base_url}/{short_code}", follow_redirects=False)

                response_time = time.time() - req_start
                response_times.append(response_time)
                requests += 1

                if response.status_code not in [301, 302]:
                    errors += 1

            except Exception:
                errors += 1

        results.append(
            {"task": f"celebrity-{task_id}", "requests": requests, "errors": errors, "response_times": response_times}
        )

    def calculate_stats(self, results: list[dict]) -> BenchResult:
        """Calculate benchmark statistics."""
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

        return BenchResult(
            requests=total_requests,
            errors=total_errors,
            total_time=self.config.duration_seconds,
            avg_response_time=avg_response_time,
            p95_response_time=p95_response_time,
            p99_response_time=p99_response_time,
        )

    async def run_benchmark(self):
        """Run complete benchmark."""
        print(f"Starting benchmark with config: {self.config}")

        # Warmup phase
        await self.warmup()

        print("Starting benchmark phases...")

        # Writer phase
        print(f"\n=== Writer Phase ({self.config.writer_concurrency} workers) ===")
        writer_results = []
        writer_tasks = [
            asyncio.create_task(self.writer_task(i, writer_results)) for i in range(self.config.writer_concurrency)
        ]
        await asyncio.gather(*writer_tasks)
        writer_stats = self.calculate_stats(writer_results)

        # Reader phase
        print(f"\n=== Reader Phase ({self.config.reader_concurrency} workers) ===")
        reader_results = []
        reader_tasks = [
            asyncio.create_task(self.reader_task(i, reader_results)) for i in range(self.config.reader_concurrency)
        ]
        await asyncio.gather(*reader_tasks)
        reader_stats = self.calculate_stats(reader_results)

        # Celebrity phase
        print(f"\n=== Celebrity Phase ({self.config.celebrity_concurrency} workers) ===")
        celebrity_results = []
        celebrity_tasks = [
            asyncio.create_task(self.celebrity_task(i, celebrity_results))
            for i in range(self.config.celebrity_concurrency)
        ]
        await asyncio.gather(*celebrity_tasks)
        celebrity_stats = self.calculate_stats(celebrity_results)

        # Print results
        print("\n=== BENCHMARK RESULTS ===")
        print(f"Duration: {self.config.duration_seconds}s per phase")
        print(f"Timeout: {self.config.timeout_seconds}s")
        print()

        self.print_phase_results("WRITER", writer_stats)
        self.print_phase_results("READER", reader_stats)
        self.print_phase_results("CELEBRITY", celebrity_stats)

        # Summary
        total_requests = writer_stats.requests + reader_stats.requests + celebrity_stats.requests
        total_errors = writer_stats.errors + reader_stats.errors + celebrity_stats.errors
        total_rps = total_requests / (self.config.duration_seconds * 3)

        print("\n=== SUMMARY ===")
        print(f"Total Requests: {total_requests:,}")
        print(f"Total Errors: {total_errors:,}")
        print(f"Error Rate: {(total_errors/total_requests*100):.2f}%")
        print(f"Overall RPS: {total_rps:.1f}")

    def print_phase_results(self, phase: str, stats: BenchResult):
        """Print phase results."""
        rps = stats.requests / stats.total_time
        error_rate = (stats.errors / stats.requests * 100) if stats.requests > 0 else 0

        print(f"{phase}:")
        print(f"  Requests: {stats.requests:,} ({rps:.1f} RPS)")
        print(f"  Errors: {stats.errors:,} ({error_rate:.2f}%)")
        print(f"  Avg Response: {stats.avg_response_time*1000:.1f}ms")
        print(f"  P95 Response: {stats.p95_response_time*1000:.1f}ms")
        print(f"  P99 Response: {stats.p99_response_time*1000:.1f}ms")


async def main():
    """Main benchmark entry point."""
    config = BenchConfig(
        base_url=os.getenv("BENCH_BASE_URL", "http://host.docker.internal:8080"),
        duration_seconds=int(os.getenv("BENCH_DURATION_SECONDS", "15")),
        timeout_seconds=int(os.getenv("BENCH_TIMEOUT_SECONDS", "2")),
        writer_concurrency=int(os.getenv("BENCH_WRITER_CONCURRENCY", "10")),
        reader_concurrency=int(os.getenv("BENCH_READER_CONCURRENCY", "60")),
        celebrity_concurrency=int(os.getenv("BENCH_CELEBRITY_CONCURRENCY", "30")),
        celebrity_pool_size=int(os.getenv("BENCH_CELEBRITY_POOL_SIZE", "5")),
        warmup_urls=int(os.getenv("BENCH_WARMUP_URLS", "200")),
    )

    client = BenchClient(config)
    await client.run_benchmark()


if __name__ == "__main__":
    asyncio.run(main())
