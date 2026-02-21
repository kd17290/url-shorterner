#!/usr/bin/env python3
"""
Simple benchmark script to test URL generation performance.
Tests both direct app access and measures the scalability improvements.
"""

import asyncio
import httpx
import json
import time
from typing import List, Dict, Any
import statistics

async def benchmark_stack(name: str, base_url: str, num_requests: int = 100):
    """Benchmark a URL shortener stack."""
    print(f"\n=== {name} Benchmark ===")
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        # Test health endpoint first
        try:
            health = await client.get(f"{base_url}/health")
            print(f"Health: {health.json()}")
        except Exception as e:
            print(f"Health check failed: {e}")
            return
        
        # Benchmark URL creation
        print(f"Creating {num_requests} URLs...")
        start_time = time.time()
        
        tasks = []
        latencies = []
        
        for i in range(num_requests):
            task_start = time.time()
            try:
                response = await client.post(
                    f"{base_url}/api/shorten", 
                    json={"url": f"https://example.com/test/{i}"}
                )
                latency = time.time() - task_start
                if response.status_code == 201:
                    latencies.append(latency)
                else:
                    print(f"Failed request {i}: {response.status_code}")
            except Exception as e:
                print(f"Request {i} failed: {e}")
        
        elapsed = time.time() - start_time
        successful = len(latencies)
        
        if successful > 0:
            print(f"✅ Created {successful}/{num_requests} URLs in {elapsed:.2f}s")
            print(f"📊 RPS: {successful/elapsed:.2f}")
            print(f"⏱️  Avg Latency: {statistics.mean(latencies)*1000:.2f}ms")
            print(f"📈 P95 Latency: {statistics.quantiles(latencies, n=20)[18]*1000:.2f}ms")
            print(f"📉 P99 Latency: {statistics.quantiles(latencies, n=100)[98]*1000:.2f}ms")
        else:
            print(f"❌ All requests failed")
        
        return {
            "name": name,
            "successful": successful,
            "total": num_requests,
            "elapsed": elapsed,
            "rps": successful/elapsed if successful > 0 else 0,
            "avg_latency_ms": statistics.mean(latencies)*1000 if latencies else 0,
            "p95_latency_ms": statistics.quantiles(latencies, n=20)[18]*1000 if latencies and len(latencies) > 20 else 0,
            "p99_latency_ms": statistics.quantiles(latencies, n=100)[98]*1000 if latencies and len(latencies) > 100 else 0
        }

async def main():
    """Run benchmarks for both stacks."""
    print("🚀 URL Shortener Performance Benchmark")
    print("Testing scalability improvements from DB uniqueness check removal")
    
    # Test Python stack (direct container access)
    python_results = await benchmark_stack(
        "Python (Direct)", 
        "http://localhost:8000",  # This will be updated based on stack
        200
    )
    
    # Test Rust stack (if available)
    try:
        rust_results = await benchmark_stack(
            "Rust (Direct)", 
            "http://localhost:8000",  # This will be updated based on stack
            200
        )
    except Exception as e:
        print(f"Rust benchmark failed: {e}")
        rust_results = None
    
    # Summary
    print(f"\n📋 Benchmark Summary")
    print("=" * 50)
    
    if python_results:
        print(f"Python Stack:")
        print(f"  RPS: {python_results['rps']:.2f}")
        print(f"  Avg Latency: {python_results['avg_latency_ms']:.2f}ms")
        print(f"  Success Rate: {python_results['successful']/python_results['total']*100:.1f}%")
    
    if rust_results:
        print(f"Rust Stack:")
        print(f"  RPS: {rust_results['rps']:.2f}")
        print(f"  Avg Latency: {rust_results['avg_latency_ms']:.2f}ms")
        print(f"  Success Rate: {rust_results['successful']/rust_results['total']*100:.1f}%")
    
    if python_results and rust_results:
        print(f"\n🔄 Comparison:")
        rps_improvement = rust_results['rps'] / python_results['rps'] if python_results['rps'] > 0 else 0
        latency_improvement = python_results['avg_latency_ms'] / rust_results['avg_latency_ms'] if rust_results['avg_latency_ms'] > 0 else 0
        
        print(f"  RPS Improvement: {rps_improvement:.2f}x")
        print(f"  Latency Improvement: {latency_improvement:.2f}x")

if __name__ == "__main__":
    asyncio.run(main())
