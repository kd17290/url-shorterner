"""High-throughput sustained flood for the Rust stack.

Strategy
--------
1. Warm cache: create WARMUP_URLS short codes via POST (batched).
2. Flood phase: spawn FLOOD_CONCURRENCY async workers that hammer
   GET /<code> with follow_redirects=False.  All codes are already
   in Redis so every request is a pure cache hit — no DB round-trip.
3. A stats-printer coroutine prints a live RPS line every second so
   you can watch the numbers climb in the terminal while Grafana shows
   the same traffic in real time.

Env knobs
---------
FLOOD_BASE_URL          default: http://localhost:8080
FLOOD_DURATION_SECONDS  default: 300   (5 minutes of live traffic)
FLOOD_CONCURRENCY       default: 500   (concurrent GET workers)
FLOOD_WARMUP_URLS       default: 500   (codes to pre-warm into Redis)
FLOOD_WARMUP_BATCH      default: 20    (POST batch size during warmup)
FLOOD_TIMEOUT           default: 5     (per-request timeout seconds)
FLOOD_WRITER_RATIO      default: 0.05  (5 % of workers also POST)
"""

import asyncio
import os
import random
import string
import time
from dataclasses import dataclass, field

import httpx


# ── shared counters (written from many coroutines) ───────────────────────────
@dataclass
class Counters:
    ok: int = 0
    errors: int = 0
    latency_total_s: float = 0.0
    window_ok: int = 0       # reset every second by the printer
    window_errors: int = 0


def _random_url() -> str:
    slug = "".join(random.choices(string.ascii_lowercase, k=10))
    return f"https://flood-target-{slug}.example.com/path"


