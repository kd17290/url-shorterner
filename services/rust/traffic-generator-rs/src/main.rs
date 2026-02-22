use anyhow::Result;
use clap::Parser;
use rand::Rng;
use reqwest::Client;
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::Semaphore;
use log::{info, error, warn};

#[derive(Parser)]
#[command(name = "traffic-generator-rs")]
#[command(about = "High-performance traffic generator for URL shortener")]
struct Args {
    /// Target service URL
    #[arg(long, default_value = "http://localhost:8080")]
    target_url: String,

    /// Number of concurrent workers
    #[arg(long, default_value = "100")]
    workers: usize,

    /// Read requests per second (per URL)
    #[arg(long, default_value = "2000")]
    read_rps: u32,

    /// Write requests per second (per URL)
    #[arg(long, default_value = "1000")]
    write_rps: u32,

    /// Number of URLs to generate traffic for
    #[arg(long, default_value = "10")]
    url_count: usize,

    /// Duration in seconds
    #[arg(long, default_value = "60")]
    duration: u64,

    /// Warmup duration in seconds
    #[arg(long, default_value = "10")]
    warmup: u64,
}

#[derive(Debug, Serialize, Deserialize)]
struct CreateUrlRequest {
    url: String,
    custom_code: Option<String>,
}

#[derive(Debug, Serialize, Deserialize)]
struct CreateUrlResponse {
    id: u64,
    short_code: String,
    original_url: String,
    short_url: String,
    clicks: u64,
    created_at: String,
    updated_at: String,
}

#[derive(Clone)]
struct TrafficGenerator {
    client: Client,
    args: Args,
    urls: Arc<Vec<String>>,
    read_success: std::sync::atomic::AtomicU64,
    read_errors: std::sync::atomic::AtomicU64,
    write_success: std::sync::atomic::AtomicU64,
    write_errors: std::sync::atomic::AtomicU64,
}

impl TrafficGenerator {
    fn new(args: Args) -> Self {
        let client = Client::builder()
            .timeout(Duration::from_secs(10))
            .build()
            .expect("Failed to create HTTP client");

        Self {
            client,
            args,
            urls: Arc::new(Vec::new()),
            read_success: std::sync::atomic::AtomicU64::new(0),
            read_errors: std::sync::atomic::AtomicU64::new(0),
            write_success: std::sync::atomic::AtomicU64::new(0),
            write_errors: std::sync::atomic::AtomicU64::new(0),
        }
    }

    async fn setup_urls(&mut self) -> Result<()> {
        info!("Setting up {} URLs for testing...", self.args.url_count);

        let mut urls = Vec::new();

        // For simplicity, generate test URLs without actually creating them
        for i in 0..self.args.url_count {
            urls.push(format!("test{}", i));
        }

        self.urls = Arc::new(urls);

        info!("Setup complete. Ready to generate traffic for {} URLs", self.args.url_count);
        Ok(())
    }

    async fn run_read_traffic(&self, url: &str, duration: Duration) -> Result<()> {
        let start_time = Instant::now();
        let interval = Duration::from_secs(1) / self.args.read_rps;

        while start_time.elapsed() < duration {
            let request_start = Instant::now();

            match self.client.get(&format!("{}/{}", self.args.target_url, url)).send().await {
                Ok(response) => {
                    if response.status().is_success() {
                        self.read_success.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                    } else {
                        self.read_errors.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                        warn!("Read request failed for URL {}: {}", url, response.status());
                    }
                }
                Err(e) => {
                    self.read_errors.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                    error!("Read request error for URL {}: {}", url, e);
                }
            }

            // Rate limiting
            let elapsed = request_start.elapsed();
            if elapsed < interval {
                tokio::time::sleep(interval - elapsed).await;
            }
        }

        Ok(())
    }

