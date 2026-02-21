/// All configuration loaded from environment variables.
/// Mirrors the Python Settings Pydantic model exactly.
#[derive(Debug, Clone)]
pub struct Config {
    pub app_name: String,
    pub app_env: String,
    pub base_url: String,

    pub database_url: String,

    pub redis_url: String,
    pub redis_replica_url: Option<String>,

    pub short_code_length: usize,
    pub id_allocator_key: String,
    pub id_block_size: i64,
    pub keygen_service_url: String,

    pub click_buffer_key_prefix: String,
    pub click_buffer_ttl_seconds: u64,
    pub click_flush_threshold: i64,
    pub click_stream_key: String,

    pub kafka_bootstrap_servers: String,
    pub kafka_click_topic: String,
}

fn env(key: &str) -> anyhow::Result<String> {
    std::env::var(key).map_err(|_| anyhow::anyhow!("Missing env var: {key}"))
}

fn env_or(key: &str, default: &str) -> String {
    std::env::var(key).unwrap_or_else(|_| default.to_string())
}

fn env_parse<T: std::str::FromStr>(key: &str, default: T) -> T
where
    T::Err: std::fmt::Debug,
{
    std::env::var(key)
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}

impl Config {
    pub fn from_env() -> anyhow::Result<Self> {
        dotenvy::dotenv().ok();
        let mut database_url = env("DATABASE_URL")?;
        // sqlx requires postgresql:// not postgresql+asyncpg:// (Python asyncpg driver prefix)
        database_url = database_url.replace("postgresql+asyncpg://", "postgresql://");
        Ok(Self {
            app_name: env_or("APP_NAME", "url-shortener-rs"),
            app_env: env_or("APP_ENV", "development"),
            base_url: env_or("BASE_URL", "http://localhost:8080"),
            database_url,
            redis_url: env("REDIS_URL")?,
            redis_replica_url: std::env::var("REDIS_REPLICA_URL").ok(),
            short_code_length: env_parse("SHORT_CODE_LENGTH", 7),
            id_allocator_key: env_or("ID_ALLOCATOR_KEY", "id_allocator:url"),
            id_block_size: env_parse("ID_BLOCK_SIZE", 1000),
            keygen_service_url: env_or("KEYGEN_SERVICE_URL", "http://keygen:8010"),
            click_buffer_key_prefix: env_or("CLICK_BUFFER_KEY_PREFIX", "click_buffer"),
            click_buffer_ttl_seconds: env_parse("CLICK_BUFFER_TTL_SECONDS", 300),
            click_flush_threshold: env_parse("CLICK_FLUSH_THRESHOLD", 100),
            click_stream_key: env_or("CLICK_STREAM_KEY", "click_events"),
            kafka_bootstrap_servers: env_or("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
            kafka_click_topic: env_or("KAFKA_CLICK_TOPIC", "click_events"),
        })
    }
}
