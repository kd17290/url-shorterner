use chrono::{DateTime, Utc};
use crate::enums::HealthStatus;
use serde::{Deserialize, Serialize};
use sqlx::FromRow;

/// Database row — mirrors the Python URL SQLAlchemy model.
#[derive(Debug, Clone, FromRow, Serialize, Deserialize)]
pub struct Url {
    pub id: i32,
    pub short_code: String,
    pub original_url: String,
    pub clicks: i32,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

/// Request body for POST /api/shorten.
#[derive(Debug, Deserialize)]
pub struct ShortenRequest {
    pub url: String,
    pub custom_code: Option<String>,
}

/// Response for POST /api/shorten and GET /api/stats/:code.
#[derive(Debug, Serialize)]
pub struct UrlResponse {
    pub id: i32,
    pub short_code: String,
    pub original_url: String,
    pub short_url: String,
    pub clicks: i32,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

impl UrlResponse {
    pub fn from_url(url: &Url, base_url: &str) -> Self {
        Self {
            id: url.id,
            short_code: url.short_code.clone(),
            original_url: url.original_url.clone(),
            short_url: format!("{}/{}", base_url, url.short_code),
            clicks: url.clicks,
            created_at: url.created_at,
            updated_at: url.updated_at,
        }
    }
}

/// Health check response.
#[derive(Debug, Serialize, Deserialize)]
pub struct HealthResponse {
    pub status: HealthStatus,
    pub database: HealthStatus,
    pub cache: HealthStatus,
}

/// Kafka click event payload — matches Python ClickEvent schema.
#[derive(Debug, Serialize, Deserialize)]
pub struct ClickEvent {
    pub short_code: String,
    pub delta: i64,
}

/// Keygen allocate response.
#[derive(Debug, Deserialize)]
pub struct AllocateResponse {
    pub start: i64,
    pub end: i64,
}
