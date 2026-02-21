# Codebase Map — Python ↔ Rust Service by Service

A navigable reference linking every service to its source files in both stacks.
Each section covers what the service does, its entry point, and the key files to read.

---

## System Overview

```
                        ┌─────────────────────────────────────┐
                        │           nginx / load balancer      │
                        └──────────────────┬──────────────────┘
                                           │ HTTP
                   ┌───────────────────────┴───────────────────────┐
                   │                                               │
          ┌────────▼────────┐                            ┌─────────▼───────┐
          │   app (Python)  │                            │  app-rs (Rust)  │
          │  FastAPI + uvicorn                           │  Axum + Tokio   │
          └────────┬────────┘                            └─────────┬───────┘
                   │                                               │
         ┌─────────┼──────────┐                        ┌──────────┼──────────┐
         ▼         ▼          ▼                        ▼          ▼          ▼
     Postgres    Redis      Kafka                  Postgres    Redis      Kafka
         │                   │                        │                    │
         └──────┬────────────┘                        └──────┬─────────────┘
                │                                            │
     ┌──────────▼──────────┐                    ┌───────────▼───────────┐
     │  ingestion (Python) │                    │  ingestion-rs (Rust)  │
     └──────────┬──────────┘                    └───────────┬───────────┘
                │                                           │
                ▼                                           ▼
           ClickHouse                                  ClickHouse
```

**Shared infrastructure** (same containers for both stacks):
PostgreSQL · Redis primary + replica · Kafka · ClickHouse · Prometheus · Grafana

---

## 1. API Edge — the main HTTP service

Handles `POST /api/shorten`, `GET /<code>` (redirect), `GET /api/stats/<code>`, `GET /health`.

### Python — `app/`

| File | Purpose |
|---|---|
| [`app/main.py`](../app/main.py) | FastAPI app factory, lifespan (startup/shutdown), CORS, Prometheus instrumentation |
| [`app/config.py`](../app/config.py) | All env vars as a Pydantic `Settings` class, cached with `@lru_cache` |
| [`app/routes.py`](../app/routes.py) | HTTP route definitions — thin layer, delegates to `service.py` |
| [`app/service.py`](../app/service.py) | **All business logic** — short code generation, cache-first lookup, click buffering, stampede protection |
| [`app/models.py`](../app/models.py) | SQLAlchemy ORM model for the `urls` table |
| [`app/schemas.py`](../app/schemas.py) | Pydantic schemas: `URLCreate` (input), `URLResponse` (output), `ClickEvent`, `CachedURLPayload` |
| [`app/database.py`](../app/database.py) | Async SQLAlchemy engine + session factory, `init_db()` with advisory lock |
| [`app/redis.py`](../app/redis.py) | Two singleton Redis clients — write (primary) and read (replica) |
| [`app/kafka.py`](../app/kafka.py) | `AIOKafkaProducer` singleton, `publish_click_event()` with Redis stream fallback |

**Key flow — redirect hot path:**
```
routes.py: redirect_to_url()
  → service.get_url_by_code()   # Redis replica GET → cache hit → return
                                 # cache miss → acquire lock → Postgres SELECT → cache SET
  → service.increment_clicks()  # Redis INCR click_buffer → Kafka publish (or XADD fallback)
  → RedirectResponse(307)
```

**Docker image:** [`docker/api/Dockerfile`](../docker/api/Dockerfile)
**Compose service:** [`docker-compose.yml`](../docker-compose.yml) → `app-1`, `app-2`, `app-3`

---

### Rust — `services/app-rs/`

