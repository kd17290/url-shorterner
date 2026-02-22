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

### Python — `apps/`

| File | Purpose |
|---|---|
| [`apps/url_shortener/main.py`](../apps/url_shortener/main.py) | FastAPI app factory, lifespan (startup/shutdown), CORS, Prometheus instrumentation |
| [`apps/url_shortener/config.py`](../apps/url_shortener/config.py) | All env vars as a Pydantic `Settings` class, cached with `@lru_cache` |
| [`apps/url_shortener/routes.py`](../apps/url_shortener/routes.py) | HTTP route definitions — thin layer, delegates to service layer |
| [`services/url_shortening/url_shortening_service.py`](../services/url_shortening/url_shortening_service.py) | **All business logic** — short code generation, cache-first lookup, click buffering, stampede protection |
| [`common/models.py`](../common/models.py) | SQLAlchemy ORM model for the `urls` table |
| [`common/schemas.py`](../common/schemas.py) | Pydantic schemas: `URLCreate` (input), `URLResponse` (output), `ClickEvent`, `CachedURLPayload` |
| [`apps/url_shortener/database.py`](../apps/url_shortener/database.py) | Async SQLAlchemy engine + session factory, `init_db()` with advisory lock |
| [`apps/url_shortener/dependencies.py`](../apps/url_shortener/dependencies.py) | Dependency injection with singleton service manager and request context |

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
- Python: [`services/config/config_service.py`](../services/config/config_service.py)
- Python app settings: [`apps/url_shortener/config.py`](../apps/url_shortener/config.py)
- Rust app-rs: [`services/app-rs/src/config.rs`](../services/app-rs/src/config.rs)
- Rust keygen-rs: [`services/keygen-rs/src/main.rs`](../services/keygen-rs/src/main.rs) (inline `Config` struct)
- Rust ingestion-rs: [`services/ingestion-rs/src/main.rs`](../services/ingestion-rs/src/main.rs) (inline `Config` struct)
- Env files: [`.env`](../.env) · [`.env.ci`](../.env.ci) · [`.env.test`](../.env.test)

---

## 6. Shared Data Contracts

These structures are defined in Python schemas and mirrored exactly in Rust models so both stacks can read each other's Redis cache and Kafka messages.

| Contract | Python | Rust | Used for |
|---|---|---|---|
| Redis URL cache | `CachedURLPayload` in [`common/schemas.py`](../common/schemas.py) | `Url` struct in [`services/app-rs/src/models.rs`](../services/app-rs/src/models.rs) | `url:<short_code>` Redis key |
| Kafka click event | `ClickEvent` in [`common/schemas.py`](../common/schemas.py) | `ClickEvent` in [`services/app-rs/src/models.rs`](../services/app-rs/src/models.rs) and [`services/ingestion-rs/src/main.rs`](../services/ingestion-rs/src/main.rs) | `click_events` Kafka topic |
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

## 9. Architectural Patterns & Gotchas

This section captures the key learnings, tradeoffs, and common pitfalls discovered while building and maintaining this dual-stack (Python + Rust) URL shortener.

### 🏗️ Service Layer Architecture Patterns

#### ✅ **Recommended Pattern: Module Import + Infrastructure DI**

```python
# ✅ Current approach - keep this
from app import service

@router.post("/api/shorten")
async def shorten_url(
    payload: URLCreate,
    db: AsyncSession = Depends(get_db),      # Infrastructure via FastAPI DI
    cache: redis.Redis = Depends(get_redis), # Infrastructure via FastAPI DI
) -> URLResponse:
    url = await service.create_short_url(payload, db, cache)  # Direct service call
    return URLResponse.model_validate(url)
```

**Why this works:**
- **Performance**: Direct function calls, no per-request object allocation
- **Simplicity**: Clear separation between HTTP handling and business logic
- **Testability**: Easy to mock service functions with `unittest.mock`
- **FastAPI idiomatic**: DI for infrastructure, direct calls for logic

#### ❌ **Anti-Pattern: Service Class Injection**

```python
# ❌ Don't do this - unnecessary complexity
class URLService:
    def __init__(self, db: AsyncSession, cache: redis.Redis):
        self.db = db
        self.cache = cache
    
    async def create_short_url(self, payload: URLCreate) -> URL:
        # Implementation...

def get_url_service(...) -> URLService:
    return URLService(db, cache)

@router.post("/api/shorten")
async def shorten_url(
    payload: URLCreate,
    url_service: URLService = Depends(get_url_service),  # Unnecessary overhead
) -> URLResponse:
    url = await url_service.create_short_url(payload)
    return URLResponse.model_validate(url)
```

