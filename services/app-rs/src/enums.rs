/// Shared enums for the Rust URL shortener services.
///
/// These enums provide type safety for status fields across the codebase.
/// They serialize to strings for JSON compatibility with the Python stack.
use serde::{Deserialize, Serialize};

/// Health check status values.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum HealthStatus {
    Healthy,
    Unhealthy,
}

impl HealthStatus {
    /// Safely parse from string, falling back to Unhealthy for unknown values.
    pub fn from_str(s: &str) -> Self {
        match s {
            "healthy" => Self::Healthy,
            _ => Self::Unhealthy,
        }
    }
}

/// Service operational status values.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ServiceStatus {
    Pending,
    Running,
    Completed,
    Failed,
}

impl ServiceStatus {
    /// Safely parse from string, falling back to Failed for unknown values.
    pub fn from_str(s: &str) -> Self {
        match s {
            "pending" => Self::Pending,
            "running" => Self::Running,
            "completed" => Self::Completed,
            _ => Self::Failed,
        }
    }
}
