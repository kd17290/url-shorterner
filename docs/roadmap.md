# Project Roadmap

Current state: **v1.0.0** — Python/FastAPI URL shortener with PostgreSQL + Redis + Kafka +
ClickHouse, 3-replica nginx load-balanced stack, full CI/CD pipeline green.

---

## Phase 2 — Scale the Write Path (PostgreSQL → ScyllaDB/Cassandra)

### Why PostgreSQL is the bottleneck

The current write path:
```
POST /api/shorten → FastAPI → PostgreSQL (single primary, synchronous write)
                             → Redis (async, non-blocking)
                             → Kafka (async, non-blocking)
```

PostgreSQL is the only synchronous blocking step. At scale:
- Single primary → vertical scaling limit ~50k writes/s
- `CREATE TABLE` race condition on multi-replica startup (fixed with advisory lock, but
  signals the deeper issue: DDL is not designed for horizontal scale)
- Row-level locking on `id SERIAL` causes contention under high concurrency

### Option A — ScyllaDB (Cassandra-compatible, C++ rewrite)

ScyllaDB is a drop-in Cassandra replacement written in C++ (Seastar framework).
It achieves 1M+ ops/s on commodity hardware.

**Schema change:**
```cql
CREATE TABLE urls (
    short_code  TEXT PRIMARY KEY,
    original_url TEXT,
    clicks      COUNTER,
    created_at  TIMESTAMP
) WITH compaction = {'class': 'LeveledCompactionStrategy'};
```

**Trade-offs vs PostgreSQL:**

| | PostgreSQL | ScyllaDB |
|---|---|---|
| Write throughput | ~10k–50k/s (single primary) | 500k–1M+/s (multi-node) |
| Read throughput | ~50k–100k/s | 1M+/s |
| Consistency | Strong (ACID) | Tunable (eventual by default) |
| Schema flexibility | Full SQL, joins, transactions | No joins, partition-key access only |
| Operational complexity | Low (single node easy) | Higher (cluster management) |
| Python driver | `asyncpg` (excellent) | `cassandra-driver` (async via `aiocassandra`) |
| Click counter | `UPDATE urls SET clicks = clicks + 1` (row lock) | `UPDATE urls SET clicks = clicks + 1` (CRDT counter, lock-free) |

**Migration plan:**
1. Add `cassandra-driver` + `aiocassandra` to `requirements.txt`
2. Create `app/database_scylla.py` mirroring `database.py` interface
3. Run both DBs in parallel (feature flag `USE_SCYLLA=true`)
4. Benchmark both with `make bench`, compare RPS numbers
5. Cut over when ScyllaDB numbers are validated

### Option B — Keep PostgreSQL, add read replicas + connection pooling

Simpler path for moderate scale (up to ~500k reads/day):
- Add `PgBouncer` in front of PostgreSQL (transaction-mode pooling)
- Add 1–2 read replicas, route `GET /<code>` reads to replicas
- Use `UNLOGGED TABLE` for the URL table (no WAL overhead, ~2× write speed)
- Add `pg_partman` for time-based partitioning of click events

---

## Phase 3 — Rewrite Hot Path in Rust (Performance Comparison)

### What to rewrite

Only the **read path** (`GET /<code>` → redirect) is worth rewriting in Rust.
It is the highest-volume, lowest-complexity endpoint.

The write path (`POST /api/shorten`) involves Kafka, keygen, and DB — the bottleneck
is I/O, not CPU. Python async handles this fine.

### Rust stack

| Component | Choice | Reason |
|---|---|---|
| HTTP framework | `axum` (tokio) | Fastest Rust async HTTP, ergonomic |
| Redis client | `fred` or `deadpool-redis` | Async, connection pooling |
| PostgreSQL client | `sqlx` | Async, compile-time query checking |
| Serialization | `serde_json` | Zero-copy deserialization |

### Expected gains (read path only)

Based on published benchmarks (TechEmpower Round 22):

| | Python/FastAPI | Rust/axum |
|---|---|---|
| Plaintext RPS | ~100k | ~1.2M |
| JSON RPS | ~80k | ~900k |
| DB query RPS | ~20k | ~200k |
| Memory per instance | ~50MB | ~5MB |
| Cold start | ~2s | ~50ms |

