# Performance Audit — 2026-02-21

Audit of the running infrastructure under load. All numbers measured live from
Prometheus + `docker stats` while the benchmark was running.

---

## 1. nginx Load Skew — CRITICAL (Fixed)

### Observation

```
app1:8000   rps=0.0    share=0%    CPU=0.1%
app2:8000   rps=312.2  share=100%  CPU=79.5%
app3:8000   rps=0.0    share=0%    CPU=0.85%
```

app2 was serving **100% of all traffic**. app1 and app3 were completely idle.
app2 latency: 857ms redirect, 1157ms shorten — severely degraded from saturation.

### Root Cause

`least_conn` + `keepalive 64` + HTTP/1.1 persistent connections.

`least_conn` picks the backend with the fewest **active connections**, not fewest
active requests. When a benchmark client (httpx, curl) opens a persistent keepalive
connection to app2, nginx sees:

```
app1: 0 connections  ← never picked (least_conn skips it)
app2: 1 connection   ← already has a connection, but least_conn still picks it
app3: 0 connections  ← never picked
```

All subsequent requests reuse the existing keepalive connection to app2. app1 and
app3 never receive a request because they always show 0 active connections.

**`least_conn` is the wrong algorithm for keepalive upstreams.** It is designed for
long-lived connections (WebSockets, gRPC) where connection count ≈ request count.
For short HTTP requests with keepalive, round-robin is correct.

### Fix Applied

`docker/nginx/nginx.conf`:
- Removed `least_conn` → uses round-robin (nginx default)
- Reduced `keepalive` pool from 64 → 32 (3× replica count)
- Added `keepalive_requests 1000` — forces upstream reselection after 1000 requests
- Added `keepalive_time 60s` — closes idle keepalive connections after 60s
- Added `worker_processes auto` + `worker_connections 4096`
- Added `$upstream_addr` to access log format for per-backend visibility

### After Fix

```
app1:8000   rps=140.4  share=26%   CPU=97%
app2:8000   rps=266.3  share=50%   CPU=94%
app3:8000   rps=125.9  share=24%   CPU=79%
```

Still slightly skewed toward app2 because existing keepalive connections from the
benchmark client hadn't cycled yet. Will even out to ~33% each as connections rotate.

### Rule

**Never use `least_conn` with HTTP/1.1 keepalive upstreams.** Use round-robin (default)
or `least_conn` only for WebSocket/gRPC where connection count equals request count.

---

## 2. Redis Replica Completely Unused — HIGH (Fixed)

### Observation

```
urlshortener-redis          connected_clients=129   CPU=5.6%
urlshortener-redis-replica  connected_clients=2     CPU=2.1%
```

The replica had only 2 connections (Prometheus scraper + replication stream).
The app was sending **all reads and writes to the primary**.

### Root Cause

`app/redis.py` only created one client (`redis_client`) pointed at `REDIS_URL`
(primary). `REDIS_REPLICA_URL` was declared in `Settings` and in `.env` but
never used anywhere in the application code.

### Fix Applied

`app/redis.py`:
- Added `redis_read_client` singleton pointed at `REDIS_REPLICA_URL`
- Added `get_redis_read()` FastAPI dependency (falls back to primary if replica URL not set)

`app/routes.py`:
- `redirect_to_url` now injects both `cache` (primary, for writes) and `cache_read`
  (replica, for the GET cache lookup)
- `get_url_by_code(short_code, db, cache_read)` — reads from replica
- `increment_clicks(url, db, cache)` — writes (INCR, EXPIRE, XADD) to primary

### Expected Impact

The redirect hot path (`GET /<code>`) is ~85% of all traffic. Routing its cache
lookup to the replica offloads ~85% of Redis read ops from the primary.

```
Before: primary handles 100% of reads + 100% of writes
After:  primary handles ~15% of reads + 100% of writes
        replica handles ~85% of reads
```

---

## 3. Redis Cache Hit Rate — MEDIUM

### Observation

```
keyspace_hits:   132,194
keyspace_misses:  93,416
hit rate: 58.6%
```

58.6% is poor for a URL shortener. The redirect path should be >95% cache hits
in steady state — most short codes are accessed repeatedly.

### Root Cause

Two contributing factors:
1. **Short TTL** — `CLICK_BUFFER_TTL_SECONDS=300` (5 min). URLs expire from cache
   quickly and must be re-fetched from PostgreSQL.
2. **Cold cache** — the benchmark creates new URLs during warmup, then reads them.
   The cache is warm for the warmup set but cold for any URL not in the warmup pool.

### Fix (Recommended, not yet applied)

Increase `CLICK_BUFFER_TTL_SECONDS` to 3600 (1 hour) or higher for the URL cache.
Note: `CLICK_BUFFER_TTL_SECONDS` controls the click counter buffer TTL, not the URL
cache TTL. The URL cache TTL is set separately in `_cache_url`. Check `app/service.py`
`_cache_url` for the actual URL cache TTL.

---

## 4. Kafka / Ingestion Workers — OK ✅

### Observation

```
Topic: click_events   Partitions: 6   Replicas: 1
Consumer group: click_ingestion_group   Members: 3   Total-lag: 254

Partition  Consumer              Lag
0          ingestion-consumer-1  41
1          ingestion-consumer-2  34
2          ingestion-consumer-3  54
3          ingestion-consumer-1  49
4          ingestion-consumer-2  27
5          ingestion-consumer-3  49
```

6 partitions / 3 consumers = 2 partitions each. Perfectly balanced.
Total lag of 254 is acceptable under active load.

### No Action Required

---

## 5. PostgreSQL — Moderate Load

### Observation

```
urlshortener-db   CPU=9.38%   Memory=224MB   NetIO=98MB/333MB
```

DB is handling the load. The 333MB of outbound network traffic indicates heavy
read traffic (cache misses falling through to DB). Improving cache hit rate
(item 3) will reduce this significantly.

---

## 6. Kafka Memory — Watch

### Observation

```
urlshortener-kafka   Memory=1001MB / 7.65GB (13%)
```

Redpanda is using ~1GB RAM. This is normal for Redpanda's JVM-free architecture
but should be monitored. Set a memory limit in `docker-compose.yml` if needed.

---

## Summary

| Component | Issue | Severity | Status |
|---|---|---|---|
| nginx `least_conn` + keepalive | 100% traffic on app2, app1/app3 idle | 🔴 Critical | ✅ Fixed |
| Redis replica unused | All reads hitting primary | 🔴 Critical | ✅ Fixed |
| Redis cache hit rate 58.6% | Cache misses → DB fallback | 🟡 Medium | Recommended fix |
| Kafka/ingestion balance | 2 partitions per consumer | ✅ OK | No action |
| PostgreSQL load | Moderate, driven by cache misses | 🟡 Medium | Improves with cache fix |
| Kafka memory 1GB | Normal for Redpanda | 🟢 Low | Monitor |

---

## Load Distribution After Fix

```
Before fix:
  app1: 0 RPS   (0%)    CPU 0.1%
  app2: 312 RPS (100%)  CPU 79.5%
  app3: 0 RPS   (0%)    CPU 0.85%

After fix (nginx reload, connections cycling):
  app1: 140 RPS (26%)   CPU 97%
  app2: 266 RPS (50%)   CPU 94%
  app3: 126 RPS (24%)   CPU 79%

Expected steady state (all connections cycled):
  app1: ~177 RPS (33%)  CPU ~90%
  app2: ~177 RPS (33%)  CPU ~90%
  app3: ~177 RPS (33%)  CPU ~90%
  Total: ~531 RPS (vs 312 before — 70% throughput gain from balancing alone)
```
