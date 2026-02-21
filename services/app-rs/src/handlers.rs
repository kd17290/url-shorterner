//! HTTP handlers for the Rust URL shortener service.
//!
//! This module provides all HTTP endpoints with proper error handling,
//! response serialization, and performance optimizations.
//!
//! # Architecture Overview
//!
//! ```text
//! Request → Handler → Service Layer → Data Layer → Response
//!    ↓         ↓           ↓            ↓         ↓
//! HTTP    Axum     Business    Database/   JSON/HTTP
//! Layer   Router    Logic       Redis      Response
//! ```
//!
//! # Flow Diagrams
//!
//! ## URL Creation (Scalable)
//! ```text
//! ┌─────────────┐
//! │ POST /api/ │
//! │ shorten     │
//! └──────┬──────┘
//!        ▼
//! ┌─────────────┐
//! │ Validate URL│
//! │ (Serde)     │
//! └──────┬──────┘
//!        ▼
//! ┌─────────────┐
//! │ Generate or │
//! │ use custom   │
//! │ short code   │
//! └──────┬──────┘
//!        ▼
//! ┌─────────────┐
//! │ Custom code │
//! │ DB check?   │
//! │ (PostgreSQL)│
//! └──────┬──────┘
//! NO?    │ YES
//! ▼      ▼
//! ┌─────────┐ ┌─────────┐
//! │Generated│ │ Custom  │
//! │code     │ │code DB  │
//! │(no DB)  │ │check    │
//! └────┬───┘ └────┬───┘
//!      ▼           ▼
//! ┌─────────────┐
//! │ Create URL  │
//! │ record      │
//! │ (optimistic)│
//! └──────┬──────┘
//!        ▼
//! ┌─────────────┐
//! │ Cache in    │
//! │ Redis (TTL) │
//! └──────┬──────┘
//!        ▼
//! ┌─────────────┐
//! │ Return URL  │
//! │ response    │
//! └─────────────┘
//! ```
//!
//! ## URL Lookup & Redirect
//! ```text
//! ┌─────────────┐
//! │  GET /:code  │
//! └──────┬──────┘
//!        ▼
//! ┌─────────────┐
//! │ Check Redis │
//! │ cache       │
//! └──────┬──────┘
//! HIT?  │
//! ┌─────┴─────┐
//! │ NO         │ YES
//! ▼            ▼
//! ┌─────────┐ ┌─────────┐
//! │Database │ │ Redirect│
//! │lookup   │ │307      │
//! └────┬───┘ └────┬───┘
//!      ▼           ▼
//! ┌─────────┐ ┌─────────────┐
//! │ Cache   │ │ Return      │
//! │populate │ │ redirect    │
//! └────┬───┘ └─────────────┘
//!      ▼
//! ┌─────────────┐
//! │ Background  │
//! │ click track │
//! │ task spawn  │
//! └─────────────┘
//! ```
//!
//! ## Health Check
//! ```text
//! ┌─────────────┐
//! │ GET /health │
//! └──────┬──────┘
//!        ▼
//! ┌─────────────┐
//! │ Check DB    │
//! │ (SELECT 1)  │
//! └──────┬──────┘
//!        ▼
//! ┌─────────────┐
//! │ Check Redis │
//! │ (PING)     │
//! └──────┬──────┘
//!        ▼
//! ┌─────────────┐
//! │ Return     │
//! │ HealthStatus│
//! │ (enum)     │
//! └─────────────┘
//! ```

use axum::{
    extract::{Path, State},
    http::StatusCode,
    response::{IntoResponse, Redirect, Response},
    Json,
};
use std::sync::Arc;

use crate::cache;
use crate::enums::HealthStatus;
use crate::kafka;
use crate::models::{ClickEvent, HealthResponse, ShortenRequest, Url, UrlResponse};
use crate::state::AppState;

// ── Health ────────────────────────────────────────────────────────────────────

pub async fn health(State(state): State<Arc<AppState>>) -> Json<HealthResponse> {
    let db_status = match sqlx::query("SELECT 1").execute(&state.db).await {
        Ok(_) => HealthStatus::Healthy,
        Err(_) => HealthStatus::Unhealthy,
    };

    let cache_status = {
        let mut conn = state.redis_write.lock().await;
        match cache::ping(&mut conn).await {
            Ok(_) => HealthStatus::Healthy,
            Err(_) => HealthStatus::Unhealthy,
        }
    };

    let overall_status = if db_status == HealthStatus::Healthy && cache_status == HealthStatus::Healthy {
        HealthStatus::Healthy
    } else {
        HealthStatus::Unhealthy
    };

    Json(HealthResponse {
        status: overall_status,
        database: db_status,
        cache: cache_status,
    })
}