    async fn run_write_traffic(&self, duration: Duration) -> Result<()> {
        let start_time = Instant::now();
        let interval = Duration::from_secs(1) / self.args.write_rps;

        while start_time.elapsed() < duration {
            let request_start = Instant::now();

            let url = format!("https://random-{}.example.com", rand::thread_rng().gen::<u32>());
            let create_req = CreateUrlRequest {
                url: url.clone(),
                custom_code: None,
            };

            match self.client
                .post(&format!("{}/api/shorten", self.args.target_url))
                .json(&create_req)
                .send()
                .await
            {
                Ok(response) => {
                    if response.status().is_success() {
                        self.write_success.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                    } else {
                        self.write_errors.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                        warn!("Write request failed: {}", response.status());
                    }
                }
                Err(e) => {
                    self.write_errors.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                    error!("Write request error: {}", e);
                }
            }

            // Rate limiting
            let elapsed = request_start.elapsed();
            if elapsed < interval {
                tokio::time::sleep(interval - elapsed).await;
            }
        }

        Ok(())
    }

    async fn run(&mut self) -> Result<()> {
        env_logger::init();

        info!("Starting traffic generator");
        info!("Target: {}", self.args.target_url);
        info!("Workers: {}", self.args.workers);
        info!("Read RPS: {} per URL", self.args.read_rps);
        info!("Write RPS: {}", self.args.write_rps);
        info!("URL count: {}", self.args.url_count);
        info!("Duration: {}s", self.args.duration);

        // Setup URLs
        self.setup_urls().await?;

        // Warmup phase
        info!("Starting warmup phase for {}s", self.args.warmup);
        let warmup_duration = Duration::from_secs(self.args.warmup);
        tokio::time::sleep(warmup_duration).await;

        // Main traffic generation
        info!("Starting main traffic generation for {}s", self.args.duration);
        let main_duration = Duration::from_secs(self.args.duration);

        let semaphore = Arc::new(Semaphore::new(self.args.workers));
        let mut tasks = Vec::new();

        // Spawn read tasks for each URL
        for url in self.urls.iter().cloned() {
            let generator = self.clone();
            let permit = semaphore.clone().acquire_owned().await?;

            let task = tokio::spawn(async move {
                let _permit = permit;
                if let Err(e) = generator.run_read_traffic(&url, main_duration).await {
                    error!("Read traffic error for URL {}: {}", url, e);
                }
            });

            tasks.push(task);
        }

        // Spawn write task
        let generator = self.clone();
        let write_task = tokio::spawn(async move {
            if let Err(e) = generator.run_write_traffic(main_duration).await {
                error!("Write traffic error: {}", e);
            }
        });
        tasks.push(write_task);

        // Wait for all tasks to complete
        for task in tasks {
            if let Err(e) = task.await {
                error!("Task error: {}", e);
            }
        }

        // Print final metrics
        self.print_final_metrics().await;

        Ok(())
    }

    async fn print_final_metrics(&self) {
        info!("=== Final Traffic Generation Metrics ===");

        let read_success = self.read_success.load(std::sync::atomic::Ordering::Relaxed);
        let write_success = self.write_success.load(std::sync::atomic::Ordering::Relaxed);
        let read_errors = self.read_errors.load(std::sync::atomic::Ordering::Relaxed);
        let write_errors = self.write_errors.load(std::sync::atomic::Ordering::Relaxed);

        let total_read = read_success + read_errors;
        let total_write = write_success + write_errors;

        info!("Read Requests: {} success, {} errors, {} total", read_success, read_errors, total_read);
        info!("Write Requests: {} success, {} errors, {} total", write_success, write_errors, total_write);

        if total_read > 0 {
            info!("Read Success Rate: {:.2}%", (read_success as f64 / total_read as f64) * 100.0);
        }
        if total_write > 0 {
            info!("Write Success Rate: {:.2}%", (write_success as f64 / total_write as f64) * 100.0);
        }

        let total_rps = (self.args.read_rps * self.args.url_count as u32) + self.args.write_rps;
        info!("Target RPS: {}", total_rps);
        info!("Active URLs: {}", self.args.url_count);
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    let args = Args::parse();
    let mut generator = TrafficGenerator::new(args);

    generator.run().await?;

    Ok(())
}
