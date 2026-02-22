#!/usr/bin/env python3
"""
Quick benchmark script for Keygen Service performance testing.

Provides fast performance measurements for:
- Single request latency
- Concurrent request throughput
- Resource utilization
- Service health metrics
"""

import asyncio
import aiohttp
import time
import json
import statistics
import psutil
import sys
import os
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class BenchmarkMetrics:
    operation: str
    rps: float
    avg_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    min_latency_ms: float
    max_latency_ms: float
    error_rate: float
    total_requests: int
    successful_requests: int
    duration: float
    cpu_usage: float
    memory_usage_mb: float

class QuickBenchmark:
    def __init__(self, base_url: str = "http://localhost:8001"):
        self.base_url = base_url
        self.session = None
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10),
            connector=aiohttp.TCPConnector(limit=100)
        )
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def run_quick_benchmark(self) -> Dict[str, Any]:
        """Run quick benchmark suite."""
        logger.info("🚀 Running quick benchmark suite...")
        
        results = {}
        
        # Test 1: Health check
        health_ok = await self.health_check()
        if not health_ok:
            return {"error": "Service not healthy"}
        
        # Test 2: Single request benchmark
        results["single_request"] = await self.benchmark_single_request()
        
        # Test 3: Concurrent requests benchmark
        results["concurrent_requests"] = await self.benchmark_concurrent_requests()
        
        # Test 4: Sustained load benchmark
        results["sustained_load"] = await self.benchmark_sustained_load()
        
        # Test 5: Resource utilization
        results["resource_utilization"] = await self.measure_resource_utilization()
        
        # Generate summary
        return self.generate_benchmark_summary(results)

    async def health_check(self) -> bool:
        """Check if service is healthy."""
        try:
            async with self.session.get(f"{self.base_url}/health") as response:
                if response.status == 200:
                    health = await response.json()
                    logger.info(f"Service health: {health.get('status', 'unknown')}")
                    return True
                else:
                    logger.error(f"Health check failed: HTTP {response.status}")
                    return False
        except Exception as e:
            logger.error(f"Health check error: {e}")
            return False

    async def benchmark_single_request(self) -> BenchmarkMetrics:
        """Benchmark single request performance."""
        logger.info("📊 Benchmarking single requests...")
        
        warmup_requests = 10
        test_requests = 100
        range_size = 100
        
        # Warmup
        for _ in range(warmup_requests):
            try:
                async with self.session.post(f"{self.base_url}/allocate", 
                                         json={"range_size": range_size}) as response:
                    await response.release()
            except:
                pass
        
        # Benchmark
        latencies = []
        errors = 0
        start_time = time.time()
        
        for _ in range(test_requests):
            request_start = time.time()
            try:
                async with self.session.post(f"{self.base_url}/allocate", 
                                             json={"range_size": range_size}) as response:
                    if response.status == 200:
                        await response.json()
                        await response.release()
                        latency = (time.time() - request_start) * 1000
                        latencies.append(latency)
                    else:
                        errors += 1
                        await response.release()
            except Exception:
                errors += 1
        
        duration = time.time() - start_time
        
        # Calculate metrics
        if latencies:
            latencies.sort()
            rps = test_requests / duration
            avg_latency = statistics.mean(latencies)
            p95_latency = latencies[int(0.95 * len(latencies))]
            p99_latency = latencies[int(0.99 * len(latencies))]
            min_latency = min(latencies)
            max_latency = max(latencies)
        else:
            rps = avg_latency = p95_latency = p99_latency = min_latency = max_latency = 0
        
        error_rate = errors / test_requests
        
        metrics = BenchmarkMetrics(
            operation="single_request",
            rps=rps,
            avg_latency_ms=avg_latency,
            p95_latency_ms=p95_latency,
            p99_latency_ms=p99_latency,
            min_latency_ms=min_latency,
            max_latency_ms=max_latency,
            error_rate=error_rate,
            total_requests=test_requests,
            successful_requests=len(latencies),
            duration=duration,
            cpu_usage=0,  # Will be measured separately
            memory_usage_mb=0
        )
        
        logger.info(f"Single request: {rps:.1f} RPS, Avg: {avg_latency:.2f}ms, P95: {p95_latency:.2f}ms")
        return metrics

    async def benchmark_concurrent_requests(self) -> BenchmarkMetrics:
        """Benchmark concurrent request performance."""
        logger.info("📊 Benchmarking concurrent requests...")
        
        concurrency_levels = [5, 10, 25, 50]
        best_metrics = None
        best_rps = 0
        
        for concurrency in concurrency_levels:
            logger.info(f"Testing concurrency: {concurrency}")
            
            requests_per_level = 200
            range_size = 50
            
            # Create semaphore for concurrency control
            semaphore = asyncio.Semaphore(concurrency)
            
            async def bounded_request():
                async with semaphore:
                    request_start = time.time()
                    try:
                        async with self.session.post(f"{self.base_url}/allocate", 
                                                     json={"range_size": range_size}) as response:
                            if response.status == 200:
                                await response.json()
                                await response.release()
                                return (time.time() - request_start) * 1000, None
                            else:
                                await response.release()
                                return None, f"HTTP {response.status}"
                    except Exception as e:
                        return None, str(e)
            
            # Execute requests
            start_time = time.time()
            tasks = [bounded_request() for _ in range(requests_per_level)]
            responses = await asyncio.gather(*tasks)
            duration = time.time() - start_time
            
            # Process results
            latencies = [r[0] for r in responses if r[0] is not None]
            errors = [r[1] for r in responses if r[1] is not None]
            
            if latencies:
                latencies.sort()
                rps = requests_per_level / duration
                avg_latency = statistics.mean(latencies)
                p95_latency = latencies[int(0.95 * len(latencies))]
                p99_latency = latencies[int(0.99 * len(latencies))]
                min_latency = min(latencies)
                max_latency = max(latencies)
                error_rate = len(errors) / requests_per_level
                
                metrics = BenchmarkMetrics(
                    operation=f"concurrent_{concurrency}",
                    rps=rps,
                    avg_latency_ms=avg_latency,
                    p95_latency_ms=p95_latency,
                    p99_latency_ms=p99_latency,
                    min_latency_ms=min_latency,
                    max_latency_ms=max_latency,
                    error_rate=error_rate,
                    total_requests=requests_per_level,
                    successful_requests=len(latencies),
                    duration=duration,
                    cpu_usage=0,
                    memory_usage_mb=0
                )
                
                logger.info(f"Concurrency {concurrency}: {rps:.1f} RPS, P95: {p95_latency:.2f}ms, Errors: {error_rate:.2%}")
                
                if rps > best_rps:
                    best_rps = rps
                    best_metrics = metrics
        
        return best_metrics or BenchmarkMetrics("concurrent", 0, 0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 0)

    async def benchmark_sustained_load(self) -> BenchmarkMetrics:
        """Benchmark sustained load performance."""
        logger.info("📊 Benchmarking sustained load...")
        
        duration_seconds = 30
        target_rps = 100
        range_size = 10
        
        start_time = time.time()
        end_time = start_time + duration_seconds
        
        latencies = []
        errors = 0
        total_requests = 0
        
        while time.time() < end_time:
            batch_start = time.time()
            batch_size = max(1, int(target_rps * 0.1))  # 10% of target RPS per batch
            
            # Create batch of requests
            tasks = []
            for _ in range(batch_size):
                task = self.session.post(f"{self.base_url}/allocate", 
                                        json={"range_size": range_size})
                tasks.append(task)
            
            # Execute batch
            for task in tasks:
                request_start = time.time()
                try:
                    async with task as response:
                        if response.status == 200:
                            await response.json()
                            await response.release()
                            latencies.append((time.time() - request_start) * 1000)
                        else:
                            errors += 1
                            await response.release()
                except Exception:
                    errors += 1
                    
                total_requests += 1
            
            # Rate limiting
            batch_duration = time.time() - batch_start
            expected_batch_duration = batch_size / target_rps
            if batch_duration < expected_batch_duration:
                await asyncio.sleep(expected_batch_duration - batch_duration)
        
        actual_duration = time.time() - start_time
        
        # Calculate metrics
        if latencies:
            latencies.sort()
            rps = total_requests / actual_duration
            avg_latency = statistics.mean(latencies)
            p95_latency = latencies[int(0.95 * len(latencies))]
            p99_latency = latencies[int(0.99 * len(latencies))]
            min_latency = min(latencies)
            max_latency = max(latencies)
        else:
            rps = avg_latency = p95_latency = p99_latency = min_latency = max_latency = 0
        
        error_rate = errors / total_requests
        
        metrics = BenchmarkMetrics(
            operation="sustained_load",
            rps=rps,
            avg_latency_ms=avg_latency,
            p95_latency_ms=p95_latency,
            p99_latency_ms=p99_latency,
            min_latency_ms=min_latency,
            max_latency_ms=max_latency,
            error_rate=error_rate,
            total_requests=total_requests,
            successful_requests=len(latencies),
            duration=actual_duration,
            cpu_usage=0,
            memory_usage_mb=0
        )
        
        logger.info(f"Sustained load: {rps:.1f} RPS, Avg: {avg_latency:.2f}ms, Duration: {actual_duration:.1f}s")
        return metrics

    async def measure_resource_utilization(self) -> Dict[str, Any]:
        """Measure system resource utilization."""
        logger.info("📊 Measuring resource utilization...")
        
        # Get current process
        process = psutil.Process()
        
        # Measure CPU and memory usage
        cpu_percent = process.cpu_percent(interval=1)
        memory_info = process.memory_info()
        memory_mb = memory_info.rss / 1024 / 1024  # Convert to MB
        
        # Get system-wide metrics
        system_cpu = psutil.cpu_percent(interval=1)
        system_memory = psutil.virtual_memory()
        
        utilization = {
            "process_cpu_percent": cpu_percent,
            "process_memory_mb": memory_mb,
            "system_cpu_percent": system_cpu,
            "system_memory_percent": system_memory.percent,
            "system_memory_available_gb": system_memory.available / 1024 / 1024 / 1024,
            "timestamp": datetime.now().isoformat()
        }
        
        logger.info(f"Process CPU: {cpu_percent:.1f}%, Memory: {memory_mb:.1f}MB")
        logger.info(f"System CPU: {system_cpu:.1f}%, Memory: {system_memory.percent:.1f}%")
        
        return utilization

    def generate_benchmark_summary(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Generate benchmark summary."""
        
        # Extract key metrics
        single_request = results.get("single_request")
        concurrent_requests = results.get("concurrent_requests")
        sustained_load = results.get("sustained_load")
        resource_util = results.get("resource_utilization", {})
        
        # Calculate overall metrics
        best_rps = 0
        best_latency = float('inf')
        
        for metrics in [single_request, concurrent_requests, sustained_load]:
            if metrics and hasattr(metrics, 'rps'):
                best_rps = max(best_rps, metrics.rps)
                best_latency = min(best_latency, metrics.avg_latency_ms)
        
        # Performance rating
        performance_rating = "Unknown"
        if best_rps >= 1000 and best_latency <= 1:
            performance_rating = "Excellent"
        elif best_rps >= 500 and best_latency <= 2:
            performance_rating = "Good"
        elif best_rps >= 200 and best_latency <= 5:
            performance_rating = "Acceptable"
        else:
            performance_rating = "Needs Improvement"
        
        summary = {
            "performance_rating": performance_rating,
            "best_rps": best_rps,
            "best_latency_ms": best_latency,
            "detailed_results": results,
            "resource_utilization": resource_util,
            "timestamp": datetime.now().isoformat()
        }
        
        # Print summary
        self.print_benchmark_summary(summary)
        
        return summary

    def print_benchmark_summary(self, summary: Dict[str, Any]):
        """Print benchmark summary."""
        logger.info("\n" + "=" * 60)
        logger.info("🎯 QUICK BENCHMARK RESULTS")
        logger.info("=" * 60)
        
        logger.info(f"Performance Rating: {summary['performance_rating']}")
        logger.info(f"Best RPS: {summary['best_rps']:.1f}")
        logger.info(f"Best Latency: {summary['best_latency_ms']:.2f}ms")
        
        # Detailed results
        results = summary["detailed_results"]
        
        if "single_request" in results:
            sr = results["single_request"]
            logger.info(f"\nSingle Request:")
            logger.info(f"  RPS: {sr.rps:.1f}")
            logger.info(f"  Avg Latency: {sr.avg_latency_ms:.2f}ms")
            logger.info(f"  P95 Latency: {sr.p95_latency_ms:.2f}ms")
            logger.info(f"  Error Rate: {sr.error_rate:.2%}")
        
        if "concurrent_requests" in results:
            cr = results["concurrent_requests"]
            logger.info(f"\nConcurrent Requests:")
            logger.info(f"  RPS: {cr.rps:.1f}")
            logger.info(f"  Avg Latency: {cr.avg_latency_ms:.2f}ms")
            logger.info(f"  P95 Latency: {cr.p95_latency_ms:.2f}ms")
            logger.info(f"  Error Rate: {cr.error_rate:.2%}")
        
        if "sustained_load" in results:
            sl = results["sustained_load"]
            logger.info(f"\nSustained Load:")
            logger.info(f"  RPS: {sl.rps:.1f}")
            logger.info(f"  Avg Latency: {sl.avg_latency_ms:.2f}ms")
            logger.info(f"  P95 Latency: {sl.p95_latency_ms:.2f}ms")
            logger.info(f"  Error Rate: {sl.error_rate:.2%}")
        
        # Resource utilization
        resource_util = summary.get("resource_utilization", {})
        if resource_util:
            logger.info(f"\nResource Utilization:")
            logger.info(f"  Process CPU: {resource_util.get('process_cpu_percent', 0):.1f}%")
            logger.info(f"  Process Memory: {resource_util.get('process_memory_mb', 0):.1f}MB")
            logger.info(f"  System CPU: {resource_util.get('system_cpu_percent', 0):.1f}%")
            logger.info(f"  System Memory: {resource_util.get('system_memory_percent', 0):.1f}%")
        
        logger.info("\n" + "=" * 60)
        if summary['performance_rating'] == "Excellent":
            logger.info("🎉 EXCELLENT PERFORMANCE!")
        elif summary['performance_rating'] == "Good":
            logger.info("✅ GOOD PERFORMANCE")
        elif summary['performance_rating'] == "Acceptable":
            logger.info("⚠️  ACCEPTABLE PERFORMANCE")
        else:
            logger.info("❌ NEEDS IMPROVEMENT")
        logger.info("=" * 60)

async def main():
    """Main benchmark runner."""
    base_url = os.getenv("TARGET_SERVICE", "http://localhost:8001")
    
    async with QuickBenchmark(base_url) as benchmark:
        results = await benchmark.run_quick_benchmark()
        
        # Save results
        os.makedirs("/app/results", exist_ok=True)
        with open("/app/results/quick_benchmark.json", "w") as f:
            json.dump(results, f, indent=2)
        
        logger.info(f"\nDetailed results saved to: /app/results/quick_benchmark.json")
        
        # Determine success
        success = results["performance_rating"] in ["Excellent", "Good", "Acceptable"]
        sys.exit(0 if success else 1)

if __name__ == "__main__":
    asyncio.run(main())
