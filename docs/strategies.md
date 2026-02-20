# Design Strategies & Trade-offs

This document discusses the key design decisions in building a URL shortener, comparing alternative approaches and their trade-offs.

## Strategy Catalog (Current State)

| Area | Current Strategy | Scope | Benefits | Drawbacks | When to Upgrade |
|---|---|---|---|---|---|
| Edge routing | Nginx LB across 3 app nodes | North-south HTTP traffic distribution | Simple, transparent failover, easy local reproducibility | No smart autoscaling decisions, less feature-rich than cloud LB/WAF | Move to managed LB + WAF at internet scale |
| App scalability | Stateless FastAPI replicas | API concurrency and horizontal scaling | Easy replication, no sticky session dependency | Needs external state stores for everything | Add autoscaling policies and service mesh at larger fleets |
| Key generation | Dedicated keygen service + allocator ranges | Short-code uniqueness under concurrency | Collision-free by design, low per-request latency | Allocator dependency, IDs can be enumerable unless obfuscated | Add multi-region allocator or ID obfuscation if needed |
| Keygen HA | Primary/secondary Redis failover | Key allocation continuity | Fast failover path, isolated from app Redis | Operational overhead, replication consistency concerns | Use Redis Sentinel/Cluster or managed Redis failover |
| Read cache | Redis cache-aside + cache warmer | Redirect latency and DB offload | High hit rates for hot keys, lower DB read pressure | Cache invalidation complexity, stale windows | Add CDN/edge cache and tiered local in-memory cache |
| Click capture | Async Kafka event publish from app | Redirect-path write decoupling | Keeps redirect path light, durable queue semantics | Queue operations and consumer lag add ops complexity | Add partition strategy by key and idempotent producers |
| Ingestion | 3 workers + Redis batching + 5s flush | Click aggregation pipeline | Batches reduce OLTP/OLAP write amplification | Eventual consistency window; burst lag visibility required | Tune flush interval or adopt adaptive dynamic batching |
| OLTP store | PostgreSQL (URL truth + persisted clicks) | Transactional API correctness | Mature ACID semantics, excellent tooling | Single-primary write ceiling without extensions | Add replicas first, then Citus/sharding for high writes |
| OLAP store | ClickHouse for analytics | High-volume event analytics | Efficient append + aggregation, cheap analytical scans | Additional pipeline and schema management overhead | Add retention tiers and materialized views at scale |
| Observability | Prometheus + Grafana + Dozzle | Metrics, dashboards, log visibility | Unified visibility and fast incident triage | Requires curation of metrics quality and dashboards | Add tracing (OTel/Tempo/Jaeger) and alert SLO packs |
| Load validation | Locust live UI + generator service | Synthetic traffic and regression checks | Repeatable and visual load tests | Synthetic patterns may diverge from production behavior | Add replayed traffic profiles and chaos scenarios |

### Scope interpretation

- **Scope** describes the boundary where a strategy is expected to operate effectively.
- **Drawbacks** are not blockers; they are signals for the next architectural step.
- **When to upgrade** indicates the threshold where an alternative strategy becomes justified.

---

## 1. Short Code Generation

### Option A: Nanoid (Chosen ✅)
Random string generation using a cryptographically secure alphabet.

```
Input:  https://www.google.com
Output: aB3xK9m  (random, no relation to input)
```

| Pros | Cons |
|---|---|
| No coordination needed between instances | Collision possible (astronomically unlikely) |
| URL-safe characters | No deterministic mapping |
| Configurable length | Requires uniqueness check |
| Fast generation | |

### Option B: Base62 Encoding of Auto-Increment ID

```
Input:  DB ID 12345
Output: dnh  (base62 encoded)
```

| Pros | Cons |
|---|---|
| Deterministic, no collisions | Predictable/enumerable (security risk) |
| Compact codes | Requires centralized counter |
| Simple implementation | Hard to scale across DB shards |

### Option C: MD5/SHA Hash Truncation

