use anyhow::{anyhow, Result};
use std::sync::Arc;
use tokio::sync::Mutex;

use crate::models::AllocateResponse;

/// Local block of pre-allocated IDs fetched from the keygen service.
/// Mirrors the Python _allocate_id_block / _generate_short_code_from_allocator logic.
struct IdBlock {
    current: i64,
    end: i64,
}

pub struct KeygenClient {
    keygen_url: String,
    http: reqwest::Client,
    block: Arc<Mutex<Option<IdBlock>>>,
    id_block_size: i64,
}

impl KeygenClient {
    pub fn new(keygen_url: String, id_block_size: i64) -> Self {
        Self {
            keygen_url,
            http: reqwest::Client::new(),
            block: Arc::new(Mutex::new(None)),
            id_block_size,
        }
    }

    async fn fetch_block(&self) -> Result<IdBlock> {
        let url = format!("{}/allocate", self.keygen_url);
        let resp = self
            .http
            .post(&url)
            .json(&serde_json::json!({
                "size": self.id_block_size,
                "stack": "rust"
            }))
            .send()
            .await?
            .error_for_status()?
            .json::<AllocateResponse>()
            .await?;
        Ok(IdBlock {
            current: resp.start,
            end: resp.end,
        })
    }

    /// Get the next unique numeric ID, fetching a new block from keygen when exhausted.
    pub async fn next_id(&self) -> Result<i64> {
        let mut guard = self.block.lock().await;
        if let Some(ref mut block) = *guard {
            if block.current <= block.end {
                let id = block.current;
                block.current += 1;
                return Ok(id);
            }
        }
        // Block exhausted or not yet fetched — get a new one.
        let new_block = self.fetch_block().await?;
        let id = new_block.current;
        *guard = Some(IdBlock {
            current: new_block.current + 1,
            end: new_block.end,
        });
        Ok(id)
    }
}

/// Encode a numeric ID to a base-62 short code, left-padded to `length` chars.
pub fn encode_id(id: i64, length: usize) -> Result<String> {
    if id < 0 {
        return Err(anyhow!("id must be non-negative"));
    }
    let encoded = base62::encode(id as u64);
    // Left-pad with '0' (base62 zero char) to ensure consistent length.
    let padded = if encoded.len() < length {
        format!("{:0>width$}", encoded, width = length)
    } else {
        encoded[encoded.len() - length..].to_string()
    };
    Ok(padded)
}
