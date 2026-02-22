use axum::{
    extract::State,
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::{get, post},
    Json, Router,
};
use redis::{aio::ConnectionManager, AsyncCommands};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tokio::sync::Mutex;
use tower_http::cors::CorsLayer;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter};

// ── Enums ─────────────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum HealthStatus {
    Healthy,
    Unhealthy,
}

impl HealthStatus {
    pub fn from_str(s: &str) -> Self {
        match s {
            "healthy" => Self::Healthy,
            _ => Self::Unhealthy,
        }
    }
}

// ── Config ────────────────────────────────────────────────────────────────────

#[derive(Debug, Clone)]
struct Config {
    keygen_primary_redis_url: String,
    keygen_secondary_redis_url: String,
    id_allocator_key: String,
    id_block_size: i64,
}

impl Config {
    fn from_env() -> anyhow::Result<Self> {
        dotenvy::dotenv().ok();
        Ok(Self {
            keygen_primary_redis_url: std::env::var("KEYGEN_PRIMARY_REDIS_URL")
                .unwrap_or_else(|_| "redis://keygen-redis-primary:6379/0".to_string()),
            keygen_secondary_redis_url: std::env::var("KEYGEN_SECONDARY_REDIS_URL")
                .unwrap_or_else(|_| "redis://keygen-redis-secondary:6379/0".to_string()),
            id_allocator_key: std::env::var("ID_ALLOCATOR_KEY")
                .unwrap_or_else(|_| "id_allocator:url".to_string()),
            id_block_size: std::env::var("ID_BLOCK_SIZE")
                .ok()
                .and_then(|v| v.parse().ok())
                .unwrap_or(1000),
        })
    }
}

// ── Models ────────────────────────────────────────────────────────────────────

#[derive(Debug, Deserialize)]
struct AllocateRequest {
    size: Option<i64>,
    stack: Option<String>, // "python" or "rust"
}

#[derive(Debug, Serialize)]
struct AllocateResponse {
    start: i64,
    end: i64,
    stack: String,
}

#[derive(Debug, Serialize)]
struct HealthResponse {
    status: HealthStatus,
    primary: HealthStatus,
    secondary: HealthStatus,
}

// ── State ─────────────────────────────────────────────────────────────────────

// ConnectionManager is not Clone in redis 0.25 in a way that shares the same
// underlying connection pool, so we wrap each in a Mutex for interior mutability.
struct AppState {
    config: Config,
    primary: Mutex<ConnectionManager>,
    secondary: Mutex<ConnectionManager>,
}

// ── Handlers ──────────────────────────────────────────────────────────────────

async fn health(State(state): State<Arc<AppState>>) -> Json<HealthResponse> {
    let primary_status = {
        let mut c = state.primary.lock().await;
        match c.get::<&str, Option<String>>("__ping__").await {
            Ok(_) => HealthStatus::Healthy,
            Err(_) => HealthStatus::Unhealthy,
        }
    };
    let secondary_status = {
        let mut c = state.secondary.lock().await;
        match c.get::<&str, Option<String>>("__ping__").await {
            Ok(_) => HealthStatus::Healthy,
            Err(_) => HealthStatus::Unhealthy,
        }
    };
    let overall_status =
        if primary_status == HealthStatus::Healthy || secondary_status == HealthStatus::Healthy {
            HealthStatus::Healthy
        } else {
            HealthStatus::Unhealthy
        };
    Json(HealthResponse {
        status: overall_status,
        primary: primary_status,
        secondary: secondary_status,
    })
}

async fn allocate(
    State(state): State<Arc<AppState>>,
    Json(req): Json<AllocateRequest>,
) -> Response {
    let size = req.size.unwrap_or(state.config.id_block_size);
    let stack = req.stack.unwrap_or_else(|| "rust".to_string());

    if size <= 0 {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({ "detail": "size must be > 0" })),
        )
            .into_response();
    }

    if !["python", "rust"].contains(&stack.as_str()) {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({ "detail": "stack must be 'python' or 'rust'" })),
        )
            .into_response();
    }

    // Use stack-specific allocator key
    let allocator_key = format!("{}:{}", state.config.id_allocator_key, stack);

    // Try primary first, then secondary.
    let result = {
        let mut c = state.primary.lock().await;
        try_allocate(&mut c, &allocator_key, size).await
    };
    let (start, end) = match result {
        Ok(r) => r,
        Err(_) => {
            let mut c = state.secondary.lock().await;
            match try_allocate(&mut c, &allocator_key, size).await {
                Ok(r) => r,
                Err(e) => {
                    tracing::error!("both keygen backends failed for stack {}: {}", stack, e);
                    return (
                        StatusCode::SERVICE_UNAVAILABLE,
                        Json(
                            serde_json::json!({ "detail": format!("key allocation backends unavailable for stack: {}", stack) }),
                        ),
                    )
                        .into_response();
                }
            }
        }
    };

    Json(AllocateResponse { start, end, stack }).into_response()
}

async fn try_allocate(
    conn: &mut ConnectionManager,
    key: &str,
    size: i64,
) -> anyhow::Result<(i64, i64)> {
    let end_value: i64 = conn.incr(key, size).await?;
    let start_value = end_value - size + 1;
    Ok((start_value, end_value))
}

// ── Main ──────────────────────────────────────────────────────────────────────

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::registry()
        .with(EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()))
        .with(tracing_subscriber::fmt::layer().json())
        .init();

    let config = Config::from_env()?;
    tracing::info!("starting keygen-rs");

    let primary = {
        let client = redis::Client::open(config.keygen_primary_redis_url.as_str())?;
        ConnectionManager::new(client).await?
    };
    let secondary = {
        let client = redis::Client::open(config.keygen_secondary_redis_url.as_str())?;
        ConnectionManager::new(client).await?
    };
    tracing::info!("redis backends ready");

    let state = Arc::new(AppState {
        config,
        primary: Mutex::new(primary),
        secondary: Mutex::new(secondary),
    });

    let app = Router::new()
        .route("/health", get(health))
        .route("/allocate", post(allocate))
        .layer(CorsLayer::permissive())
        .with_state(state);

    let addr = "0.0.0.0:8010";
    tracing::info!("listening on {addr}");
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;

    Ok(())
}
