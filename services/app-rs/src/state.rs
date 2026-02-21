use prometheus::Registry;
use rdkafka::producer::FutureProducer;
use redis::aio::ConnectionManager;
use sqlx::PgPool;
use std::sync::Arc;
use tokio::sync::Mutex;

use crate::{config::Config, keygen::KeygenClient, metrics::AppMetrics};

/// Shared application state injected into every handler via axum State extractor.
pub struct AppState {
    pub config: Config,
    pub db: PgPool,
    /// Primary Redis — writes (INCR, SET, XADD, advisory locks).
    pub redis_write: Arc<Mutex<ConnectionManager>>,
    /// Replica Redis — reads (GET cache lookups in redirect hot path).
    pub redis_read: Arc<Mutex<ConnectionManager>>,
    pub kafka_producer: FutureProducer,
    pub keygen: KeygenClient,
    pub metrics: &'static AppMetrics,
    pub registry: Registry,
}

impl AppState {
    pub fn new(
        config: Config,
        db: PgPool,
        redis_write: ConnectionManager,
        redis_read: ConnectionManager,
        kafka_producer: FutureProducer,
        metrics: &'static AppMetrics,
        registry: Registry,
    ) -> Arc<Self> {
        let keygen = KeygenClient::new(config.keygen_service_url.clone(), config.id_block_size);
        Arc::new(Self {
            config,
            db,
            redis_write: Arc::new(Mutex::new(redis_write)),
            redis_read: Arc::new(Mutex::new(redis_read)),
            kafka_producer,
            keygen,
            metrics,
            registry,
        })
    }
}
