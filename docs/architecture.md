# Architecture

## Overview

This project runs a **distributed URL shortener platform** with:

- load-balanced stateless app nodes,
- split OLTP and OLAP responsibilities,
- asynchronous click ingestion,
- dedicated key-generation service,
- multi-layer observability and load testing.

It is designed to keep redirect latency low while preserving high write throughput and analytics fidelity.

## End-to-End Architecture Diagram

![URL Shortener Architecture](./diagrams/architecture.svg)

Static SVG: [`docs/diagrams/architecture.svg`](./diagrams/architecture.svg)

```mermaid
flowchart LR
    C[Clients / Browsers / API users]

    subgraph EDGE[Edge Layer]
      LB[Nginx Load Balancer]
    end

    subgraph APP[Application Layer]
      A1[app1 FastAPI]
      A2[app2 FastAPI]
      A3[app3 FastAPI]
      KG[keygen service]
      CW[cache-warmer worker]
    end

    subgraph DATA_OLTP[OLTP + Cache]
      R[(Redis primary)]
      RR[(Redis replica)]
      PG[(PostgreSQL)]
      KGR1[(keygen redis primary)]
      KGR2[(keygen redis secondary)]
    end

    subgraph STREAM[Streaming + Ingestion]
      KAFKA[(Kafka / Redpanda)]
      I1[ingestion-1]
      I2[ingestion-2]
      I3[ingestion-3]
    end

    subgraph DATA_OLAP[Analytics]
      CH[(ClickHouse)]
      CHUI[ClickHouse SQL UI]
    end

    subgraph OBS[Observability + Load]
      LOC[Locust UI + generator]
      PROM[(Prometheus)]
      GRAF[Grafana boards]
      DOZ[Dozzle logs]
    end

    C --> LB
    LB --> A1
    LB --> A2
    LB --> A3

    A1 --> R
    A2 --> R
    A3 --> R
    R --> RR

    A1 --> PG
    A2 --> PG
    A3 --> PG

    A1 --> KAFKA
    A2 --> KAFKA
    A3 --> KAFKA

    KAFKA --> I1
    KAFKA --> I2
    KAFKA --> I3

    I1 --> PG
    I2 --> PG
    I3 --> PG

    I1 --> CH
    I2 --> CH
    I3 --> CH

    A1 --> KG
    A2 --> KG
    A3 --> KG
    KG --> KGR1
    KG --> KGR2

    CW --> PG
    CW --> R

    LOC --> LB

    A1 -. metrics .-> PROM
    A2 -. metrics .-> PROM
    A3 -. metrics .-> PROM
    I1 -. metrics .-> PROM
    I2 -. metrics .-> PROM
    I3 -. metrics .-> PROM
    CH -. exporter .-> PROM
    PROM --> GRAF

    CH --> CHUI
    DOZ -. docker logs .- EDGE
    DOZ -. docker logs .- APP
    DOZ -. docker logs .- STREAM
```

## Core Runtime Flows

### 1) Shorten URL (`POST /api/shorten`)

1. Client hits LB -> routed to one app node.
2. App requests a short-code range block from `keygen` when local block exhausts.
3. App validates uniqueness in Postgres.
4. URL mapping persisted in Postgres.
5. Cache entry populated in Redis.

### 2) Redirect (`GET /{short_code}`)

1. App checks Redis cache (`url:{short_code}`).
2. On miss: fetches from Postgres and warms cache.
3. Redirect response returns `307`.
4. Click event published to Kafka (fallback Redis stream available).
5. Near-real-time buffered click value stays in Redis for quick stats reads.

### 3) Ingestion / Analytics

1. Ingestion workers consume Kafka `click_events`.
2. They aggregate deltas in Redis hash.
3. Every 5 seconds, aggregated batch flushes to:
   - Postgres `urls.clicks` (OLTP truth for API stats),
   - ClickHouse `click_events` (analytics store).

## Service Inventory

| Layer | Services |
|---|---|
| Edge | `load-balancer` |
| App | `app1`, `app2`, `app3`, `keygen`, `cache-warmer` |
| OLTP | `db`, `redis`, `redis-replica`, `keygen-redis-primary`, `keygen-redis-secondary` |
| Stream | `kafka`, `ingestion-1`, `ingestion-2`, `ingestion-3` |
| OLAP | `clickhouse`, `clickhouse-dashboard` |
| Observability | `prometheus`, `grafana`, `dozzle` |
| Load generation | `load-ui`, `request-generator`, `request-generator-100k`, `request-generator-dist-master`, `request-generator-dist-worker` |

## Data Stores and Responsibility Split

| Store | Role | Notes |
|---|---|---|
| PostgreSQL | Source of truth for URL mappings + persisted click totals | ACID, indexed lookup by `short_code` |
| Redis | Low-latency cache + click aggregation buffers | Fast reads and temporary counters |
| Kafka | Durable click event transport | Decouples redirect path from write-heavy ingestion |
| ClickHouse | Analytics and reporting | Optimized for high-volume append and aggregate queries |

## Observability Surfaces

| UI | URL | Primary Use |
|---|---|---|
| Grafana | `http://localhost:3000` | Unified architecture board + service flow rates |
| Prometheus | `http://localhost:9090` | Raw metrics, target health, query debugging |
| Locust | `http://localhost:8089` | Live traffic generation + latency/failure during tests |
| ClickHouse UI | `http://localhost:8088` | Direct SQL analytics exploration |
| Dozzle | `http://localhost:9999` | Container logs and runtime behavior |