**Problems:**
- **Overhead**: Object creation per request in hot path
- **Complexity**: More boilerplate, factories, and wiring
- **No Benefits**: Service functions are already pure and testable

#### 🎯 **When to Use Service Classes**

Only consider service injection when you have:
1. **Multiple implementations** (different payment providers, storage backends)
2. **Runtime switching** (feature flags, A/B testing)
3. **Complex state** (service needs own configuration and lifecycle)
4. **Interface segregation** (want to hide implementation details)

---

### 🌍 Global State vs Dependency Injection

#### ⚠️ **Global State Gotchas (Current Issues)**

```python
# service.py - PROBLEMATIC global state
settings = get_settings()  # ← Fixed at import time
APP_EDGE_DB_READS_TOTAL = Counter(...)  # ← Global metrics persist between tests
_id_block_next: int = 0  # ← Thread safety concerns
_id_block_end: int = -1  # ← Memory never cleaned up
```

**Problems with global state:**
- **Testing**: Global metrics persist between tests, causing flaky tests
- **Configuration**: Settings fixed at import time, can't change per-request
- **Thread safety**: Global variables need locks in concurrent environments
- **Memory leaks**: Global state never gets cleaned up

#### ✅ **Better Pattern: Service Dependencies Parameter**

```python
# Phase 1: Backward compatible
async def create_short_url(payload, db, cache, deps: ServiceDeps | None = None):
    if deps:
        deps.metrics.inc_db_reads()
    else:
        # Fallback to global for backward compatibility
        APP_EDGE_DB_READS_TOTAL.inc()

# Phase 2: Full migration
@dataclass
class ServiceDeps:
    db: AsyncSession
    cache: redis.Redis
    config: ConfigProtocol
    metrics: MetricsProtocol

async def create_short_url(payload, deps: ServiceDeps) -> URL:
    settings = deps.config.get_settings()
    deps.metrics.inc_db_reads()
    # Clean implementation with no global state
```

---

### 🏛️ Dependency Injection Best Practices

#### ✅ **What to Inject via FastAPI DI**

```python
# ✅ Infrastructure dependencies
db: AsyncSession = Depends(get_db)
cache: redis.Redis = Depends(get_redis)
cache_read: redis.Redis = Depends(get_redis_read)
```

**Why these work:**
- **External resources**: Database connections, Redis clients
- **Lifecycle management**: FastAPI handles setup/teardown
- **Per-request state**: Each request gets its own connection
- **Testability**: Easy to inject test doubles

#### ❌ **What NOT to Inject via FastAPI DI**

```python
# ❌ Don't inject these
service: URLService = Depends(get_url_service)  # Business logic
config: Settings = Depends(get_settings)        # Configuration
metrics: Metrics = Depends(get_metrics)        # Utilities
```

**Why these don't work:**
- **Business logic**: Should be called directly, not instantiated per request
- **Configuration**: Usually static per deployment
- **Utilities**: Better as global singletons or module-level functions

---

### 🔄 Async/Await Patterns & Gotchas

#### ✅ **Correct Async Patterns**

```python
# ✅ Non-blocking I/O throughout
async def redirect_to_url(short_code: str, db: AsyncSession, cache: redis.Redis):
    # All I/O operations are awaited
    cached = await cache.get(cache_key)  # Redis GET
    if not cached:
        result = await db.execute(select(URL).where(URL.short_code == short_code))  # DB query
    await cache.set(cache_key, data)  # Redis SET
    await increment_clicks(url, db, cache)  # Business logic
```

#### ❌ **Common Async Gotchas**

```python
# ❌ Blocking operations in async code
async def bad_example():
    time.sleep(1)  # ❌ Blocks event loop
    sync_requests.get("https://example.com")  # ❌ Blocking HTTP
    
# ✅ Correct alternatives
async def good_example():
    await asyncio.sleep(1)  # ✅ Non-blocking
    async with httpx.AsyncClient() as client:  # ✅ Async HTTP
        await client.get("https://example.com")
```

