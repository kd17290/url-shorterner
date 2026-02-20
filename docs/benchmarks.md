---
description: Benchmarks and performance baselines (docker-only)
---

# Benchmarks

This document tracks **repeatable, docker-only** performance baselines for the system.

## Rules

- All benchmark commands must run **inside Docker**.
- Record:
  - the command
  - the environment knobs
  - the measured output
  - the commit/date (when available)

## Full Workflow Benchmark (writer + reader + celebrity)

> **This is the only benchmark.** `make bench` runs the complete request lifecycle — writer, reader, and celebrity — simultaneously. There is no separate health-check micro benchmark.

This benchmark exercises the **complete request lifecycle** simultaneously:

| Scenario | Endpoint | Description |
|---|---|---|
| **writer** | `POST /api/shorten` | Creates new short URLs; measures write throughput |
| **reader** | `GET /<code>` (broad pool) | Redirects across all warmed-up codes; measures read throughput |
| **celebrity** | `GET /<code>` (hot pool) | Skewed reads on a tiny N-code pool; simulates viral/hot-key traffic |

### Command

```bash
make bench
```

### Knobs

| Variable | Default | Description |
|---|---|---|
| `BENCH_BASE_URL` | `http://host.docker.internal:8080` | Load balancer URL |
| `BENCH_DURATION_SECONDS` | `15` | Duration of each scenario (all run simultaneously) |
| `BENCH_TIMEOUT_SECONDS` | `2` | Per-request timeout |
| `BENCH_WRITER_CONCURRENCY` | `10` | Concurrent writer coroutines |
| `BENCH_READER_CONCURRENCY` | `60` | Concurrent reader coroutines |
| `BENCH_CELEBRITY_CONCURRENCY` | `30` | Concurrent celebrity reader coroutines |
| `BENCH_CELEBRITY_POOL_SIZE` | `5` | Number of hot short codes to concentrate celebrity reads on |
| `BENCH_WARMUP_URLS` | `200` | Short URLs pre-created before the timed run |

Example override:

```bash
BENCH_DURATION_SECONDS=30 BENCH_CELEBRITY_POOL_SIZE=3 make bench
```

### Baseline

```text
DATE:    2026-02-21
COMMAND: make bench  (all defaults, 3-app stack behind nginx lb)

[writer (POST /api/shorten)]
  concurrency       = 10
  duration_s        = 15.0
  total_requests    = 1166
  ok                = 1166
  errors            = 0
  rps               = 77.73
  avg_latency_ms    = 129.16

[reader (GET /<code> — broad pool)]
  concurrency       = 60
  duration_s        = 15.0
  total_requests    = 6885
  ok                = 6885
  errors            = 0
  rps               = 459.00
  avg_latency_ms    = 131.15

[celebrity (GET /<code> — 5-code hot pool)]
  concurrency       = 30
  duration_s        = 15.0
  total_requests    = 3430
  ok                = 3430
  errors            = 0
  rps               = 228.67
  avg_latency_ms    = 131.43

[aggregate]
  total_requests    = 11481
  ok                = 11481
  errors            = 0
  rps               = 765.40
```

**Notes:**
- Celebrity reads hit the Redis cache (hot ZSET + per-code cache key); latency is similar to broad reads because both are cache-served.
- Writer latency (~129ms) reflects DB write + Kafka publish + keygen round-trip.
- All three scenarios run **concurrently** — aggregate RPS is the combined throughput under realistic mixed load.

---

## Load benchmarks (Locust)

For realistic throughput numbers (e.g. 100k RPS), use the existing Locust orchestrators:

- `make orchestrator-100k`
- `make orchestrator-100k-dist`

Record the scenario, duration, and key Grafana panels (RPS split, 5xx, ingestion rates).