| File | Purpose |
|---|---|
| [`services/app-rs/src/main.rs`](../services/app-rs/src/main.rs) | Axum router setup, all dependency wiring (DB pool, Redis, Kafka, metrics) |
| [`services/app-rs/src/handlers.rs`](../services/app-rs/src/handlers.rs) | HTTP handlers: `health`, `shorten`, `redirect`, `stats`, `metrics` |
| [`services/app-rs/src/config.rs`](../services/app-rs/src/config.rs) | `Config::from_env()` — reads same env vars as Python `Settings` |
| [`services/app-rs/src/models.rs`](../services/app-rs/src/models.rs) | `Url` struct (SQLx `FromRow`), `UrlResponse`, `ShortenRequest`, `ClickEvent` |
| [`services/app-rs/src/cache.rs`](../services/app-rs/src/cache.rs) | Redis helpers: `get_url`, `set_url`, `incr_click_buffer`, `push_fallback_stream` |
| [`services/app-rs/src/kafka.rs`](../services/app-rs/src/kafka.rs) | rdkafka producer, `publish_click()` |
| [`services/app-rs/src/keygen.rs`](../services/app-rs/src/keygen.rs) | ID block allocator — HTTP call to keygen-rs, base62 encode |
| [`services/app-rs/src/metrics.rs`](../services/app-rs/src/metrics.rs) | Prometheus `AppMetrics` struct — same counter names as Python |
| [`services/app-rs/src/state.rs`](../services/app-rs/src/state.rs) | `AppState` — shared across all Axum handlers via `Arc<AppState>` |
| [`services/app-rs/src/db.rs`](../services/app-rs/src/db.rs) | SQLx pool creation and migration runner |

**Key flow — redirect hot path (Rust):**
```
handlers.rs: redirect()
  → cache::get_url(&redis_read)   # Redis replica GET → cache hit → spawn track_click task
                                   # cache miss → Postgres SELECT → cache::set_url
  → track_click() [tokio::spawn]  # cache::incr_click_buffer → kafka::publish_click
  → Redirect::temporary(original_url)
```

**Docker image:** [`services/app-rs/Dockerfile`](../services/app-rs/Dockerfile)
**Compose service:** [`docker-compose.rust.yml`](../docker-compose.rust.yml) → `app-rs-1`, `app-rs-2`, `app-rs-3`

---

### Python ↔ Rust — API edge comparison

| Concern | Python | Rust |
|---|---|---|
| Framework | FastAPI | Axum |
| Async runtime | asyncio (single-threaded per worker) | Tokio (work-stealing, multi-threaded) |
| DB driver | `asyncpg` via SQLAlchemy | `sqlx` |
| Redis client | `redis-py` async | `redis-rs` `ConnectionManager` |
| Kafka client | `aiokafka` | `rdkafka` |
| Config | `pydantic-settings` + `.env` | `dotenvy` + `std::env::var` |
| Metrics | `prometheus_fastapi_instrumentator` (auto) + manual `Counter` | Manual `prometheus` crate `CounterVec` |
| Click tracking | Inline in route handler | `tokio::spawn` background task (non-blocking) |

---

## 2. Key Generation — unique ID allocator

Hands out non-overlapping blocks of integer IDs so multiple app instances never generate the same short code.

### Python — `services/keygen_py/`

| File | Purpose |
|---|---|
| [`services/keygen_py/main.py`](../services/keygen_py/main.py) | FastAPI app with two endpoints: `GET /health` and `POST /allocate` |

**How it works:**
- `POST /allocate {"size": 1000}` → calls `Redis INCRBY id_allocator:url 1000`
- Returns `{"start": 1001, "end": 2000}` — the caller owns that entire range
- Has a **primary + secondary Redis** for HA — if primary fails, tries secondary
- The app edge calls this on startup and caches the block locally; only calls again when the block is exhausted

**Compose service:** [`docker-compose.yml`](../docker-compose.yml) → `keygen`

---

### Rust — `services/keygen-rs/`

| File | Purpose |
|---|---|
| [`services/keygen-rs/src/main.rs`](../services/keygen-rs/src/main.rs) | Entire service in one file — Axum router, `Config`, `AppState`, `health` + `allocate` handlers |

**How it works (same logic, different language):**
- `try_allocate()` → `conn.incr(key, size)` → returns `(end - size + 1, end)`
- Primary/secondary failover: tries primary `ConnectionManager`, falls back to secondary on error
- Uses `tokio::sync::Mutex` to share `ConnectionManager` across handlers

**Compose service:** [`docker-compose.rust.yml`](../docker-compose.rust.yml) → `keygen-rs`

---

### Python ↔ Rust — keygen comparison

| Concern | Python | Rust |
|---|---|---|
| Framework | FastAPI | Axum |
| Redis op | `client.incrby(key, size)` | `conn.incr(key, size)` |
| HA strategy | Try primary → secondary in a loop | Try primary → secondary explicitly |
| State sharing | `app.state.redis_primary` (FastAPI state) | `Arc<AppState>` with `Mutex<ConnectionManager>` |
| File count | 1 (`main.py`) | 1 (`main.rs`) |

---