#### 🎯 **Background Tasks Patterns**

```python
# Python: Fire-and-forget (careful with errors)
async def track_click_background(url: URL):
    try:
        await increment_clicks(url, db, cache)
    except Exception:
        # Log but don't fail the main request
        logger.error(f"Failed to track click: {e}")

# Rust: Proper background task with error handling
tokio::spawn(async move {
    if let Err(e) = track_click(url).await {
        tracing::error!("Failed to track click: {}", e);
    }
});
```

---

### 📊 Enum Patterns vs String Literals

#### ❌ **String Literal Problems**

```python
# ❌ Error-prone string literals
if status == "healthy":  # What if typo "healty"?
    return {"status": "healthy", "database": "healthy"}
```

**Problems:**
- **Typos**: `"healty"` vs `"healthy"` - runtime errors
- **No autocomplete**: IDE can't suggest valid values
- **No type safety**: Any string is accepted
- **Hard to refactor**: Need to find all occurrences manually

#### ✅ **Enum Pattern Benefits**

```python
# ✅ Type-safe enums
from enum import StrEnum

class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"

def health_check() -> HealthResponse:
    status = HealthStatus.HEALTHY  # ✅ Type-safe, autocomplete
    return HealthResponse(status=status)  # ✅ Serialized to "healthy"
```

**Benefits:**
- **Type safety**: Compile/type-time error checking
- **IDE support**: Full autocomplete and refactoring
- **Documentation**: Enum definition shows all valid values
- **Refactoring safe**: IDE can find all usages
- **JSON compatible**: `StrEnum` serializes to strings automatically

---

### 🧪 Testing Patterns & Gotchas

#### ✅ **Good Testing Patterns**

```python
# ✅ Test service functions directly
async def test_get_url_by_code_cache_hit():
    # Arrange
    mock_cache = AsyncMock()
    mock_cache.get.return_value = json.dumps({"short_code": "abc123", ...})
    
    # Act
    result = await service.get_url_by_code("abc123", mock_db, mock_cache)
    
    # Assert
    assert result.short_code == "abc123"
    mock_cache.get.assert_called_once_with("url:abc123")

# ✅ Test routes with dependency overrides
async def test_redirect_endpoint():
    app.dependency_overrides[get_redis] = lambda: mock_cache
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/abc123")
        assert response.status_code == 307
```

#### ❌ **Testing Gotchas**

```python
# ❌ Testing with global state
def test_with_global_metrics():
    APP_EDGE_DB_READS_TOTAL.inc()  # ❌ Persists to other tests
    
# ❌ Not cleaning up test data
async def test_create_url():
    url = await service.create_short_url(...)  # ❌ Leaves data in DB
    # No cleanup = test pollution

# ✅ Proper test cleanup
async def test_create_url_with_cleanup():
    url = await service.create_short_url(...)
    try:
        assert url.short_code is not None
    finally:
        await db.delete(url)  # ✅ Clean up
```

---

### 🚀 Performance Optimization Patterns

#### ✅ **Cache-First Pattern**

```python
# ✅ Always check cache first
async def get_url_by_code(short_code: str, db, cache_read, cache_write=None):
    # 1. Try cache (fast)
    cached = await cache_read.get(f"url:{short_code}")
    if cached:
        return URL(**json.loads(cached))
    
    # 2. Cache miss - go to database (slow)
    result = await db.execute(select(URL).where(URL.short_code == short_code))
    url = result.scalar_one_or_none()
    
    # 3. Populate cache for next time
    if url and cache_write:
        await cache_write.set(f"url:{short_code}", json.dumps(url.model_dump()), ex=3600)
    
    return url
```

#### ✅ **Write-Back Pattern for Clicks**

```python
# ✇ Buffer clicks in Redis, batch flush to DB
async def increment_clicks(url: URL, db, cache):
    # Fast Redis increment
    buffer_key = f"click_buffer:{url.short_code}"
    count = await cache.incr(buffer_key)
    
    # Set expiry on first increment
    if count == 1:
        await cache.expire(buffer_key, 300)  # 5 minutes
    
    # Async Kafka publish (non-blocking)
    await publish_click_event(url.short_code, 1)
```

#### ❌ **Performance Anti-Patterns**

