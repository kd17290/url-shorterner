# Scaling Strategy

## Current Baseline

Current stack is already distributed:

- Nginx load balancer
- 3 FastAPI app nodes
- Redis cache + replica
- PostgreSQL OLTP
- Kafka + 3 ingestion consumers
- ClickHouse OLAP
- Prometheus/Grafana/Dozzle for visibility

This baseline is suitable for high read-heavy workloads with asynchronous click ingestion.

---

## Scaling Phases, Scope, and Drawbacks

| Phase | Primary Goal | Scope | Gains | Drawbacks / Limits | Trigger for Next Phase |
|---|---|---|---|---|---|
| Phase A | Single-cluster horizontal scale | One region / one cluster | Simple operations, low latency within cluster | Regional outage risk, manual scaling limits | Frequent saturation or multi-region need |
| Phase B | Data-plane optimization | Cache, queue, ingestion throughput | Better p95/p99, lower OLTP pressure | Higher infra complexity and lag windows | Queue lag, cache churn, or hotspot pressure |
| Phase C | Storage scaling | OLTP read/write scaling and partitioning | Higher sustained throughput, better isolation | Rebalancing and operational complexity | Primary DB bottlenecks or storage growth |
| Phase D | Global resilience | Multi-region HA and failover | Improved disaster tolerance and geo latency | Highest complexity and cost | Strict global SLO/RTO requirements |

---

## Dimension-by-Dimension Strategy

### 1) Read Path (Redirect-heavy)

**Current strategy**
- Redis cache-aside + cache warmer + LB fanout.

**Scope**
- Works well while hot keys remain manageable within Redis + app fleet.

**Drawbacks**
- Hot-key skew can still create uneven node pressure.
- Cache invalidation race conditions under rapid mutation.

**Next upgrades**
1. CDN edge cache for immutable redirects.
2. L1 in-process caches for hottest short codes.
3. Hot-key detection and pinning policy.

---

### 2) Write Path (Click tracking)

**Current strategy**
- App publishes click events to Kafka.
- Ingestion workers aggregate in Redis and flush every 5s to Postgres + ClickHouse.

**Scope**
- Strong for bursty traffic and large read/write asymmetry.

**Drawbacks**
- Eventual consistency window (few seconds).
- Needs queue lag monitoring and backpressure controls.

**Next upgrades**
1. Dynamic flush intervals based on lag.
2. Idempotent event keys for exactly-once semantics in analytics path.
3. Tiered ingestion with dedicated OLTP and OLAP queues if needed.

---

### 3) App Layer Scaling

**Current strategy**
- Stateless app replicas behind Nginx.

**Scope**
- Horizontal scale out for CPU/network-bound API load.

**Drawbacks**
- Manual scaling in compose environments.
- No automatic pod/node recovery policy tuning.

**Next upgrades**
1. Kubernetes deployment + HPA.
2. Per-route autoscaling signals (redirect vs shorten).
3. Service mesh for richer traffic policy.

---

### 4) OLTP Database Scaling

**Current strategy**
- Single PostgreSQL primary with async-heavy app behavior.

**Scope**
- Good until sustained write throughput and connection pressure grow.

**Drawbacks**
- Single-primary write ceiling.
- Failover and scaling are operationally sensitive.

**Next upgrades**
1. PgBouncer + read replicas.
2. Table/index tuning and partitioning.
3. Citus-based horizontal scaling when primary bottlenecks persist.

---

### 5) Cache Tier Scaling

**Current strategy**
- Single Redis primary + replica.

**Scope**
- Good for moderate-to-high cache throughput in one region.

**Drawbacks**
- Memory-bound and shard hotspot risk.
- Single-cluster blast radius.

**Next upgrades**
1. Redis Sentinel for managed failover.
2. Redis Cluster for horizontal shard scale.
3. Multi-region cache policy for global traffic.

---

### 6) Analytics Scaling

**Current strategy**
- ClickHouse stores click events and aggregations.

**Scope**
- Excellent for append-heavy analytics and aggregate queries.

**Drawbacks**
- Requires ingestion/schema lifecycle management.
- Retention and partition strategy must be explicit.

**Next upgrades**
1. Materialized views for fast top-N and time buckets.
2. TTL + partition pruning for retention control.
3. Separate hot/cold analytics tiers.

---

## Capacity Planning Lens

Use these operational indicators to decide when to scale next:

| Signal | Meaning | Typical Action |
|---|---|---|
| `http_requests_total` p95 latency climb | App tier saturation | Add app replicas / tune LB |
| Kafka consumer lag growth | Ingestion under-provisioned | Add partitions/consumers; tune flush |
| Redis memory pressure | Cache saturation | Tune TTL/eviction; add Redis cluster |
| Postgres write latency/locks | OLTP bottleneck | Batch more aggressively; replicas/Citus |
| ClickHouse insert/query contention | Analytics pressure | Partitioning + materialized views |

---

## Practical Progression Recommendation

1. Keep current distributed baseline and monitor lag/latency SLOs.
2. Add read replicas + PgBouncer before major OLTP replatforming.
3. Move to Citus when write and storage growth exceed single-primary comfort.
4. Add CDN + multi-region controls only when global traffic/SLOs demand it.

---

## 100k RPS Load Test Runbook

### Goal
- Stress request generation toward `~100,000 rps` aggregate using Locust profile controls.

### Command
```bash
make orchestrator-100k
```

### Core tuning levers
| Variable | Meaning | Default |
|---|---|---|
| `REQUEST_GENERATOR_USERS_100K` | Total Locust users | `5000` |
| `REQUEST_GENERATOR_SPAWN_RATE_100K` | User ramp-up per second | `1000` |
| `REQUEST_GENERATOR_PROCESSES_100K` | Locust worker processes in container | `4` |
| `TARGET_READ_USERS_100K` | Reader user count | `4000` |
| `TARGET_WRITE_USERS_100K` | Writer user count | `1000` |
| `TARGET_READ_RPS_PER_USER_100K` | Per-reader throughput | `20` |
| `TARGET_WRITE_RPS_PER_USER_100K` | Per-writer throughput | `20` |

### Practical constraints / drawbacks
- Single-machine Docker commonly bottlenecks before sustained 100k.
- Generator CPU saturation can under-report achievable backend capacity.
- High spawn rate can create transient errors unrelated to steady-state service behavior.

### Recommended practice
1. Start with `make boards` for observability.
2. Run `make orchestrator-100k`.
3. Watch Grafana Architecture Flow + Prometheus for true observed rates.
4. If capped, scale load generation horizontally (multiple Locust agents).

### Distributed run (master + workers)
```bash
REQUEST_GENERATOR_WORKERS_DIST=8 \
REQUEST_GENERATOR_USERS_DIST=100000 \
REQUEST_GENERATOR_SPAWN_RATE_DIST=5000 \
REQUEST_GENERATOR_DURATION_DIST=10m \
TARGET_READ_USERS_DIST=95000 \
TARGET_WRITE_USERS_DIST=5000 \
TARGET_READ_RPS_PER_USER_DIST=1 \
TARGET_WRITE_RPS_PER_USER_DIST=1 \
make orchestrator-100k-dist
```

- `REQUEST_GENERATOR_WORKERS_DIST` controls worker replica count.
- `REQUEST_GENERATOR_HOST_DIST` defaults to `http://host.docker.internal:8080` for no-deps load runs.