## 3. Click Ingestion — async click counter persistence

Consumes click events from Kafka, aggregates them in Redis, and flushes batched `UPDATE clicks = clicks + N` to Postgres and analytics rows to ClickHouse.

### Python — `services/ingestion_py/`

| File | Purpose |
|---|---|
| [`services/ingestion_py/worker.py`](../services/ingestion_py/worker.py) | Full ingestion loop — Kafka consumer, Redis aggregation hash, Postgres flush, ClickHouse insert |

**Key functions:**

| Function | What it does |
|---|---|
| `run()` | Main loop — polls Kafka, buffers to Redis, flushes on interval |
| `_buffer_batch_to_redis()` | Groups a batch of `ClickEvent`s by `short_code`, writes to Redis hash with `HINCRBY` pipeline |
| `_flush_aggregates()` | Reads the Redis hash, calls `_process_batch()`, clears the hash |
| `_process_batch()` | Postgres `UPDATE urls SET clicks = clicks + N`, Redis cache invalidation, ClickHouse insert |
| `_process_redis_fallback_stream()` | Reads from Redis Stream (`XREADGROUP`) for events that couldn't reach Kafka |
| `_ensure_fallback_group()` | Creates the Redis consumer group on startup (`XGROUP CREATE`) |

**Compose service:** [`docker-compose.yml`](../docker-compose.yml) → `ingestion-1`, `ingestion-2`, `ingestion-3`

---

### Rust — `services/ingestion-rs/`

| File | Purpose |
|---|---|
| [`services/ingestion-rs/src/main.rs`](../services/ingestion-rs/src/main.rs) | Full ingestion loop — rdkafka `StreamConsumer`, Redis aggregation, SQLx flush, ClickHouse HTTP insert |

**Key functions:**

| Function | What it does |
|---|---|
| `main()` | Wires everything, runs the poll loop |
| `buffer_to_redis()` | Redis pipeline `HINCR` for each `short_code` in the batch |
| `flush_redis_to_db()` | `HGETALL` agg hash → SQLx `UPDATE` per code → Redis cache invalidation → ClickHouse insert → `DEL` agg hash |
| `insert_clickhouse_rows()` | Builds a raw SQL `INSERT VALUES (...)` string, POSTs to ClickHouse HTTP API |
| `ensure_clickhouse_table()` | Runs `CREATE TABLE IF NOT EXISTS` DDL via ClickHouse HTTP API |
| `ClickAggregates::add()` | In-memory accumulator before Redis flush |

**Compose service:** [`docker-compose.rust.yml`](../docker-compose.rust.yml) → `ingestion-rs-1`, `ingestion-rs-2`, `ingestion-rs-3`

---

### Python ↔ Rust — ingestion comparison

| Concern | Python | Rust |
|---|---|---|
| Kafka client | `aiokafka` `AIOKafkaConsumer` | `rdkafka` `StreamConsumer` |
| Batch poll | `consumer.getmany(timeout_ms, max_records)` | `tokio::time::timeout` + `consumer.recv()` |
| Redis aggregation | `pipeline(transaction=False)` + `HINCRBY` | `redis::pipe()` + `hincr` |
| Postgres flush | SQLAlchemy `update()` ORM | SQLx raw `sqlx::query()` |
| ClickHouse client | `clickhouse_connect` Python library | `reqwest` HTTP client with raw SQL string |
| Redis fallback stream | `XREADGROUP` + `XACK` | Not implemented (Rust stack uses Kafka reliably) |
| Metrics | `prometheus_client` `Counter` | `prometheus` crate `IntCounter` |
| In-memory buffer | `ClickAggregates` Pydantic model | `ClickAggregates` plain Rust struct with `HashMap` |

---

## 4. Cache Warmer — proactive Redis pre-warming

Periodically queries the top-N most-clicked URLs from Postgres and writes them into Redis before they expire. Prevents cold-start cache misses for popular URLs.

### Python — `services/cache_warmer_py/`

| File | Purpose |
|---|---|
| [`services/cache_warmer_py/worker.py`](../services/cache_warmer_py/worker.py) | Single `run()` loop — Postgres `SELECT ORDER BY clicks DESC LIMIT N` → Redis `SET` pipeline |

