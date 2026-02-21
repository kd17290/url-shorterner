#!/usr/bin/env python3
"""
Simple performance test for URL creation.
"""

import asyncio
import statistics
import time

import httpx


async def test_python_performance():
    """Test Python stack performance."""
    print("🐍 Python Stack Performance Test")

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Health check
        health = await client.get("http://localhost:8080/health")
        print(f"Health: {health.json()}")

        # Benchmark URL creation
        num_requests = 100
        print(f"Creating {num_requests} URLs...")

        start_time = time.time()
        latencies = []
        successful = 0

        for i in range(num_requests):
            task_start = time.time()
            try:
                response = await client.post(
                    "http://localhost:8080/api/shorten", json={"url": f"https://example.com/test/{i}"}
                )
                latency = time.time() - task_start

                if response.status_code == 201:
                    successful += 1
                    latencies.append(latency)
                else:
                    print(f"Request {i} failed: {response.status_code}")
            except Exception as e:
                print(f"Request {i} exception: {e}")

        elapsed = time.time() - start_time

        print("\n📊 Results:")
        print(f"✅ Success Rate: {successful}/{num_requests} ({successful/num_requests*100:.1f}%)")
        print(f"⏱️  Total Time: {elapsed:.2f}s")
        print(f"🚀 RPS: {successful/elapsed:.2f}")

        if latencies:
            print(f"📈 Avg Latency: {statistics.mean(latencies)*1000:.2f}ms")
            print(f"📉 Min Latency: {min(latencies)*1000:.2f}ms")
            print(f"📈 Max Latency: {max(latencies)*1000:.2f}ms")

            if len(latencies) > 10:
                p95 = statistics.quantiles(latencies, n=20)[18]
                print(f"📊 P95 Latency: {p95*1000:.2f}ms")


if __name__ == "__main__":
    asyncio.run(test_python_performance())