```
Input:  https://www.google.com
Output: First 7 chars of MD5 hash
```

| Pros | Cons |
|---|---|
| Deterministic (same URL → same code) | Higher collision rate with truncation |
| No DB lookup for dedup | Fixed output for same input (no multiple short URLs) |
| | Hash computation overhead |

### Option D: Pre-generated Key Pool

```
Background worker generates keys → Key Pool (Redis/DB) → API pops a key
```

| Pros | Cons |
|---|---|
| Zero-latency key generation at request time | Requires background worker |
| No collision checks needed | Pool exhaustion risk under burst |
| Scales well | Added infrastructure complexity |

### Option E: Counter Range Allocation + Base62 (Recommended for hyperscale)

```
ID Service (or Redis INCRBY) allocates ranges (e.g., 10k IDs) to each app instance.
App instance encodes IDs locally to fixed-length base62 (e.g., 8 chars).
```

| Pros | Cons |
|---|---|
| No collisions by design | Requires central allocator service/key |
| Very low latency per request (no per-request coordination) | IDs can be enumerable unless obfuscated |
| Easy horizontal scaling with batched range fetches | Needs careful handling of allocator outages |
| Simple observability/debugging | |

### Recommendation
- **Small-medium scale**: Nanoid (current choice) — simple, fast, practically collision-free
- **Large scale**: Counter range allocation + Base62 — deterministic, collision-free, operationally simpler than key pools

---

## 1A. High-Scale Context (Target: 4B reads/day, 1000:1 read/write)

### Capacity Translation

| Metric | Value |
|---|---|
| Reads/day | 4,000,000,000 |
| Average reads/sec | ~46,300 rps |
| Peak planning factor | 5-10x |
| Peak reads/sec target | ~230k to ~460k rps |
| Writes/day (1000:1) | ~4,000,000 |
| Average writes/sec | ~46 rps |

### Key implication
At this scale, **read path resilience and hot-key handling** dominate overall system design. DB writes become critical mainly for analytics/click recording if implemented synchronously.

---

## 2. Database Choice

### Option A: PostgreSQL (Chosen ✅)

| Pros | Cons |
|---|---|
| ACID compliance | Vertical scaling limits |
| Mature ecosystem | Slower than NoSQL for simple key-value |
| Rich indexing | Schema migrations needed |
| Strong consistency | |

### Option B: MongoDB

| Pros | Cons |
|---|---|
| Flexible schema | Weaker consistency guarantees |
| Horizontal scaling (sharding) | Less efficient for relational queries |
| JSON-native | Higher storage overhead |

### Option C: DynamoDB / Cassandra

| Pros | Cons |
|---|---|
| Massive horizontal scale | Eventually consistent (by default) |
| Single-digit ms latency | Limited query flexibility |
| Managed (DynamoDB) | Vendor lock-in (DynamoDB) |

### Option D: Redis Only (No persistent DB)

| Pros | Cons |
|---|---|
| Fastest possible reads | Data loss risk (even with AOF) |
| Simplest architecture | Memory-bound storage |
| | No complex queries |

### Recommendation
- **Learning/production**: PostgreSQL — battle-tested, excellent tooling
- **Massive scale**: DynamoDB/Cassandra — if you need millions of writes/sec

---

## 3. Caching Strategy

### Option A: Read-Through Cache (Chosen ✅)

```
Request → Check Redis → MISS → Query DB → Store in Redis → Return
                      → HIT  → Return from Redis
```

| Pros | Cons |
|---|---|
| Simple implementation | First request always slow (cold cache) |
| Automatic cache population | Stale data possible within TTL |
| Reduces DB load | |

### Option B: Write-Through Cache

```
Write → Update DB + Update Redis simultaneously
Read  → Always read from Redis
```

| Pros | Cons |
|---|---|
| Cache always fresh | Write latency increases |
| No cache misses after write | More complex write path |

### Option C: Write-Behind (Write-Back) Cache