**How it works:**
1. Every `CACHE_WARMER_INTERVAL_SECONDS` (default 30s), queries `SELECT * FROM urls ORDER BY clicks DESC LIMIT 5000`
2. Serializes each row to `CachedURLPayload` JSON
3. Writes all 5000 keys in a single Redis pipeline (no `transaction=True` — speed over atomicity)
4. Sleeps and repeats

**Compose service:** [`docker-compose.yml`](../docker-compose.yml) → `cache-warmer`

> **Note:** There is no Rust equivalent of the cache warmer. The Rust stack relies on the same cache warmer Python service (or on-demand cache population in `handlers.rs: redirect()` on cache miss).

---

## 5. Shared Configuration

Both stacks read from the same environment variables. The Python side uses Pydantic `Settings`; the Rust side reads them with `std::env::var`.

| Env var | Python field | Rust field | Used by |
|---|---|---|---|
| `DATABASE_URL` | `Settings.DATABASE_URL` | `Config.database_url` | app, ingestion |
| `REDIS_URL` | `Settings.REDIS_URL` | `Config.redis_url` | all services |
| `REDIS_REPLICA_URL` | `Settings.REDIS_REPLICA_URL` | `Config.redis_replica_url` | app edge |
| `KAFKA_BOOTSTRAP_SERVERS` | `Settings.KAFKA_BOOTSTRAP_SERVERS` | `Config.kafka_bootstrap_servers` | app, ingestion |
| `KAFKA_CLICK_TOPIC` | `Settings.KAFKA_CLICK_TOPIC` | `Config.kafka_click_topic` | app, ingestion |
| `KEYGEN_SERVICE_URL` | `Settings.KEYGEN_SERVICE_URL` | `Config.keygen_service_url` | app edge |
| `KEYGEN_PRIMARY_REDIS_URL` | `Settings.KEYGEN_PRIMARY_REDIS_URL` | `Config.keygen_primary_redis_url` | keygen |
| `ID_ALLOCATOR_KEY` | `Settings.ID_ALLOCATOR_KEY` | `Config.id_allocator_key` | keygen, app |
| `ID_BLOCK_SIZE` | `Settings.ID_BLOCK_SIZE` | `Config.id_block_size` | keygen, app |
| `CLICK_BUFFER_KEY_PREFIX` | `Settings.CLICK_BUFFER_KEY_PREFIX` | `Config.click_buffer_key_prefix` | app, ingestion |
| `INGESTION_FLUSH_INTERVAL_SECONDS` | `Settings.INGESTION_FLUSH_INTERVAL_SECONDS` | `Config.ingestion_flush_interval_seconds` | ingestion |
| `CLICKHOUSE_URL` | `Settings.CLICKHOUSE_URL` | `Config.clickhouse_url` | ingestion |

**Config source files:**
- Python: [`app/config.py`](../app/config.py)
- Rust app-rs: [`services/app-rs/src/config.rs`](../services/app-rs/src/config.rs)
- Rust keygen-rs: [`services/keygen-rs/src/main.rs`](../services/keygen-rs/src/main.rs) (inline `Config` struct)
- Rust ingestion-rs: [`services/ingestion-rs/src/main.rs`](../services/ingestion-rs/src/main.rs) (inline `Config` struct)
- Env files: [`.env`](../.env) · [`.env.ci`](../.env.ci) · [`.env.test`](../.env.test)

---

## 6. Shared Data Contracts

These structures are defined in Python schemas and mirrored exactly in Rust models so both stacks can read each other's Redis cache and Kafka messages.

| Contract | Python | Rust | Used for |
|---|---|---|---|
| Redis URL cache | `CachedURLPayload` in [`app/schemas.py`](../app/schemas.py) | `Url` struct in [`services/app-rs/src/models.rs`](../services/app-rs/src/models.rs) | `url:<short_code>` Redis key |
| Kafka click event | `ClickEvent` in [`app/schemas.py`](../app/schemas.py) | `ClickEvent` in [`services/app-rs/src/models.rs`](../services/app-rs/src/models.rs) and [`services/ingestion-rs/src/main.rs`](../services/ingestion-rs/src/main.rs) | `click_events` Kafka topic |
| Redis click buffer | key `click_buffer:<code>` (plain integer string) | same key pattern in `cache.rs` and `ingestion-rs` | buffered click counter |
| Redis agg hash | `ingestion_agg:<consumer_name>` (Redis hash) | same key in `ingestion-rs` | aggregation before DB flush |
| ClickHouse table | DDL in [`services/ingestion_py/worker.py`](../services/ingestion_py/worker.py) | DDL in [`services/ingestion-rs/src/main.rs`](../services/ingestion-rs/src/main.rs) | `click_events` analytics table |

