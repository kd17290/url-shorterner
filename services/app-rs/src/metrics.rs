use prometheus::{IntCounter, IntCounterVec, Opts, Registry};
use std::sync::OnceLock;

#[allow(dead_code)]
pub struct AppMetrics {
    pub redis_ops_total: IntCounter,
    pub db_reads_total: IntCounter,
    pub db_writes_total: IntCounter,
    pub kafka_publish_total: IntCounter,
    pub stream_fallback_total: IntCounter,
    pub cache_hits_total: IntCounter,
    pub cache_misses_total: IntCounter,
    pub http_requests_total: IntCounterVec,
}

static METRICS: OnceLock<AppMetrics> = OnceLock::new();

pub fn init(registry: &Registry) -> &'static AppMetrics {
    METRICS.get_or_init(|| {
        let redis_ops = IntCounter::with_opts(Opts::new(
            "app_edge_redis_ops_total",
            "Redis ops from app-rs",
        ))
        .unwrap();
        let db_reads =
            IntCounter::with_opts(Opts::new("app_edge_db_reads_total", "DB reads from app-rs"))
                .unwrap();
        let db_writes = IntCounter::with_opts(Opts::new(
            "app_edge_db_writes_total",
            "DB writes from app-rs",
        ))
        .unwrap();
        let kafka_pub = IntCounter::with_opts(Opts::new(
            "app_edge_kafka_publish_total",
            "Kafka publishes from app-rs",
        ))
        .unwrap();
        let stream_fb = IntCounter::with_opts(Opts::new(
            "app_edge_stream_fallback_total",
            "Redis stream fallbacks",
        ))
        .unwrap();
        let cache_hits =
            IntCounter::with_opts(Opts::new("app_edge_cache_hits_total", "Redis cache hits"))
                .unwrap();
        let cache_misses = IntCounter::with_opts(Opts::new(
            "app_edge_cache_misses_total",
            "Redis cache misses",
        ))
        .unwrap();
        let http_reqs = IntCounterVec::new(
            Opts::new("http_requests_total", "HTTP requests by handler and status"),
            &["handler", "method", "status_code"],
        )
        .unwrap();

        registry.register(Box::new(redis_ops.clone())).ok();
        registry.register(Box::new(db_reads.clone())).ok();
        registry.register(Box::new(db_writes.clone())).ok();
        registry.register(Box::new(kafka_pub.clone())).ok();
        registry.register(Box::new(stream_fb.clone())).ok();
        registry.register(Box::new(cache_hits.clone())).ok();
        registry.register(Box::new(cache_misses.clone())).ok();
        registry.register(Box::new(http_reqs.clone())).ok();

        AppMetrics {
            redis_ops_total: redis_ops,
            db_reads_total: db_reads,
            db_writes_total: db_writes,
            kafka_publish_total: kafka_pub,
            stream_fallback_total: stream_fb,
            cache_hits_total: cache_hits,
            cache_misses_total: cache_misses,
            http_requests_total: http_reqs,
        }
    })
}

pub fn gather(registry: &Registry) -> String {
    use prometheus::Encoder;
    let encoder = prometheus::TextEncoder::new();
    let mut buf = Vec::new();
    encoder.encode(&registry.gather(), &mut buf).unwrap();
    String::from_utf8(buf).unwrap()
}