# ── warmup ────────────────────────────────────────────────────────────────────
async def warmup(
    client: httpx.AsyncClient,
    base_url: str,
    count: int,
    batch_size: int,
) -> list[str]:
    print(f"[warmup] creating {count} short URLs in batches of {batch_size}…")
    codes: list[str] = []
    for i in range(0, count, batch_size):
        batch_n = min(batch_size, count - i)
        tasks = [
            client.post(f"{base_url}/api/shorten", json={"url": _random_url()})
            for _ in range(batch_n)
        ]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        for r in responses:
            if isinstance(r, httpx.Response) and r.status_code == 201:
                code = r.json().get("short_code", "")
                if code:
                    codes.append(code)
        if (i // batch_size) % 5 == 0:
            print(f"  … {len(codes)}/{count} created")
    print(f"[warmup] done — {len(codes)} codes in Redis cache")
    return codes


# ── reader worker ─────────────────────────────────────────────────────────────
async def reader_worker(
    client: httpx.AsyncClient,
    base_url: str,
    codes: list[str],
    deadline: float,
    counters: Counters,
) -> None:
    while time.perf_counter() < deadline:
        code = random.choice(codes)
        t0 = time.perf_counter()
        try:
            r = await client.get(f"{base_url}/{code}")
            elapsed = time.perf_counter() - t0
            counters.latency_total_s += elapsed
            if 200 <= r.status_code < 400:
                counters.ok += 1
                counters.window_ok += 1
            else:
                counters.errors += 1
                counters.window_errors += 1
        except Exception:
            counters.errors += 1
            counters.window_errors += 1


# ── writer worker (small fraction to keep metrics interesting) ────────────────
async def writer_worker(
    client: httpx.AsyncClient,
    base_url: str,
    codes: list[str],
    deadline: float,
    counters: Counters,
) -> None:
    while time.perf_counter() < deadline:
        t0 = time.perf_counter()
        try:
            r = await client.post(
                f"{base_url}/api/shorten", json={"url": _random_url()}
            )
            elapsed = time.perf_counter() - t0
            counters.latency_total_s += elapsed
            if r.status_code == 201:
                code = r.json().get("short_code", "")
                if code:
                    codes.append(code)
                counters.ok += 1
                counters.window_ok += 1
            else:
                counters.errors += 1
                counters.window_errors += 1
        except Exception:
            counters.errors += 1
            counters.window_errors += 1


# ── live stats printer ────────────────────────────────────────────────────────
async def stats_printer(
    counters: Counters,
    deadline: float,
    duration_s: float,
) -> None:
    start = time.perf_counter()
    peak_rps = 0.0
    while time.perf_counter() < deadline:
        await asyncio.sleep(1.0)
        elapsed = time.perf_counter() - start
        rps = counters.window_ok + counters.window_errors
        peak_rps = max(peak_rps, rps)
        avg_lat = (
            counters.latency_total_s / max(counters.ok + counters.errors, 1) * 1000
        )
        remaining = max(0, deadline - time.perf_counter())
        print(
            f"  t={elapsed:5.0f}s | RPS={rps:6.0f} | peak={peak_rps:6.0f}"
            f" | ok={counters.ok:8d} | err={counters.errors:6d}"
            f" | avg_lat={avg_lat:5.1f}ms | remaining={remaining:.0f}s"
        )
        counters.window_ok = 0
        counters.window_errors = 0


# ── main ──────────────────────────────────────────────────────────────────────
async def main() -> None:
    base_url = os.getenv("FLOOD_BASE_URL", "http://localhost:8080")
    duration_s = float(os.getenv("FLOOD_DURATION_SECONDS", "300"))
    concurrency = int(os.getenv("FLOOD_CONCURRENCY", "500"))
    warmup_count = int(os.getenv("FLOOD_WARMUP_URLS", "500"))
    warmup_batch = int(os.getenv("FLOOD_WARMUP_BATCH", "20"))
    timeout_s = float(os.getenv("FLOOD_TIMEOUT", "5"))
    writer_ratio = float(os.getenv("FLOOD_WRITER_RATIO", "0.05"))

    n_writers = max(1, int(concurrency * writer_ratio))
    n_readers = concurrency - n_writers

    print("=" * 65)
    print("  Rust Stack — Sustained Flood")
    print("=" * 65)
    print(f"  base_url    = {base_url}")
    print(f"  duration    = {duration_s:.0f}s")
    print(f"  concurrency = {concurrency}  ({n_readers} readers + {n_writers} writers)")
    print(f"  warmup      = {warmup_count} URLs")
    print()

    limits = httpx.Limits(
        max_keepalive_connections=concurrency + 50,
        max_connections=concurrency + 50,
    )

    async with httpx.AsyncClient(
        timeout=timeout_s, limits=limits, follow_redirects=False
    ) as client:
        codes = await warmup(client, base_url, warmup_count, warmup_batch)
        if not codes:
            print("[ERROR] warmup produced 0 codes — is the Rust stack healthy?")
            return

        counters = Counters()
        deadline = time.perf_counter() + duration_s

        print(f"\n[flood] starting {concurrency} workers for {duration_s:.0f}s…")
        print(
            "  t(s)  | RPS    | peak   | ok       | err    | avg_lat | remaining"
        )
        print("  " + "-" * 63)

        tasks = [
            asyncio.create_task(
                reader_worker(client, base_url, codes, deadline, counters)
            )
            for _ in range(n_readers)
        ] + [
            asyncio.create_task(
                writer_worker(client, base_url, codes, deadline, counters)
            )
            for _ in range(n_writers)
        ] + [
            asyncio.create_task(
                stats_printer(counters, deadline, duration_s)
            )
        ]

        await asyncio.gather(*tasks)

    total = counters.ok + counters.errors
    avg_lat = counters.latency_total_s / max(total, 1) * 1000
    rps = total / duration_s

    print()
    print("=" * 65)
    print("[flood complete]")
    print(f"  total_requests = {total:,}")
    print(f"  ok             = {counters.ok:,}")
    print(f"  errors         = {counters.errors:,}")
    print(f"  avg_rps        = {rps:,.1f}")
    print(f"  avg_latency_ms = {avg_lat:.1f}")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(main())