---

## 7. Infrastructure & Observability

| File | Purpose |
|---|---|
| [`docker-compose.yml`](../docker-compose.yml) | Python stack — all services + shared infra |
| [`docker-compose.rust.yml`](../docker-compose.rust.yml) | Rust stack — all services + shared infra |
| [`observability/prometheus.yml`](../observability/prometheus.yml) | Scrape configs for both stacks with `stack` labels |
| [`observability/grafana/dashboards/python/`](../observability/grafana/dashboards/python/) | Python stack Grafana dashboards |
| [`observability/grafana/dashboards/rust/`](../observability/grafana/dashboards/rust/) | Rust stack Grafana dashboards |
| [`observability/grafana/dashboards/comparison/`](../observability/grafana/dashboards/comparison/) | Python vs Rust side-by-side dashboards |
| [`observability/grafana/provisioning/`](../observability/grafana/provisioning/) | Grafana auto-provisioning config |
| [`docker/nginx/nginx.conf`](../docker/nginx/nginx.conf) | nginx config for Python stack load balancer |
| [`docker/nginx/nginx-rust.conf`](../docker/nginx/nginx-rust.conf) | nginx config for Rust stack load balancer |

---

## 8. Tests & Scripts

| File | Purpose |
|---|---|
| [`tests/`](../tests/) | Python pytest suite — unit + integration tests for the Python stack |
| [`scripts/bench_http.py`](../scripts/bench_http.py) | Mixed-workload benchmark (writer + reader + celebrity traffic patterns) |
| [`scripts/flood_rust.py`](../scripts/flood_rust.py) | High-concurrency sustained flood for the Rust stack |
| [`scripts/bench_compare.py`](../scripts/bench_compare.py) | Parses bench output and compares Python vs Rust results |
| [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) | Python CI — black, isort, pyright, pytest, docker build |
| [`.github/workflows/ci-rust.yml`](../.github/workflows/ci-rust.yml) | Rust CI — rustfmt, clippy, cargo build, docker build |

---

## Quick Navigation by Task

| I want to… | Go to |
|---|---|
| Change how short codes are generated | [`app/service.py`](../app/service.py) `_base62_encode`, `_generate_short_code_from_allocator` · [`services/app-rs/src/keygen.rs`](../services/app-rs/src/keygen.rs) |
| Change the redirect / cache lookup logic | [`app/service.py`](../app/service.py) `get_url_by_code` · [`services/app-rs/src/handlers.rs`](../services/app-rs/src/handlers.rs) `redirect` |
| Change click tracking / buffering | [`app/service.py`](../app/service.py) `increment_clicks` · [`services/app-rs/src/handlers.rs`](../services/app-rs/src/handlers.rs) `track_click` |
| Change how clicks are flushed to Postgres | [`services/ingestion_py/worker.py`](../services/ingestion_py/worker.py) `_process_batch` · [`services/ingestion-rs/src/main.rs`](../services/ingestion-rs/src/main.rs) `flush_redis_to_db` |
| Add a new API endpoint | [`app/routes.py`](../app/routes.py) + [`app/service.py`](../app/service.py) · [`services/app-rs/src/handlers.rs`](../services/app-rs/src/handlers.rs) + [`services/app-rs/src/main.rs`](../services/app-rs/src/main.rs) |
| Add a new config variable | [`app/config.py`](../app/config.py) · relevant `Config::from_env()` in the Rust service |
| Add a new Prometheus metric | [`app/service.py`](../app/service.py) top-level `Counter(...)` · [`services/app-rs/src/metrics.rs`](../services/app-rs/src/metrics.rs) |
| Change the database schema | [`app/models.py`](../app/models.py) · [`services/app-rs/src/models.rs`](../services/app-rs/src/models.rs) |
| Change Redis cache format | [`app/schemas.py`](../app/schemas.py) `CachedURLPayload` · [`services/app-rs/src/cache.rs`](../services/app-rs/src/cache.rs) |
| Change Kafka message format | [`app/schemas.py`](../app/schemas.py) `ClickEvent` · [`services/app-rs/src/models.rs`](../services/app-rs/src/models.rs) `ClickEvent` |