// ── Metrics ───────────────────────────────────────────────────────────────────

pub async fn metrics(State(state): State<Arc<AppState>>) -> String {
    crate::metrics::gather(&state.registry)
}

// ── POST /api/shorten ─────────────────────────────────────────────────────────

pub async fn shorten(
    State(state): State<Arc<AppState>>,
    Json(payload): Json<ShortenRequest>,
) -> Response {
    let short_code = if let Some(ref custom) = payload.custom_code {
        // Check uniqueness of custom code.
        let existing: Option<Url> = sqlx::query_as(
            "SELECT id, short_code, original_url, clicks, created_at, updated_at FROM urls WHERE short_code = $1",
        )
        .bind(custom)
        .fetch_optional(&state.db)
        .await
        .unwrap_or(None);

        if existing.is_some() {
            return (
                StatusCode::CONFLICT,
                Json(serde_json::json!({ "detail": format!("Custom code '{}' is already taken", custom) })),
            )
                .into_response();
        }
        custom.clone()
    } else {
        // Allocate from keygen block.
        let id = match state.keygen.next_id().await {
            Ok(id) => id,
            Err(e) => {
                tracing::error!("keygen error: {e}");
                return StatusCode::SERVICE_UNAVAILABLE.into_response();
            }
        };
        match crate::keygen::encode_id(id, state.config.short_code_length) {
            Ok(code) => code,
            Err(e) => {
                tracing::error!("encode_id error: {e}");
                return StatusCode::INTERNAL_SERVER_ERROR.into_response();
            }
        }
    };

    // Optimistic insertion with collision handling (extremely rare case)
    let url: Url = match sqlx::query_as(
        r#"
        INSERT INTO urls (short_code, original_url, clicks)
        VALUES ($1, $2, 0)
        RETURNING id, short_code, original_url, clicks, created_at, updated_at
        "#,
    )
    .bind(&short_code)
    .bind(&payload.url)
    .fetch_one(&state.db)
    .await
    {
        Ok(u) => u,
        Err(e) => {
            // Check if it's a uniqueness constraint violation
            if e.to_string().contains("unique constraint") || e.to_string().contains("duplicate key") {
                tracing::warn!("Collision detected for short_code: {}, retrying...", short_code);
                
                if payload.custom_code.is_some() {
                    // Custom code collision - real error
                    return (
                        StatusCode::CONFLICT,
                        Json(serde_json::json!({ "detail": format!("Custom code '{}' is already taken", short_code) })),
                    )
                        .into_response();
                } else {
                    // Generated code collision - retry once (should never happen with proper allocator)
                    let retry_id = match state.keygen.next_id().await {
                        Ok(id) => id,
                        Err(e) => {
                            tracing::error!("keygen retry error: {e}");
                            return StatusCode::SERVICE_UNAVAILABLE.into_response();
                        }
                    };
                    let retry_code = match crate::keygen::encode_id(retry_id, state.config.short_code_length) {
                        Ok(code) => code,
                        Err(e) => {
                            tracing::error!("encode_id retry error: {e}");
                            return StatusCode::INTERNAL_SERVER_ERROR.into_response();
                        }
                    };
                    
                    // Retry insertion
                    match sqlx::query_as(
                        r#"
                        INSERT INTO urls (short_code, original_url, clicks)
                        VALUES ($1, $2, 0)
                        RETURNING id, short_code, original_url, clicks, created_at, updated_at
                        "#,
                    )
                    .bind(&retry_code)
                    .bind(&payload.url)
                    .fetch_one(&state.db)
                    .await
                    {
                        Ok(u) => u,
                        Err(e2) => {
                            tracing::error!("db retry insert error: {e2}");
                            return StatusCode::INTERNAL_SERVER_ERROR.into_response();
                        }
                    }
                }
            } else {
                tracing::error!("db insert error: {e}");
                return StatusCode::INTERNAL_SERVER_ERROR.into_response();
            }
        }
    };

    state.metrics.db_writes_total.inc();
    state
        .metrics
        .http_requests_total
        .with_label_values(&["shorten", "POST", "201"])
        .inc();

    // Cache the new URL.
    {
        let mut write_conn = state.redis_write.lock().await;
        if let Err(e) = cache::set_url(&mut write_conn, &url).await {
            tracing::warn!("cache set failed: {e}");
        }
    }
    state.metrics.redis_ops_total.inc();

    let resp = UrlResponse::from_url(&url, &state.config.base_url);
    (StatusCode::CREATED, Json(resp)).into_response()
}