```
Write → Update Redis → Async flush to DB
Read  → Always read from Redis
```

| Pros | Cons |
|---|---|
| Fastest writes | Data loss risk if Redis crashes before flush |
| Lowest write latency | Complex consistency management |

### Option D: Cache-Aside with TTL

```
Read  → Check cache → MISS → App queries DB → App writes cache
Write → App writes DB → App invalidates cache
```

| Pros | Cons |
|---|---|
| Full control over caching logic | More application code |
| Can handle complex invalidation | Potential race conditions |

### Recommendation
- **URL shortener**: Read-through with TTL — reads dominate, slight staleness is acceptable

---

## 4. Redirect HTTP Status Code

### 301 Moved Permanently
- Browser caches the redirect
- Subsequent requests skip your server entirely
- **No analytics possible** after first visit

### 302 Found
- Temporary redirect
- Browser doesn't cache
- Analytics work, but semantically incorrect

### 307 Temporary Redirect (Chosen ✅)
- Preserves HTTP method (POST stays POST)
- Browser doesn't cache
- Analytics work correctly
- Semantically correct for URL shorteners

### 308 Permanent Redirect
- Like 301 but preserves HTTP method
- Browser caches — same analytics problem as 301

### Recommendation
- **With analytics**: 307 (current choice)
- **Without analytics / max performance**: 301 (let browsers cache)

---

## 5. Rate Limiting (Phase 3)

### Option A: Token Bucket
- Smooth rate limiting
- Allows bursts up to bucket size
- Most common choice

### Option B: Fixed Window
- Simple implementation
- Can allow 2x burst at window boundary

### Option C: Sliding Window Log
- Most accurate
- Higher memory usage
- No boundary burst issue

### Option D: Sliding Window Counter
- Approximation of sliding window
- Low memory
- Good balance of accuracy and performance

### Recommendation
- **API creation endpoint**: Token bucket (allow small bursts)
- **Redirect endpoint**: Sliding window counter (high throughput needed)

---

## 6. URL Validation

### Option A: Regex Validation (Chosen ✅ via `validators` library)
- Checks URL format
- Fast, no network call
- Can't verify URL actually exists

### Option B: HEAD Request Validation
- Verifies URL is reachable
- Slow (network call)
- May be blocked by target server
- Adds latency to creation

### Option C: DNS Resolution Only
- Verifies domain exists
- Faster than full HEAD request
- Doesn't verify full path

