//! High-Performance Traffic Generator for URL Shortener
//!
//! Capable of generating 2000+ requests per second with configurable patterns.
//! Supports URL creation, redirects, and mixed traffic patterns.
//!
//! # Architecture
//!
//! ```text
//! ┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
//! │   Config        │    │  Worker Pool     │    │  Metrics        │
//! │                 │    │                  │    │                 │
//! │ • Target URL    │───▶│ • Tokio Tasks    │───▶│ • RPS Counter   │
//! │ • RPS Target    │    │ • HTTP Client    │    │ • Latency Stats │
//! │ • Duration      │    │ • Error Handling │    │ • Success Rate  │
//! │ • Pattern       │    │ • Rate Limiting  │    │ • Real-time     │
//! └─────────────────┘    └──────────────────┘    └─────────────────┘
//! ```

use anyhow::Result;
use clap::Parser;
use rand::Rng;
use reqwest::Client;
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::atomic::{AtomicU64, AtomicUsize, Ordering};
use tokio::sync::RwLock;
use tokio::time::interval;
use tracing::{error, info, warn};
use uuid::Uuid;

// ── Configuration ───────────────────────────────────────────────────────────────

#[derive(Parser)]
#[command(name = "traffic-generator")]
#[command(about = "High-performance traffic generator for URL shortener")]
struct Args {
    /// Target base URL (e.g., http://localhost:8080)
    #[arg(short, long, default_value = "http://localhost:8080")]
    target: String,

    /// Target requests per second
    #[arg(short, long, default_value = "2000")]
    rps: u64,

    /// Test duration in seconds
    #[arg(short, long, default_value = "60")]
    duration: u64,

    /// Traffic pattern: create, redirect, mixed
    #[arg(short, long, default_value = "mixed")]
    pattern: String,

    /// Number of worker tasks
    #[arg(short, long, default_value = "100")]
    workers: usize,

    /// Warmup duration in seconds
    #[arg(long, default_value = "5")]
    warmup: u64,
}

#[derive(Debug, Clone)]
enum TrafficPattern {
    Create,
    Redirect,
    Mixed,
}

impl TrafficPattern {
    fn from_str(s: &str) -> Self {
        match s.to_lowercase().as_str() {
            "create" => Self::Create,
            "redirect" => Self::Redirect,
            _ => Self::Mixed,
        }
    }
}

// ── Metrics ─────────────────────────────────────────────────────────────────────

#[derive(Debug, Default)]
struct Metrics {
    total_requests: AtomicU64,
    successful_requests: AtomicU64,
    failed_requests: AtomicU64,
    total_latency_ms: AtomicU64,
    max_latency_ms: AtomicU64,
    min_latency_ms: AtomicU64,
    created_urls: Arc<RwLock<Vec<String>>>,
}

impl Metrics {
    fn new() -> Self {
        Self {
            total_requests: AtomicU64::new(0),
            successful_requests: AtomicU64::new(0),
            failed_requests: AtomicU64::new(0),
            total_latency_ms: AtomicU64::new(0),
            max_latency_ms: AtomicU64::new(0),
            min_latency_ms: AtomicU64::new(u64::MAX),
            created_urls: Arc::new(RwLock::new(Vec::new())),
        }
    }

    fn record_request(&self, success: bool, latency_ms: u64) {
        self.total_requests.fetch_add(1, Ordering::Relaxed);
        
        if success {
            self.successful_requests.fetch_add(1, Ordering::Relaxed);
            self.total_latency_ms.fetch_add(latency_ms, Ordering::Relaxed);
            
            // Update min/max latency
            let mut current_max = self.max_latency_ms.load(Ordering::Relaxed);
            while latency_ms > current_max {
                match self.max_latency_ms.compare_exchange_weak(
                    current_max, latency_ms, Ordering::Relaxed, Ordering::Relaxed
                ) {
                    Ok(_) => break,
                    Err(x) => current_max = x,
                }
            }
            
            let mut current_min = self.min_latency_ms.load(Ordering::Relaxed);
            while latency_ms < current_min {
                match self.min_latency_ms.compare_exchange_weak(
                    current_min, latency_ms, Ordering::Relaxed, Ordering::Relaxed
                ) {
                    Ok(_) => break,
                    Err(x) => current_min = x,
                }
            }
        } else {
            self.failed_requests.fetch_add(1, Ordering::Relaxed);
        }
    }

