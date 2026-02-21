# Rust Coding Standards

Applies to all code under `services/app-rs`, `services/keygen-rs`, and `services/ingestion-rs`.

---

## 1. Toolchain & Edition

- Rust **1.93** (pinned in all Dockerfiles via `rust:1.93-slim-bookworm`).
- Edition **2021** in all `Cargo.toml` files.
- `cargo fmt` and `cargo clippy -- -D warnings` must pass before merge.

---

## 2. Project Layout

Each service follows this structure:

```
services/<name>-rs/
├── Cargo.toml          # service-level deps (workspace = true for shared ones)
└── src/
    ├── main.rs         # startup: config, state init, router, bind
    ├── config.rs       # Config struct + from_env() (app-rs only; inline for small services)
    ├── state.rs        # AppState struct (app-rs only)
    ├── handlers.rs     # Axum route handlers
    ├── models.rs       # DB row types (FromRow), request/response types
    ├── db.rs           # PgPool creation, migrations
    ├── cache.rs        # Redis helpers
    ├── kafka.rs        # Kafka producer helpers
    ├── keygen.rs       # Keygen client + base62 encoder
    └── metrics.rs      # Prometheus counters/gauges
```

---

## 3. Configuration

**Never use `envy` for uppercase env vars** — `envy 0.4` does not uppercase field names; it reads env vars as-is and matches lowercase field names. Use `std::env::var` directly:

```rust
fn env(key: &str) -> anyhow::Result<String> {
    std::env::var(key).map_err(|_| anyhow::anyhow!("Missing env var: {key}"))
}

fn env_or(key: &str, default: &str) -> String {
    std::env::var(key).unwrap_or_else(|_| default.to_string())
}

fn env_parse<T: std::str::FromStr>(key: &str, default: T) -> T {
    std::env::var(key).ok().and_then(|v| v.parse().ok()).unwrap_or(default)
}
```

Always strip the Python asyncpg driver prefix from `DATABASE_URL`:

```rust
database_url = database_url.replace("postgresql+asyncpg://", "postgresql://");
```

---

## 4. Shared State (`AppState`)

- Wrap in `Arc<AppState>` and register with `.with_state(Arc::new(state))`.
- `redis::aio::ConnectionManager` is **not Clone** in redis 0.25 in a way that shares the underlying connection. Wrap each instance in `Arc<tokio::sync::Mutex<ConnectionManager>>`:

```rust
pub struct AppState {
    pub db: PgPool,
    pub redis_write: Arc<Mutex<ConnectionManager>>,
    pub redis_read:  Arc<Mutex<ConnectionManager>>,
    // ...
}
```

- Acquire the lock in a scoped block to release it before any `.await` that doesn't need it:

```rust
{
    let mut conn = state.redis_write.lock().await;
    cache::set_url(&mut conn, &url).await?;
}
```

---

## 5. Database

- Use `sqlx::PgPool` with `connect_lazy_with` or `PgPoolOptions::new()`.
- All DB row types must derive `sqlx::FromRow`.
- **Match PostgreSQL column types exactly**:
  - `INTEGER` (INT4) → `i32`
  - `BIGINT` (INT8) → `i64`
  - `TEXT` / `VARCHAR` → `String`
  - `TIMESTAMPTZ` → `chrono::DateTime<Utc>`
- Always include all NOT NULL columns without defaults in INSERT statements:

```sql
INSERT INTO urls (short_code, original_url, clicks)
VALUES ($1, $2, 0)
RETURNING id, short_code, original_url, clicks, created_at, updated_at
```

- Use a PostgreSQL advisory lock for DDL migrations to prevent races on multi-instance startup:

```rust
conn.execute("SELECT pg_advisory_lock(12345678)").await?;
// run migrations
conn.execute("SELECT pg_advisory_unlock(12345678)").await?;
```

---

## 6. Error Handling

- Use `anyhow::Result` for application-level errors.
- Use `thiserror` for library-level error types if needed.
- Never use `.unwrap()` in production paths — use `?` or explicit error handling.
- Log errors with `tracing::error!` before returning `StatusCode::INTERNAL_SERVER_ERROR`.

---

## 7. HTTP Handlers (Axum)

- Return `impl IntoResponse` from handlers.
- Use `Json(serde_json::json!({ "detail": "..." }))` for error bodies.
- Prefer `(StatusCode, Json<T>).into_response()` over manual response construction.
- Extract state with `State(state): State<Arc<AppState>>`.

---

## 8. Kafka (`rdkafka`)

- Always use the `cmake-build` feature — Debian Bookworm's `librdkafka` (2.0.2) is too old for `rdkafka 0.36`'s `dynamic-linking` feature (requires ≥ 2.3.0).
- Dockerfiles must include `build-essential cmake libssl-dev pkg-config libsasl2-dev libcurl4-openssl-dev` in the builder stage.
- Use `FutureProducer` for async fire-and-forget publish; log errors but do not fail the request.

---

## 9. Tracing & Logging

- Use `tracing_subscriber` with `EnvFilter` driven by `RUST_LOG`.
- Default log level: `info`.
- Use structured fields: `tracing::info!(short_code = %code, "redirect")`.
- Use JSON format in production (`tracing_subscriber::fmt().json()`).

---

## 10. Metrics (Prometheus)

- Use `prometheus` crate with a global `Registry`.
- Expose metrics on `GET /metrics` via `prometheus::TextEncoder`.
- Counter naming: `<service>_<subsystem>_<operation>_total` (e.g. `app_rs_db_writes_total`).

---

## 11. Docker

- Multi-stage builds: `rust:1.93-slim-bookworm` builder → `debian:bookworm-slim` runtime.
- Runtime stage: install only `ca-certificates libssl3 libsasl2-2`.
- Create a non-root `appuser` in the runtime stage.
- Copy only the compiled binary from the builder stage.
- Set `WORKDIR /app` and `USER appuser` before `CMD`.

---

## 12. Dependency Management

- All shared dependencies go in the workspace `Cargo.toml` under `[workspace.dependencies]`.
- Service `Cargo.toml` files reference them with `{ workspace = true }`.
- Pin major versions; do not use `*` or overly broad ranges.

---

## 13. Banned Patterns

| Pattern | Reason | Alternative |
|---|---|---|
| `envy::from_env::<Config>()` with uppercase env vars | envy 0.4 doesn't uppercase | `std::env::var` directly |
| `.unwrap()` in handlers | panics in production | `?` or explicit match |
| `ConnectionManager::clone()` | doesn't share connection | `Arc<Mutex<ConnectionManager>>` |
| `rdkafka` with `dynamic-linking` on Debian Bookworm | librdkafka 2.0.2 too old | `cmake-build` feature |
| `i64` for Postgres `INTEGER` columns | type mismatch at runtime | `i32` |
