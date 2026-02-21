"""Full workflow HTTP benchmark for the URL shortener.

Covers three traffic patterns:
  - writer:    POST /api/shorten  (creates new short URLs)
  - reader:    GET  /<short_code> (redirects from a shared pool)
  - celebrity: GET  /<short_code> (skewed reads on a tiny hot-key pool)

Env knobs
---------
BENCH_BASE_URL              Base URL of the load balancer (default: http://localhost:8080)
BENCH_DURATION_SECONDS      How long to run each scenario (default: 15)
BENCH_TIMEOUT_SECONDS       Per-request timeout (default: 2)
BENCH_WRITER_CONCURRENCY    Concurrent writer coroutines (default: 10)
BENCH_READER_CONCURRENCY    Concurrent reader coroutines (default: 60)
BENCH_CELEBRITY_CONCURRENCY Concurrent celebrity reader coroutines (default: 30)
BENCH_CELEBRITY_POOL_SIZE   Number of hot short codes to concentrate reads on (default: 5)
BENCH_WARMUP_URLS           Number of URLs to create before read/celebrity phases (default: 200)
"""

import asyncio
import os
import random
import string
import time
from dataclasses import dataclass, field

import httpx


@dataclass
class ScenarioResult:
    name: str
    concurrency: int
    duration_s: float
    ok: int = 0
    errors: int = 0
    latency_total_s: float = 0.0
    short_codes_created: list[str] = field(default_factory=list)

    @property
    def total_requests(self) -> int:
        return self.ok + self.errors

    @property
    def rps(self) -> float:
        return self.total_requests / self.duration_s if self.duration_s > 0 else 0.0

    @property
    def avg_latency_ms(self) -> float:
        return (self.latency_total_s / max(self.total_requests, 1)) * 1000.0

    def print_summary(self) -> None:
        print(f"\n[{self.name}]")
        print(f"  concurrency       = {self.concurrency}")
        print(f"  duration_s        = {self.duration_s:.1f}")
        print(f"  total_requests    = {self.total_requests}")
        print(f"  ok                = {self.ok}")
        print(f"  errors            = {self.errors}")
        print(f"  rps               = {self.rps:.2f}")
        print(f"  avg_latency_ms    = {self.avg_latency_ms:.2f}")


def _random_url() -> str:
    slug = "".join(random.choices(string.ascii_lowercase, k=8))
    return f"https://bench-target-{slug}.example.com/path"


async def _writer_worker(
    client: httpx.AsyncClient,
    base_url: str,
    duration_s: float,
    result: ScenarioResult,
) -> None:
    deadline = time.perf_counter() + duration_s
    while time.perf_counter() < deadline:
        start = time.perf_counter()
        try:
            response = await client.post(
                f"{base_url}/api/shorten",
                json={"url": _random_url()},
            )
            result.latency_total_s += time.perf_counter() - start
            if response.status_code == 201:
                result.ok += 1
                short_code = response.json().get("short_code", "")
                if short_code:
                    result.short_codes_created.append(short_code)
            else:
                result.errors += 1
        except Exception:
            result.errors += 1


async def _reader_worker(
    client: httpx.AsyncClient,
    base_url: str,
    duration_s: float,
    shared_codes: list[str],
    result: ScenarioResult,
) -> None:
    deadline = time.perf_counter() + duration_s
    while time.perf_counter() < deadline:
        if not shared_codes:
            await asyncio.sleep(0.05)
            continue
        short_code = random.choice(shared_codes)
        start = time.perf_counter()
        try:
            response = await client.get(f"{base_url}/{short_code}")
            result.latency_total_s += time.perf_counter() - start
            if 200 <= response.status_code < 400:
                result.ok += 1
            else:
                result.errors += 1
        except Exception:
            result.errors += 1


