use anyhow::Result;
use redis::aio::ConnectionManager;
use redis::AsyncCommands;

use crate::models::Url;

pub async fn create_client(url: &str) -> Result<ConnectionManager> {
    let client = redis::Client::open(url)?;
    let mgr = ConnectionManager::new(client).await?;
    Ok(mgr)
}

const URL_TTL_SECONDS: u64 = 3600;

pub fn url_cache_key(short_code: &str) -> String {
    format!("url:{short_code}")
}

pub fn click_buffer_key(prefix: &str, short_code: &str) -> String {
    format!("{prefix}:{short_code}")
}

/// Get a URL from cache. Returns None on miss or error (fail-open).
pub async fn get_url(conn: &mut ConnectionManager, short_code: &str) -> Option<Url> {
    let key = url_cache_key(short_code);
    let raw: Option<String> = conn.get(&key).await.ok()?;
    let raw = raw?;
    serde_json::from_str(&raw).ok()
}

/// Set a URL in cache with TTL.
pub async fn set_url(conn: &mut ConnectionManager, url: &Url) -> Result<()> {
    let key = url_cache_key(&url.short_code);
    let value = serde_json::to_string(url)?;
    let _: () = conn.set_ex(&key, value, URL_TTL_SECONDS).await?;
    Ok(())
}

/// Increment click buffer counter. Returns new count.
pub async fn incr_click_buffer(
    conn: &mut ConnectionManager,
    prefix: &str,
    short_code: &str,
    ttl: u64,
) -> Result<i64> {
    let key = click_buffer_key(prefix, short_code);
    let count: i64 = conn.incr(&key, 1i64).await?;
    if count == 1 {
        let _: () = conn.expire(&key, ttl as i64).await?;
    }
    Ok(count)
}

/// Push a click event to the Redis fallback stream (when Kafka is unavailable).
pub async fn push_fallback_stream(
    conn: &mut ConnectionManager,
    stream_key: &str,
    short_code: &str,
    delta: i64,
) -> Result<()> {
    let _: String = conn
        .xadd(
            stream_key,
            "*",
            &[("short_code", short_code), ("delta", &delta.to_string())],
        )
        .await?;
    Ok(())
}

pub async fn ping(conn: &mut ConnectionManager) -> Result<()> {
    let _: String = redis::cmd("PING").query_async(conn).await?;
    Ok(())
}