    async fn add_created_url(&self, url: String) {
        self.created_urls.write().await.push(url);
    }

    fn get_stats(&self) -> TrafficStats {
        let total = self.total_requests.load(Ordering::Relaxed);
        let successful = self.successful_requests.load(Ordering::Relaxed);
        let failed = self.failed_requests.load(Ordering::Relaxed);
        let total_latency = self.total_latency_ms.load(Ordering::Relaxed);
        let max_latency = self.max_latency_ms.load(Ordering::Relaxed);
        let min_latency = self.min_latency_ms.load(Ordering::Relaxed);

        let avg_latency = if successful > 0 {
            total_latency / successful
        } else {
            0
        };

        TrafficStats {
            total_requests: total,
            successful_requests: successful,
            failed_requests: failed,
            success_rate: if total > 0 {
                (successful as f64 / total as f64) * 100.0
            } else {
                0.0
            },
            avg_latency_ms: avg_latency,
            min_latency_ms: if min_latency == u64::MAX { 0 } else { min_latency },
            max_latency_ms: max_latency,
        }
    }
}

#[derive(Debug, Serialize)]
struct TrafficStats {
    total_requests: u64,
    successful_requests: u64,
    failed_requests: u64,
    success_rate: f64,
    avg_latency_ms: u64,
    min_latency_ms: u64,
    max_latency_ms: u64,
}

// ── Traffic Generator ───────────────────────────────────────────────────────────

struct TrafficGenerator {
    client: Client,
    metrics: Arc<Metrics>,
    args: Args,
    pattern: TrafficPattern,
}

impl TrafficGenerator {
    fn new(args: Args) -> Self {
        let client = Client::builder()
            .timeout(Duration::from_secs(10))
            .pool_max_idle_per_host(100)
            .build()
            .expect("Failed to create HTTP client");

        Self {
            client,
            metrics: Arc::new(Metrics::new()),
            args,
            pattern: TrafficPattern::from_str(&args.pattern),
        }
    }

    async fn run(&self) -> Result<()> {
        info!("🚀 Starting traffic generator");
        info!("📊 Target: {} RPS for {} seconds", self.args.rps, self.args.duration);
        info!("🎯 Pattern: {:?}", self.pattern);
        info!("👥 Workers: {}", self.args.workers);

        // Warmup phase
        if self.args.warmup > 0 {
            info!("🔥 Warming up for {} seconds...", self.args.warmup);
            self.warmup().await?;
        }

        // Start metrics reporter
        let metrics = Arc::clone(&self.metrics);
        let duration = self.args.duration;
        tokio::spawn(async move {
            let mut interval = interval(Duration::from_secs(5));
            let start_time = Instant::now();
            
            loop {
                interval.tick().await;
                let elapsed = start_time.elapsed().as_secs();
                let stats = metrics.get_stats();
                
                info!(
                    "📈 [{}s] RPS: {:.1}, Success: {:.1}%, Avg Latency: {}ms, Min/Max: {}ms/{}ms",
                    elapsed,
                    stats.total_requests as f64 / elapsed as f64,
                    stats.success_rate,
                    stats.avg_latency_ms,
                    stats.min_latency_ms,
                    stats.max_latency_ms
                );

                if elapsed >= duration {
                    break;
                }
            }
        });

        // Main traffic generation
        self.generate_traffic().await?;

        // Final report
        self.print_final_report().await;
        Ok(())
    }