async def _warmup(
    client: httpx.AsyncClient,
    base_url: str,
    count: int,
    batch_size: int = 5,
) -> list[str]:
    print(f"\n[warmup] creating {count} short URLs...")
    short_codes: list[str] = []
    for i in range(0, count, batch_size):
        batch = [
            client.post(f"{base_url}/api/shorten", json={"url": _random_url()})
            for _ in range(min(batch_size, count - i))
        ]
        responses = await asyncio.gather(*batch, return_exceptions=True)
        for response in responses:
            if isinstance(response, httpx.Response) and response.status_code == 201:
                code = response.json().get("short_code", "")
                if code:
                    short_codes.append(code)
    print(f"[warmup] created {len(short_codes)} short URLs")
    return short_codes


async def main() -> None:
    base_url = os.getenv("BENCH_BASE_URL", "http://localhost:8080")
    duration_s = float(os.getenv("BENCH_DURATION_SECONDS", "15"))
    timeout_s = float(os.getenv("BENCH_TIMEOUT_SECONDS", "2"))
    writer_concurrency = int(os.getenv("BENCH_WRITER_CONCURRENCY", "10"))
    reader_concurrency = int(os.getenv("BENCH_READER_CONCURRENCY", "60"))
    celebrity_concurrency = int(os.getenv("BENCH_CELEBRITY_CONCURRENCY", "30"))
    celebrity_pool_size = int(os.getenv("BENCH_CELEBRITY_POOL_SIZE", "5"))
    warmup_count = int(os.getenv("BENCH_WARMUP_URLS", "200"))

    total_concurrency = writer_concurrency + reader_concurrency + celebrity_concurrency
    limits = httpx.Limits(
        max_keepalive_connections=total_concurrency,
        max_connections=total_concurrency,
    )

    print("=" * 60)
    print("URL Shortener — Full Workflow Benchmark")
    print("=" * 60)
    print(f"  base_url              = {base_url}")
    print(f"  duration_s            = {duration_s}")
    print(f"  writer_concurrency    = {writer_concurrency}")
    print(f"  reader_concurrency    = {reader_concurrency}")
    print(f"  celebrity_concurrency = {celebrity_concurrency}")
    print(f"  celebrity_pool_size   = {celebrity_pool_size}")

    async with httpx.AsyncClient(timeout=timeout_s, limits=limits, follow_redirects=False) as client:
        shared_codes = await _warmup(client, base_url, warmup_count)

        celebrity_pool = (
            shared_codes[:celebrity_pool_size] if len(shared_codes) >= celebrity_pool_size else shared_codes
        )

        writer_result = ScenarioResult(
            name="writer (POST /api/shorten)", concurrency=writer_concurrency, duration_s=duration_s
        )
        reader_result = ScenarioResult(
            name="reader (GET /<code> — broad pool)", concurrency=reader_concurrency, duration_s=duration_s
        )
        celebrity_result = ScenarioResult(
            name=f"celebrity (GET /<code> — {len(celebrity_pool)}-code hot pool)",
            concurrency=celebrity_concurrency,
            duration_s=duration_s,
        )

        print(f"\n[running] all three scenarios simultaneously for {duration_s}s...")

        writer_tasks = [
            asyncio.create_task(_writer_worker(client, base_url, duration_s, writer_result))
            for _ in range(writer_concurrency)
        ]
        reader_tasks = [
            asyncio.create_task(_reader_worker(client, base_url, duration_s, shared_codes, reader_result))
            for _ in range(reader_concurrency)
        ]
        celebrity_tasks = [
            asyncio.create_task(_reader_worker(client, base_url, duration_s, celebrity_pool, celebrity_result))
            for _ in range(celebrity_concurrency)
        ]

        await asyncio.gather(*writer_tasks, *reader_tasks, *celebrity_tasks)

    writer_result.print_summary()
    reader_result.print_summary()
    celebrity_result.print_summary()

    all_ok = writer_result.ok + reader_result.ok + celebrity_result.ok
    all_errors = writer_result.errors + reader_result.errors + celebrity_result.errors
    all_total = all_ok + all_errors
    all_rps = all_total / duration_s if duration_s > 0 else 0.0

    print("\n" + "=" * 60)
    print("[aggregate]")
    print(f"  total_requests = {all_total}")
    print(f"  ok             = {all_ok}")
    print(f"  errors         = {all_errors}")
    print(f"  rps            = {all_rps:.2f}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