// ── GET /:short_code (redirect) ───────────────────────────────────────────────

pub async fn redirect(
    State(state): State<Arc<AppState>>,
    Path(short_code): Path<String>,
) -> Response {
    // 1. Try read replica cache first.
    let cached = {
        let mut read_conn = state.redis_read.lock().await;
        cache::get_url(&mut read_conn, &short_code).await
    };

    if let Some(url) = cached {
        state.metrics.cache_hits_total.inc();
        state.metrics.redis_ops_total.inc();
        state
            .metrics
            .http_requests_total
            .with_label_values(&["redirect", "GET", "302"])
            .inc();
        let original = url.original_url.clone();
        let state2 = state.clone();
        let code = short_code.clone();
        tokio::spawn(async move {
            track_click(&state2, &code).await;
        });
        return Redirect::temporary(&original).into_response();
    }

    state.metrics.cache_misses_total.inc();
    state.metrics.redis_ops_total.inc();

    // 2. Cache miss — fall back to DB.
    let url: Option<Url> = sqlx::query_as(
        "SELECT id, short_code, original_url, clicks, created_at, updated_at FROM urls WHERE short_code = $1",
    )
    .bind(&short_code)
    .fetch_optional(&state.db)
    .await
    .unwrap_or(None);

    state.metrics.db_reads_total.inc();

    match url {
        None => (
            StatusCode::NOT_FOUND,
            Json(serde_json::json!({ "detail": "Short URL not found" })),
        )
            .into_response(),
        Some(url) => {
            // Populate cache for next request.
            {
                let mut write_conn = state.redis_write.lock().await;
                if let Err(e) = cache::set_url(&mut write_conn, &url).await {
                    tracing::warn!("cache set failed: {e}");
                }
            }
            state
                .metrics
                .http_requests_total
                .with_label_values(&["redirect", "GET", "302"])
                .inc();
            let original = url.original_url.clone();
            let state2 = state.clone();
            let code = short_code.clone();
            tokio::spawn(async move {
                track_click(&state2, &code).await;
            });
            Redirect::temporary(&original).into_response()
        }
    }
}

// ── GET /api/stats/:short_code ────────────────────────────────────────────────

pub async fn stats(State(state): State<Arc<AppState>>, Path(short_code): Path<String>) -> Response {
    let url: Option<Url> = sqlx::query_as(
        "SELECT id, short_code, original_url, clicks, created_at, updated_at FROM urls WHERE short_code = $1",
    )
    .bind(&short_code)
    .fetch_optional(&state.db)
    .await
    .unwrap_or(None);

    state.metrics.db_reads_total.inc();

    match url {
        None => (
            StatusCode::NOT_FOUND,
            Json(serde_json::json!({ "detail": "Short URL not found" })),
        )
            .into_response(),
        Some(url) => {
            state
                .metrics
                .http_requests_total
                .with_label_values(&["stats", "GET", "200"])
                .inc();
            Json(UrlResponse::from_url(&url, &state.config.base_url)).into_response()
        }
    }
}

// ── Internal: click tracking ──────────────────────────────────────────────────

async fn track_click(state: &AppState, short_code: &str) {
    // Increment Redis click buffer (primary — write op).
    {
        let mut write_conn = state.redis_write.lock().await;
        if let Err(e) = cache::incr_click_buffer(
            &mut write_conn,
            &state.config.click_buffer_key_prefix,
            short_code,
            state.config.click_buffer_ttl_seconds,
        )
        .await
        {
            tracing::warn!("click buffer incr failed: {e}");
        }
    }
    state.metrics.redis_ops_total.inc();

    // Publish to Kafka; fall back to Redis stream on failure.
    let event = ClickEvent {
        short_code: short_code.to_string(),
        delta: 1,
    };
    let published = kafka::publish_click(
        &state.kafka_producer,
        &state.config.kafka_click_topic,
        &event,
    )
    .await;

    if published {
        state.metrics.kafka_publish_total.inc();
    } else {
        state.metrics.stream_fallback_total.inc();
        let mut write_conn = state.redis_write.lock().await;
        if let Err(e) = cache::push_fallback_stream(
            &mut write_conn,
            &state.config.click_stream_key,
            short_code,
            1,
        )
        .await
        {
            tracing::warn!("fallback stream push failed: {e}");
        }
    }
}
