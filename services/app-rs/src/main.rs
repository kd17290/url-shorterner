mod cache;
mod config;
mod db;
mod enums;
mod handlers;
mod kafka;
mod keygen;
mod metrics;
mod models;
mod state;

use axum::{
    routing::{get, post},
    Router,
};
use prometheus::Registry;
use std::sync::Arc;
use tower_http::cors::CorsLayer;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter};

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Tracing
    tracing_subscriber::registry()
        .with(EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()))
        .with(tracing_subscriber::fmt::layer().json())
        .init();

    let config = config::Config::from_env()?;
    tracing::info!(app = %config.app_name, env = %config.app_env, "starting app-rs");

    // Database
    let pool = db::create_pool(&config.database_url).await?;
    db::migrate(&pool).await?;
    tracing::info!("database ready");

    // Redis write (primary)
    let redis_write = cache::create_client(&config.redis_url).await?;

    // Redis read (replica — falls back to primary if not configured)
    let read_url = config
        .redis_replica_url
        .clone()
        .unwrap_or_else(|| config.redis_url.clone());
    let redis_read = cache::create_client(&read_url).await?;
    tracing::info!("redis ready");

    // Kafka producer
    let kafka_producer = kafka::create_producer(&config.kafka_bootstrap_servers)?;
    tracing::info!("kafka producer ready");

    // Prometheus
    let registry = Registry::new();
    let app_metrics = metrics::init(&registry);

    // Shared state
    let state = state::AppState::new(
        config,
        pool,
        redis_write,
        redis_read,
        kafka_producer,
        app_metrics,
        registry,
    );

    // Router
    let app = Router::new()
        .route("/health", get(handlers::health))
        .route("/metrics", get(handlers::metrics))
        .route("/api/shorten", post(handlers::shorten))
        .route("/api/stats/:short_code", get(handlers::stats))
        .route("/:short_code", get(handlers::redirect))
        .layer(CorsLayer::permissive())
        .with_state(Arc::clone(&state));

    let addr = "0.0.0.0:8000";
    tracing::info!("listening on {addr}");
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;

    Ok(())
}
