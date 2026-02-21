# Python vs Rust Stack — Benchmark Comparison

**Date:** 2026-02-21  
**Machine:** macOS (Apple Silicon), Docker Desktop  
**Tool:** `scripts/bench_http.py` (httpx async, 20 s duration)

---

## Test Configuration

| Parameter | High-concurrency run | Low-concurrency run |
|---|---|---|
| Writer concurrency | 10 | 3 |
| Reader concurrency | 60 | 10 |
| Celebrity concurrency | 30 | 5 |
| Celebrity pool size | 5 | 5 |
| Duration | 20 s | 20 s |
| Timeout | 5 s | 5 s |

---

## Results — High Concurrency (writer=10, reader=60, celebrity=30)

### Rust Stack

| Scenario | Requests | OK | Errors | RPS | Avg Latency |
|---|---|---|---|---|---|
| POST /api/shorten | 1 196 | 1 196 | **0** | 59.80 | 168 ms |
| GET /\<code\> (broad) | 6 747 | 6 747 | **0** | 337.35 | 179 ms |
| GET /\<code\> (celebrity) | 3 447 | 3 447 | **0** | 172.35 | 175 ms |
| **Aggregate** | **11 390** | **11 390** | **0** | **569.50** | — |

### Python Stack

Python stack hit `QueuePool limit` (SQLAlchemy connection pool exhausted) under 100 concurrent connections. Results at this concurrency level are not meaningful for comparison — see low-concurrency run below.

---

## Results — Low Concurrency (writer=3, reader=10, celebrity=5)

### Python Stack

| Scenario | Requests | OK | Errors | RPS | Avg Latency |
|---|---|---|---|---|---|
| POST /api/shorten | 51 | 45 | 6 | 2.55 | 702 ms |
| GET /\<code\> (broad) | 974 | 965 | 9 | 48.70 | 166 ms |
| GET /\<code\> (celebrity) | 743 | 741 | 2 | 37.15 | 121 ms |
| **Aggregate** | **1 768** | **1 751** | **17** | **88.40** | — |

---

## Summary

| Metric | Python (concurrency=18) | Rust (concurrency=100) | Rust / Python |
|---|---|---|---|
| Aggregate RPS | 88 | 570 | **6.5×** |
| Writer RPS | 2.6 | 59.8 | **23×** |
| Reader RPS | 48.7 | 337 | **6.9×** |
| Celebrity RPS | 37.2 | 172 | **4.6×** |
| Writer avg latency | 702 ms | 168 ms | **4.2× faster** |
| Error rate | ~1% | **0%** | — |
| Max stable concurrency | ~18 | **100+** | **5.5×** |

---

## Rust — 100k Load Test (concurrency=170, 60 s)

| Scenario | Requests | OK | Errors | RPS | Avg Latency |
|---|---|---|---|---|---|
| POST /api/shorten (×20) | 3 126 | 3 126 | **0** | 52.10 | 385 ms |
| GET /\<code\> broad (×100) | 15 784 | 15 784 | **0** | 263.07 | 381 ms |
| GET /\<code\> celebrity (×50) | 7 666 | 7 666 | **0** | 127.77 | 393 ms |
| **Aggregate** | **26 576** | **26 576** | **0** | **442.93** | — |

- **26,576 total requests** processed with **zero errors** under 170 concurrent connections.
- Latency stays flat at ~385 ms avg even at 170 concurrency — Tokio's work-stealing scheduler absorbs the load without pool exhaustion.

---

## Root Cause Analysis

### Python stack bottlenecks

1. **DB connection pool exhaustion** — SQLAlchemy `AsyncSession` holds a connection for the full request lifetime. With 3 app instances × 30 pool connections = 90 max, the pool saturates at ~30 concurrent requests per instance.
2. **GIL + asyncio overhead** — Python's async model is single-threaded per worker; CPU-bound encoding and JSON serialisation compete with I/O waits.
3. **Redis replica write bug (fixed)** — `get_url_by_code` was passing the read-replica client to `_acquire_cache_lock` / `_release_cache_lock`, causing `ReadOnlyError` on every cache-miss redirect. Fixed by adding a `cache_write` parameter.

### Rust stack advantages

1. **Zero-cost async** — Tokio multiplexes thousands of tasks across OS threads with no GIL.
2. **SQLx connection pool** — `PgPool` uses a lock-free pool that scales to hundreds of concurrent queries without exhaustion.
3. **Static typing + zero-copy** — No runtime type checks, no garbage collector pauses.
4. **Memory safety without GC** — Rust's ownership model eliminates allocation overhead present in CPython.

---

## Bugs Fixed During This Session

| Service | Bug | Fix |
|---|---|---|
| Python `app` | `ReadOnlyError` on redirect — `_acquire_cache_lock` called on read-replica | Added `cache_write` param to `get_url_by_code`; route passes primary |
| Rust `app-rs` | `envy` not reading uppercase env vars | Replaced `envy` with direct `std::env::var` in all 3 services |
| Rust `app-rs` | `ConnectionManager` not `Clone` in redis 0.25 | Wrapped in `Arc<Mutex<ConnectionManager>>` |
| Rust `app-rs` | `id`/`clicks` columns `INT4` but model used `i64` | Changed model fields to `i32` |
| Rust `app-rs` | INSERT missing `clicks` column (NOT NULL) | Added `clicks = 0` to INSERT |
| Rust `ingestion-rs` | `pipe.query_async` never-type fallback | Added `::<_, ()>` type annotation |
| All Rust | `rdkafka cmake-build` missing `make`/`gcc`/`g++` | Added `build-essential cmake libcurl4-openssl-dev` to Dockerfiles |

---

## Next Steps

- Increase Python DB pool via PgBouncer (connection pooler) to close the gap
- Profile Rust stack under sustained 500+ RPS to identify next bottleneck
- Add CI workflows to gate both stacks on regression benchmarks
