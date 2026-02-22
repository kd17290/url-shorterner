/// Ingestion worker — Rust port of services/ingestion/worker.py
///
/// Consumes click events from Kafka, aggregates them in Redis,
/// flushes to PostgreSQL (OLTP) and ClickHouse (analytics) on interval.
use std::{collections::HashMap, sync::Arc, time::Duration};

use axum::{routing::get, Router};
use prometheus::{IntCounter, Registry};
use rdkafka::{
    consumer::{CommitMode, Consumer, StreamConsumer},
    ClientConfig, Message,
};
use redis::{aio::ConnectionManager, AsyncCommands};
use serde::{Deserialize, Serialize};
use sqlx::PgPool;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter};

// ── Config ────────────────────────────────────────────────────────────────────

#[derive(Debug, Clone)]
struct Config {
    database_url: String,
    redis_url: String,
    kafka_bootstrap_servers: String,
    kafka_click_topic: String,
    ingestion_consumer_group: String,
    ingestion_consumer_name: String,
    ingestion_batch_size: usize,
    ingestion_block_ms: u64,
    ingestion_flush_interval_seconds: u64,
    ingestion_agg_key_prefix: String,
    click_buffer_key_prefix: String,
    clickhouse_url: String,
    clickhouse_username: String,
    clickhouse_password: String,
    clickhouse_database: String,
    ingestion_metrics_port: Option<u16>,
}

fn evar(key: &str) -> anyhow::Result<String> {
    std::env::var(key).map_err(|_| anyhow::anyhow!("Missing env var: {key}"))
}

fn evar_or(key: &str, default: &str) -> String {
    std::env::var(key).unwrap_or_else(|_| default.to_string())
}

fn evar_parse<T: std::str::FromStr>(key: &str, default: T) -> T {
    std::env::var(key)
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}

impl Config {
    fn from_env() -> anyhow::Result<Self> {
        dotenvy::dotenv().ok();
        let mut database_url = evar("DATABASE_URL")?;
        database_url = database_url.replace("postgresql+asyncpg://", "postgresql://");
        Ok(Self {
            database_url,
            redis_url: evar("REDIS_URL")?,
            kafka_bootstrap_servers: evar_or("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
            kafka_click_topic: evar_or("KAFKA_CLICK_TOPIC", "click_events"),
            ingestion_consumer_group: evar_or("INGESTION_CONSUMER_GROUP", "click_ingestion_group"),
            ingestion_consumer_name: evar_or("INGESTION_CONSUMER_NAME", "ingestion-consumer-1"),
            ingestion_batch_size: evar_parse("INGESTION_BATCH_SIZE", 500),
            ingestion_block_ms: evar_parse("INGESTION_BLOCK_MS", 1000),
            ingestion_flush_interval_seconds: evar_parse("INGESTION_FLUSH_INTERVAL_SECONDS", 5),
            ingestion_agg_key_prefix: evar_or("INGESTION_AGG_KEY_PREFIX", "ingestion_agg"),
            click_buffer_key_prefix: evar_or("CLICK_BUFFER_KEY_PREFIX", "click_buffer"),
            clickhouse_url: evar_or("CLICKHOUSE_URL", "http://clickhouse:8123"),
            clickhouse_username: evar_or("CLICKHOUSE_USERNAME", "default"),
            clickhouse_password: evar_or("CLICKHOUSE_PASSWORD", "clickhouse"),
            clickhouse_database: evar_or("CLICKHOUSE_DATABASE", "default"),
            ingestion_metrics_port: std::env::var("INGESTION_METRICS_PORT")
                .ok()
                .and_then(|v| v.parse().ok()),
        })
    }
}

// ── Models ────────────────────────────────────────────────────────────────────

/// Kafka message payload — matches Python ClickEvent schema.
#[derive(Debug, Deserialize, Serialize)]
struct ClickEvent {
    short_code: String,
    delta: i64,
}

/// Aggregated click deltas ready to flush — mirrors Python ClickAggregates.
#[derive(Debug, Default)]
struct ClickAggregates {
    by_short_code: HashMap<String, i64>,
}

impl ClickAggregates {
    fn add(&mut self, short_code: &str, delta: i64) {
        *self
            .by_short_code
            .entry(short_code.to_string())
            .or_insert(0) += delta;
    }

    fn total(&self) -> i64 {
        self.by_short_code.values().sum()
    }