```python
# ❌ N+1 query problem
async def get_multiple_urls(codes: list[str], db):
    urls = []
    for code in codes:  # ❌ N database queries
        url = await get_url_by_code(code, db, cache)
        urls.append(url)
    return urls

# ✅ Batch query instead
async def get_multiple_urls(codes: list[str], db):
    result = await db.execute(select(URL).where(URL.short_code.in_(codes)))  # ✅ 1 query
    return result.scalars().all()
```

---

### 🔧 Configuration Management Patterns

#### ✅ **Good Configuration Pattern**

```python
# ✅ Centralized settings with validation
class Settings(BaseSettings):
    DATABASE_URL: str
    REDIS_URL: str
    CLICK_BUFFER_TTL_SECONDS: int = 300
    
    class Config:
        env_file = ".env"
        case_sensitive = True

# ✅ Cached settings (expensive parsing)
@lru_cache
def get_settings() -> Settings:
    return Settings()  # Parse once, cache forever
```

#### ❌ **Configuration Gotchas**

```python
# ❌ Environment variables scattered throughout code
redis_url = os.getenv("REDIS_URL")  # ❌ No validation, no defaults
db_url = os.getenv("DATABASE_URL")   # ❌ No type checking

# ❌ Configuration at import time
settings = Settings()  # ❌ Can't change for testing
```

---

### 📝 Error Handling Patterns

#### ✅ **Consistent Error Handling**

```python
# ✅ Domain exceptions for business logic
class URLNotFound(Exception):
    pass

class CustomCodeTaken(Exception):
    pass

# ✅ Convert domain exceptions to HTTP responses
@router.post("/api/shorten")
async def shorten_url(payload: URLCreate):
    try:
        url = await service.create_short_url(payload, db, cache)
        return URLResponse.model_validate(url)
    except CustomCodeTaken as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
```

#### ❌ **Error Handling Gotchas**

```python
# ❌ Swallowing errors
async def bad_increment_clicks(url: URL, db, cache):
    try:
        await cache.incr(f"click_buffer:{url.short_code}")
    except Exception:
        pass  # ❌ Silent failure, lost data

# ❌ Inconsistent error responses
if not url:
    return {"error": "not found"}  # ❌ No status code
    # vs
    raise HTTPException(status_code=404)  # ✅ Proper HTTP error
```

---

### 🔄 Database Transaction Patterns

#### ✅ **Transaction Management**

```python
# ✅ Explicit transaction boundaries
async def create_short_url(payload: URLCreate, db, cache):
    async with db.begin():  # ✅ Automatic rollback on exception
        # Check uniqueness
        existing = await db.execute(select(URL).where(URL.short_code == short_code))
        if existing.scalar_one_or_none():
            raise ValueError(f"Custom code '{short_code}' is already taken")
        
        # Create URL
        url = URL(short_code=short_code, original_url=str(payload.url))
        db.add(url)
        await db.flush()  # Get ID without committing
        
        # Cache population (can fail without affecting DB)
        await cache.set(f"url:{short_code}", json.dumps(url.model_dump()), ex=3600)
    
    return url  # Transaction committed here
```

#### ❌ **Transaction Gotchas**

```python
# ❌ No transaction control
async def bad_create_url(payload: URLCreate, db, cache):
    # Check uniqueness
    existing = await db.execute(select(URL).where(URL.short_code == short_code))
    if existing.scalar_one_or_none():
        raise ValueError("Code taken")  # ❌ Race condition possible
    
    # Create URL
    url = URL(short_code=short_code, original_url=str(payload.url))
    db.add(url)
    await db.commit()  # ❌ Could fail halfway through

# ❌ Long-running transactions
async def bad_long_transaction(db):
    async with db.begin():
        await db.execute(update(URL).values(clicks=URL.clicks + 1))  # Fast
        await some_slow_external_api_call()  # ❌ Blocks transaction, holds locks
        await cache.invalidate_all()  # ❌ Slow operation in transaction
```

---

### 🐛 Common Debugging Gotchas

#### 🔍 **Async Debugging**

```python
# ❌ Blocking debug prints
async def bad_debug():
    print(f"Before: {await some_async_operation()}")  # ❌ Hard to correlate logs
    result = await another_operation()
    print(f"After: {result}")

# ✅ Structured logging
async def good_debug():
    logger.info("Starting operation", operation="get_url", code=short_code)
    result = await some_async_operation()
    logger.info("Completed operation", operation="get_url", result_count=len(result))
    return result
```