### Recommendation
- **Default**: Regex validation (fast, sufficient)
- **Optional**: Async HEAD request as background check (don't block creation)

---

## 7. High-Scale Risk Register: Issues and Strategy Options

### 7.1 Hot key / Celebrity traffic

| Strategy | Pros | Cons |
|---|---|---|
| Single Redis layer only | Simple | Hot shard saturation, poor tail latency |
| Multi-layer cache (CDN + L1 in-process + Redis) | Massive offload, lower p99 | More moving parts, cache coherence complexity |
| Hot-key replication/pinning | Protects primary shard | Operational complexity, skew management |
| Request coalescing (singleflight) | Prevents cache stampede | Slight waiting under miss storms |

**Recommended:** Multi-layer cache + request coalescing + hot-key detection/pinning.

### 7.2 Cache stampede / thundering herd

| Strategy | Pros | Cons |
|---|---|---|
| Fixed TTL | Easiest | Simultaneous expiries cause spikes |
| TTL jitter | Very low cost mitigation | Does not fully solve hot misses |
| Soft TTL + background refresh | Better p99, fewer miss storms | More background traffic |
| Distributed per-key lock | Strong protection | Lock contention/failure edge-cases |

**Recommended:** TTL jitter + per-key lock + stale-while-revalidate for top keys.

### 7.3 High DB write pressure from click updates

| Strategy | Pros | Cons |
|---|---|---|
| Synchronous `clicks += 1` in OLTP DB | Simple, exact immediate value | Bottleneck at high QPS, lock contention |
| Redis INCR + periodic flush | Fast, reduced DB load | Lag, reconciliation needed |
| Event stream (Kafka/Pulsar) + async aggregation | Highest scalability, decoupled | Added infra and operational complexity |
| Batch UPSERT windows | Efficient writes | Delayed visibility |

**Recommended:** Event stream + batched aggregator for production hyperscale.

### 7.4 Unique short-code generation at scale

| Strategy | Pros | Cons |
|---|---|---|
| Nanoid + uniqueness check | Simple, stateless generation | Collision check roundtrip, harder at extreme throughput |
| DB sequence + base62 | Collision-free, simple | Central DB bottleneck at scale |
| Pre-generated token pool | Fast request path | Pool refill/exhaustion complexity |
| **Range allocator (INCRBY) + base62** | Collision-free + low latency + scalable | Central allocator dependency |

**Recommended:** Range allocator + base62 (8 chars) as default hyperscale strategy.

### 7.5 Redis availability and failover

| Strategy | Pros | Cons |
|---|---|---|
| Single Redis instance | Simple | SPOF |
| Sentinel | Automatic failover | Not horizontal sharding |
| Redis Cluster | Horizontal scale + HA | Cluster ops complexity |
| Multi-region active-active cache | Regional resilience | High complexity, conflict handling |

**Recommended:** Redis Cluster for scale, optionally paired with Sentinel-style failover controls.

### 7.6 DB growth and partitioning

| Strategy | Pros | Cons |
|---|---|---|
| Single primary + replicas | Good starting point | Primary write ceiling |
| Hash sharding by short_code | Horizontal write/read scale | Rebalancing complexity |
| Time partitioning (analytics tables) | Efficient retention/queries | Not ideal for point lookups alone |
| Hybrid OLTP + OLAP split | Best performance isolation | Extra pipeline complexity |

**Recommended:** Keep URL mapping in OLTP; move analytics to partitioned OLAP/warehouse path.

### 7.7 Abuse, bots, and DDoS

| Strategy | Pros | Cons |
|---|---|---|
| API-only rate limiting | Easy | Too late if edge already saturated |
| WAF + edge rate limiting | Early drop, protects origin | Added cost/tuning |
| Proof-of-work/challenge for suspicious traffic | Strong abuse control | UX impact |
| IP/ASN reputation lists | Fast blocking | False positives risk |

**Recommended:** Edge WAF + adaptive per-tenant/per-IP limits + anomaly detection.

### 7.8 Consistency and stale redirects

| Strategy | Pros | Cons |
|---|---|---|
| Long TTL only | Fewer DB reads | Stale redirects after updates/deletes |
| Write-through updates | Better freshness | Higher write latency |
| Invalidation events | Fresh + scalable | Requires robust event delivery |
| Versioned cache keys | Avoids stale overwrite races | More storage/churn |

**Recommended:** Invalidation events + short TTL for mutable records.

### 7.9 Observability and SLO blind spots

| Strategy | Pros | Cons |
|---|---|---|
| Basic logs only | Easy start | Poor incident triage |
| Metrics + tracing + structured logs | Full visibility | Higher setup cost |
| RED/USE dashboards + alerting | SLO-oriented operations | Requires ongoing tuning |
| Synthetic probes + chaos drills | Proactive resilience testing | Operational overhead |

**Recommended:** Instrument SLOs (p95/p99 latency, error rate, cache hit rate, queue lag, allocator lag).

---

## 8. Final Recommendations for 4B/day Goal

1. **Read path:** CDN + Redis Cluster + local cache + anti-stampede controls.
2. **Write path:** asynchronous click events with batched aggregation (no sync DB increment in redirect path).
3. **Code generation:** range allocator (`INCRBY`) + fixed-length base62.
4. **Data architecture:** OLTP for mapping, OLAP/stream pipeline for analytics.
5. **Operations:** rate limiting at edge, multi-AZ cache/DB, strong observability and load/chaos testing.