    fn is_empty(&self) -> bool {
        self.by_short_code.is_empty()
    }
}

// ── Metrics ───────────────────────────────────────────────────────────────────

struct WorkerMetrics {
    kafka_events_total: IntCounter,
    redis_buffer_total: IntCounter,
    db_updates_total: IntCounter,
    clickhouse_rows_total: IntCounter,
}

fn init_metrics(registry: &Registry) -> WorkerMetrics {
    let kafka = IntCounter::new("ingestion_kafka_events_total", "Kafka events consumed").unwrap();
    let redis_buf = IntCounter::new("ingestion_redis_buffer_total", "Redis buffer ops").unwrap();
    let db_upd = IntCounter::new("ingestion_db_updates_total", "DB updates applied").unwrap();
    let ch_rows = IntCounter::new(
        "ingestion_clickhouse_rows_total",
        "ClickHouse rows inserted",
    )
    .unwrap();
    registry.register(Box::new(kafka.clone())).ok();
    registry.register(Box::new(redis_buf.clone())).ok();
    registry.register(Box::new(db_upd.clone())).ok();
    registry.register(Box::new(ch_rows.clone())).ok();
    WorkerMetrics {
        kafka_events_total: kafka,
        redis_buffer_total: redis_buf,
        db_updates_total: db_upd,
        clickhouse_rows_total: ch_rows,
    }
}

// ── ClickHouse ────────────────────────────────────────────────────────────────

async fn ensure_clickhouse_table(
    http: &reqwest::Client,
    ch_url: &str,
    username: &str,
    password: &str,
    database: &str,
) -> anyhow::Result<()> {
    let ddl = format!(
        "CREATE TABLE IF NOT EXISTS {database}.click_events \
         (short_code String, delta UInt32, event_time DateTime) \
         ENGINE = MergeTree ORDER BY (short_code, event_time)"
    );
    let url = format!("{ch_url}/?user={username}&password={password}");
    http.post(&url).body(ddl).send().await?.error_for_status()?;
    Ok(())
}

async fn insert_clickhouse_rows(
    http: &reqwest::Client,
    ch_url: &str,
    username: &str,
    password: &str,
    database: &str,
    aggregates: &ClickAggregates,
) -> anyhow::Result<usize> {
    if aggregates.is_empty() {
        return Ok(0);
    }
    let now = chrono::Utc::now().format("%Y-%m-%d %H:%M:%S").to_string();
    let rows: String = aggregates
        .by_short_code
        .iter()
        .map(|(code, delta)| format!("('{}',{},'{}')", code.replace('\'', "\\'"), delta, now))
        .collect::<Vec<_>>()
        .join(",");

    let query = format!(
        "INSERT INTO {database}.click_events (short_code, delta, event_time) VALUES {rows}"
    );
    let url = format!("{ch_url}/?user={username}&password={password}");
    http.post(&url)
        .body(query)
        .send()
        .await?
        .error_for_status()?;
    Ok(aggregates.by_short_code.len())
}

// ── Redis helpers ─────────────────────────────────────────────────────────────

fn agg_hash_key(prefix: &str, consumer_name: &str) -> String {
    format!("{prefix}:{consumer_name}")
}

async fn buffer_to_redis(
    conn: &mut ConnectionManager,
    agg_key: &str,
    aggregates: &ClickAggregates,
) -> anyhow::Result<()> {
    if aggregates.is_empty() {
        return Ok(());
    }
    let mut pipe = redis::pipe();
    for (code, delta) in &aggregates.by_short_code {
        pipe.hincr(agg_key, code, *delta);
    }
    pipe.query_async::<_, ()>(conn).await?;
    Ok(())
}

async fn flush_redis_to_db(
    conn: &mut ConnectionManager,
    pool: &PgPool,
    http: &reqwest::Client,
    config: &Config,
    metrics: &WorkerMetrics,
) -> anyhow::Result<()> {
    let agg_key = agg_hash_key(
        &config.ingestion_agg_key_prefix,
        &config.ingestion_consumer_name,
    );
    let raw: HashMap<String, String> = conn.hgetall(&agg_key).await?;
    if raw.is_empty() {
        return Ok(());
    }

    let mut aggregates = ClickAggregates::default();
    for (code, delta_str) in &raw {
        if let Ok(delta) = delta_str.parse::<i64>() {
            if delta > 0 {
                aggregates.add(code, delta);
            }
        }
    }
    if aggregates.is_empty() {
        let _: () = conn.del(&agg_key).await?;
        return Ok(());
    }

    // Flush to PostgreSQL.
    let mut tx = pool.begin().await?;
    for (code, delta) in &aggregates.by_short_code {
        sqlx::query(
            "UPDATE urls SET clicks = clicks + $1, updated_at = now() WHERE short_code = $2",
        )
        .bind(delta)
        .bind(code)
        .execute(&mut *tx)
        .await?;
        metrics.db_updates_total.inc();
    }
    tx.commit().await?;

    // Decrement Redis click buffer + invalidate URL cache.
    let mut pipe = redis::pipe();
    pipe.atomic();
    for (code, delta) in &aggregates.by_short_code {
        let buf_key = format!("{}:{}", config.click_buffer_key_prefix, code);
        let cache_key = format!("url:{code}");
        pipe.decr(&buf_key, *delta);
        pipe.del(&cache_key);
    }
    pipe.query_async::<_, ()>(conn).await?;

    // Insert into ClickHouse.
    let rows = insert_clickhouse_rows(
        http,
        &config.clickhouse_url,
        &config.clickhouse_username,
        &config.clickhouse_password,
        &config.clickhouse_database,
        &aggregates,
    )
    .await
    .unwrap_or_else(|e| {
        tracing::warn!("clickhouse insert failed: {e}");
        0
    });
    metrics.clickhouse_rows_total.inc_by(rows as u64);

    // Clear the aggregation hash.
    let _: () = conn.del(&agg_key).await?;
    Ok(())
}

// ── Main loop ─────────────────────────────────────────────────────────────────

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::registry()
        .with(EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()))
        .with(tracing_subscriber::fmt::layer().json())
        .init();

    let config = Config::from_env()?;
    tracing::info!(consumer = %config.ingestion_consumer_name, "starting ingestion-rs");

    // Prometheus metrics server.
    let registry = Arc::new(Registry::new());
    let metrics = Arc::new(init_metrics(&registry));
    let metrics_port = config.ingestion_metrics_port.unwrap_or(9200);
    {
        let registry = Arc::clone(&registry);
        tokio::spawn(async move {
            let app = Router::new().route(
                "/metrics",
                get(move || {
                    let r = Arc::clone(&registry);
                    async move {
                        use prometheus::Encoder;
                        let enc = prometheus::TextEncoder::new();
                        let mut buf = Vec::new();
                        enc.encode(&r.gather(), &mut buf).unwrap();
                        String::from_utf8(buf).unwrap()
                    }
                }),
            );
            let addr = format!("0.0.0.0:{metrics_port}");
            let listener = tokio::net::TcpListener::bind(&addr).await.unwrap();
            tracing::info!("metrics server on {addr}");
            axum::serve(listener, app).await.unwrap();
        });
    }

    // Database pool.
    let pool = sqlx::postgres::PgPoolOptions::new()
        .max_connections(5)
        .connect(&config.database_url)
        .await?;
    tracing::info!("database ready");

    // Redis.
    let redis_client = redis::Client::open(config.redis_url.as_str())?;
    let mut redis_conn = ConnectionManager::new(redis_client).await?;
    tracing::info!("redis ready");

    // HTTP client for ClickHouse.
    let http = reqwest::Client::new();
    ensure_clickhouse_table(
        &http,
        &config.clickhouse_url,
        &config.clickhouse_username,
        &config.clickhouse_password,
        &config.clickhouse_database,
    )
    .await
    .unwrap_or_else(|e| tracing::warn!("clickhouse DDL failed (will retry): {e}"));

    // Kafka consumer.
    let consumer: StreamConsumer = ClientConfig::new()
        .set("bootstrap.servers", &config.kafka_bootstrap_servers)
        .set("group.id", &config.ingestion_consumer_group)
        .set("client.id", &config.ingestion_consumer_name)
        .set("enable.auto.commit", "true")
        .set("auto.offset.reset", "earliest")
        .set("session.timeout.ms", "30000")
        .create()?;
    consumer.subscribe(&[&config.kafka_click_topic])?;
    tracing::info!("kafka consumer subscribed to {}", config.kafka_click_topic);

    let flush_interval = Duration::from_secs(config.ingestion_flush_interval_seconds);
    let mut last_flush = std::time::Instant::now();
    let mut pending = ClickAggregates::default();
    let agg_key = agg_hash_key(
        &config.ingestion_agg_key_prefix,
        &config.ingestion_consumer_name,
    );

    loop {
        // Poll Kafka with a short timeout so we can flush on interval.
        match tokio::time::timeout(
            Duration::from_millis(config.ingestion_block_ms),
            consumer.recv(),
        )
        .await
        {
            Ok(Ok(msg)) => {
                if let Some(payload) = msg.payload() {
                    match serde_json::from_slice::<ClickEvent>(payload) {
                        Ok(event) => {
                            pending.add(&event.short_code, event.delta);
                            metrics.kafka_events_total.inc();
                        }
                        Err(e) => tracing::warn!("invalid kafka payload: {e}"),
                    }
                }
                consumer.commit_message(&msg, CommitMode::Async).ok();

                // Buffer to Redis when batch is large enough.
                if pending.by_short_code.len() >= config.ingestion_batch_size {
                    let total = pending.total();
                    if let Err(e) = buffer_to_redis(&mut redis_conn, &agg_key, &pending).await {
                        tracing::warn!("redis buffer failed: {e}");
                    } else {
                        metrics.redis_buffer_total.inc_by(total as u64);
                    }
                    pending = ClickAggregates::default();
                }
            }
            Ok(Err(e)) => tracing::warn!("kafka recv error: {e}"),
            Err(_) => {} // timeout — normal, proceed to flush check
        }

        // Flush remaining pending to Redis.
        if !pending.is_empty() {
            let total = pending.total();
            if let Err(e) = buffer_to_redis(&mut redis_conn, &agg_key, &pending).await {
                tracing::warn!("redis buffer failed: {e}");
            } else {
                metrics.redis_buffer_total.inc_by(total as u64);
            }
            pending = ClickAggregates::default();
        }

        // Flush Redis aggregates to DB + ClickHouse on interval.
        if last_flush.elapsed() >= flush_interval {
            if let Err(e) =
                flush_redis_to_db(&mut redis_conn, &pool, &http, &config, &metrics).await
            {
                tracing::warn!("flush failed: {e}");
            }
            last_flush = std::time::Instant::now();
        }
    }
}