**Realistic gain for this project** (Redis-cached reads, single lookup):
- Python: ~460 RPS (measured locally, 3 replicas, nginx)
- Rust: estimated ~3,000–5,000 RPS (same hardware, same Redis)
- **~7–10× improvement** on the read path

### Implementation plan

```
services/
  redirect-rs/          ← new Rust service
    src/
      main.rs           ← axum server, GET /<code> handler
      cache.rs          ← Redis lookup (fred client)
      db.rs             ← PostgreSQL fallback (sqlx)
    Cargo.toml
    Dockerfile
```

The Rust service replaces only the redirect handler. The Python app continues handling
`POST /api/shorten`, `/api/stats`, `/health`, and all admin endpoints.

nginx routes:
```nginx
location ~ ^/[A-Za-z0-9]{7}$ {
    proxy_pass http://rust-redirect;   # Rust handles redirects
}
location / {
    proxy_pass http://python-app;      # Python handles everything else
}
```

### Benchmark comparison methodology

Run `make bench` against both stacks with identical Redis/DB state:
```bash
# Python stack
BENCH_BASE_URL=http://localhost:8080 make bench > /tmp/python_bench.txt

# Rust stack (different port)
BENCH_BASE_URL=http://localhost:8090 make bench > /tmp/rust_bench.txt

# Compare
python scripts/bench_regression_check.py \
  --results /tmp/rust_bench.txt \
  --baselines docs/bench_baselines.json \
  --tolerance -1.0   # negative tolerance = must be FASTER than baseline
```

---

## Phase 4 — Performance Gaps in Current v1.0.0

### Identified bottlenecks (from benchmark data)

| Bottleneck | Observed | Root cause | Fix |
|---|---|---|---|
| Writer RPS low (77 RPS) | High error rate under load | Kafka publish blocks on slow broker | Make Kafka publish fully async with fire-and-forget |
| Reader RPS ceiling (459 RPS) | Nginx + 3 Python replicas | Python GIL limits per-process concurrency | Rust redirect service (Phase 3) |
| Celebrity/hot-key reads | ~228 RPS (same as reader) | Cache hit but still goes through Python | Rust + in-process LRU cache (no Redis round-trip) |
| Click counting | Redis INCR per click | Synchronous, one round-trip per request | Batch in-memory counter, flush every N ms |
| Kafka consumer lag | Unknown | Not measured in CI | Add consumer lag metric to Prometheus |

### Quick wins (no language change)

1. **Fire-and-forget Kafka publish** — don't await the producer send in the request path.
   Use `asyncio.create_task` and let failures be logged, not propagated.

2. **In-process LRU cache** — add `cachetools.TTLCache` (1000 entries, 10s TTL) in front
   of Redis for the redirect handler. Eliminates Redis round-trip for hot URLs.

3. **Connection pool tuning** — current `pool_size=20, max_overflow=10`. Under 60 concurrent
   readers, this is fine. At 200+ concurrent, increase to `pool_size=50, max_overflow=20`.

4. **Nginx worker tuning** — current nginx config uses default `worker_processes auto`.
   Set `worker_connections 4096` and `keepalive 32` on upstream blocks.

---

## Phase 5 — Observability Gaps

| Gap | Current state | Target |
|---|---|---|
| Kafka consumer lag | Not tracked | Prometheus `kafka_consumer_lag` gauge |
| Redis memory usage | Not tracked | Alert when >80% of `maxmemory` |
| ClickHouse ingest rate | Not tracked | Rows/s gauge in ingestion worker |
| P99 latency | Not tracked | Add `prometheus-fastapi-instrumentator` histogram |
| Error rate by endpoint | Not tracked | Prometheus counter per route + status code |

---

## Milestone Summary

| Milestone | Status | Key metric |
|---|---|---|
| v1.0.0 — Python stack, full CI/CD | ✅ Done | 77 writer RPS, 459 reader RPS, all tests green |
| v1.1.0 — Quick wins (LRU, fire-and-forget Kafka) | Planned | Target: 150 writer RPS, 700 reader RPS |
| v1.2.0 — ScyllaDB write path | Planned | Target: 500+ writer RPS |
| v2.0.0 — Rust redirect service | Planned | Target: 3000+ reader RPS |
| v2.1.0 — Full observability (P99, lag, ingest rate) | Planned | — |