    async fn warmup(&self) -> Result<()> {
        let warmup_start = Instant::now();
        let warmup_duration = Duration::from_secs(self.args.warmup);
        
        while warmup_start.elapsed() < warmup_duration {
            // Generate low-intensity traffic during warmup
            for _ in 0..10 {
                self.send_request().await;
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
        
        info!("✅ Warmup completed");
        Ok(())
    }

    async fn generate_traffic(&self) -> Result<()> {
        let start_time = Instant::now();
        let duration = Duration::from_secs(self.args.duration);
        let interval_between_requests = Duration::from_nanos(1_000_000_000 / self.args.rps);
        
        // Create worker tasks
        let mut handles = Vec::new();
        for worker_id in 0..self.args.workers {
            let generator = self.clone_for_worker(worker_id);
            let handle = tokio::spawn(async move {
                generator.worker_loop(start_time, duration, interval_between_requests).await;
            });
            handles.push(handle);
        }

        // Wait for all workers to complete
        for handle in handles {
            handle.await?;
        }

        Ok(())
    }

    fn clone_for_worker(&self, worker_id: usize) -> Self {
        Self {
            client: self.client.clone(),
            metrics: Arc::clone(&self.metrics),
            args: self.args.clone(),
            pattern: self.pattern.clone(),
        }
    }

    async fn worker_loop(&self, start_time: Instant, duration: Duration, interval: Duration) {
        let mut next_request_time = start_time + (Duration::from_millis(100) * rand::thread_rng().gen_range(0..10));
        
        while start_time.elapsed() < duration {
            let now = Instant::now();
            
            if now >= next_request_time {
                self.send_request().await;
                next_request_time = now + interval;
            } else {
                tokio::time::sleep(next_request_time - now).await;
            }
        }
    }

    async fn send_request(&self) {
        let start_time = Instant::now();
        let success = match self.pattern {
            TrafficPattern::Create => self.send_create_request().await,
            TrafficPattern::Redirect => self.send_redirect_request().await,
            TrafficPattern::Mixed => {
                // 70% create, 30% redirect
                if rand::thread_rng().gen_range(0..100) < 70 {
                    self.send_create_request().await
                } else {
                    self.send_redirect_request().await
                }
            }
        };
        
        let latency_ms = start_time.elapsed().as_millis() as u64;
        self.metrics.record_request(success, latency_ms);
    }

    async fn send_create_request(&self) -> bool {
        let url = format!("https://example-{}.com", Uuid::new_v4());
        
        match self.client
            .post(&format!("{}/api/shorten", self.args.target))
            .json(&serde_json::json!({"url": url}))
            .send()
            .await
        {
            Ok(response) => {
                if response.status().is_success() {
                    if let Ok(body) = response.json::<serde_json::Value>().await {
                        if let Some(short_url) = body.get("short_url").and_then(|v| v.as_str()) {
                            self.metrics.add_created_url(short_url.to_string()).await;
                        }
                    }
                    true
                } else {
                    warn!("Create request failed: {}", response.status());
                    false
                }
            }
            Err(e) => {
                error!("Create request error: {}", e);
                false
            }
        }
    }

    async fn send_redirect_request(&self) -> bool {
        let urls = self.metrics.created_urls.read().await;
        if urls.is_empty() {
            return false;
        }

        let random_url = urls[rand::thread_rng().gen_range(0..urls.len())].clone();
        drop(urls);

        // Extract short code from URL
        if let Some(code) = random_url.split('/').last() {
            match self.client.get(&format!("{}/{}", self.args.target, code)).send().await {
                Ok(response) => response.status().is_success(),
                Err(e) => {
                    error!("Redirect request error: {}", e);
                    false
                }
            }
        } else {
            false
        }
    }

    async fn print_final_report(&self) {
        let stats = self.metrics.get_stats();
        let created_urls = self.metrics.created_urls.read().await;
        
        println!("\n🎯 📊 🚀 TRAFFIC GENERATION COMPLETE 🚀 📊 🎯\n");
        println!("📈 Performance Summary:");
        println!("   Total Requests: {}", stats.total_requests);
        println!("   Successful: {}", stats.successful_requests);
        println!("   Failed: {}", stats.failed_requests);
        println!("   Success Rate: {:.2}%", stats.success_rate);
        println!("   Avg RPS: {:.2}", stats.total_requests as f64 / self.args.duration as f64);
        println!("   Avg Latency: {}ms", stats.avg_latency_ms);
        println!("   Min Latency: {}ms", stats.min_latency_ms);
        println!("   Max Latency: {}ms", stats.max_latency_ms);
        println!("   URLs Created: {}", created_urls.len());
        
        if stats.total_requests > 0 {
            println!("\n🎯 Target vs Actual:");
            println!("   Target RPS: {}", self.args.rps);
            println!("   Actual RPS: {:.2}", stats.total_requests as f64 / self.args.duration as f64);
            println!("   Achievement: {:.1}%", (stats.total_requests as f64 / self.args.duration as f64) / self.args.rps as f64 * 100.0);
        }
        
        println!("\n✅ Traffic generation completed successfully!");
    }
}

// ── Main ───────────────────────────────────────────────────────────────────────

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::registry()
        .with(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info".into()),
        )
        .with(tracing_subscriber::fmt::layer())
        .init();

    let args = Args::parse();
    let generator = TrafficGenerator::new(args);
    generator.run().await
}