#### 🔍 **Race Condition Debugging**

```python
# ❌ Hard-to-reproduce race conditions
async def concurrent_url_creation():
    # Two requests might generate same custom code simultaneously
    if not await db.execute(select(URL).where(URL.short_code == custom_code)):
        # Race condition: another request might insert here
        url = URL(short_code=custom_code, original_url=url)
        db.add(url)
        await db.commit()  # ❌ Unique constraint violation

# ✅ Database constraints + proper error handling
async def safe_url_creation():
    try:
        url = URL(short_code=custom_code, original_url=url)
        db.add(url)
        await db.commit()  # ✅ Let database handle race condition
    except IntegrityError:
        await db.rollback()
        raise ValueError(f"Custom code '{custom_code}' is already taken")
```

---

### 📚 Additional Learning Resources

#### 🏛️ **Architecture Patterns to Study**
- **Repository Pattern**: Abstract data access behind interfaces
- **Unit of Work Pattern**: Manage transactions and consistency
- **CQRS Pattern**: Separate read and write models
- **Event Sourcing**: Store events instead of current state
- **Circuit Breaker Pattern**: Handle external service failures

#### 🧪 **Testing Patterns to Master**
- **Test Doubles**: Mocks, stubs, fakes, and spies
- **Property-Based Testing**: Generate test cases automatically
- **Contract Testing**: Verify service integrations
- **Load Testing**: Verify performance under stress
- **Chaos Engineering**: Test system resilience

#### 🚀 **Performance Patterns to Explore**
- **Connection Pooling**: Reuse database/Redis connections
- **Batch Processing**: Group operations for efficiency
- **Caching Strategies**: Multi-level caching hierarchies
- **Async Task Queues**: Background job processing
- **Sharding**: Distribute data across multiple instances

---

## Quick Navigation by Task

| I want to… | Go to |
|---|---|
| Change how short codes are generated | [`services/url_shortening/url_shortening_service.py`](../services/url_shortening/url_shortening_service.py) `_base62_encode`, `_generate_short_code_from_allocator` · [`services/app-rs/src/keygen.rs`](../services/app-rs/src/keygen.rs) |
| Change the redirect / cache lookup logic | [`services/url_shortening/url_shortening_service.py`](../services/url_shortening/url_shortening_service.py) `get_url_by_code` · [`services/app-rs/src/handlers.rs`](../services/app-rs/src/handlers.rs) `redirect` |
| Change click tracking / buffering | [`services/url_shortening/url_shortening_service.py`](../services/url_shortening/url_shortening_service.py) `increment_clicks` · [`services/app-rs/src/handlers.rs`](../services/app-rs/src/handlers.rs) `track_click` |
| Change how clicks are flushed to Postgres | [`services/ingestion/worker.py`](../services/ingestion/worker.py) `_process_batch` · [`services/ingestion-rs/src/main.rs`](../services/ingestion-rs/src/main.rs) `flush_redis_to_db` |
| Add a new API endpoint | [`apps/url_shortener/routes.py`](../apps/url_shortener/routes.py) + [`services/url_shortening/url_shortening_service.py`](../services/url_shortening/url_shortening_service.py) · [`services/app-rs/src/handlers.rs`](../services/app-rs/src/handlers.rs) + [`services/app-rs/src/main.rs`](../services/app-rs/src/main.rs) |
| Add a new config variable | [`services/config/config_service.py`](../services/config/config_service.py) · relevant `Config::from_env()` in the Rust service |
| Add a new Prometheus metric | [`services/url_shortening/url_shortening_service.py`](../services/url_shortening/url_shortening_service.py) top-level `Counter(...)` · [`services/app-rs/src/metrics.rs`](../services/app-rs/src/metrics.rs) |
| Change the database schema | [`common/models.py`](../common/models.py) · [`services/app-rs/src/models.rs`](../services/app-rs/src/models.rs) |
| Change Redis cache format | [`common/schemas.py`](../common/schemas.py) `CachedURLPayload` · [`services/app-rs/src/cache.rs`](../services/app-rs/src/cache.rs) |
| Change Kafka message format | [`common/schemas.py`](../common/schemas.py) `ClickEvent` · [`services/app-rs/src/models.rs`](../services/app-rs/src/models.rs) `ClickEvent` |
