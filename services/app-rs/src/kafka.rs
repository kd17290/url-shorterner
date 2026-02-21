use anyhow::Result;
use rdkafka::config::ClientConfig;
use rdkafka::producer::{FutureProducer, FutureRecord};
use std::time::Duration;

use crate::models::ClickEvent;

pub fn create_producer(bootstrap_servers: &str) -> Result<FutureProducer> {
    let producer = ClientConfig::new()
        .set("bootstrap.servers", bootstrap_servers)
        .set("message.timeout.ms", "2000")
        .set("queue.buffering.max.messages", "100000")
        .set("queue.buffering.max.ms", "5")
        .create()?;
    Ok(producer)
}

/// Publish a click event to Kafka. Returns Ok(true) on success, Ok(false) on timeout/error.
/// Never propagates errors — caller falls back to Redis stream.
pub async fn publish_click(producer: &FutureProducer, topic: &str, event: &ClickEvent) -> bool {
    let payload = match serde_json::to_string(event) {
        Ok(p) => p,
        Err(_) => return false,
    };
    let record = FutureRecord::to(topic)
        .payload(&payload)
        .key(&event.short_code);
    producer
        .send(record, Duration::from_millis(500))
        .await
        .is_ok()
}
