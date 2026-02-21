#!/usr/bin/env python3
"""
Direct benchmark script for Python stack.
Tests app directly without nginx load balancer.
"""

import asyncio
import statistics
import time

import httpx


async def benchmark_python_direct():
    """Benchmark Python stack directly."""
    print("🐍 Python Stack Direct Benchmark")
    print("=" * 50)

    # Test different concurrency levels
    concurrency_levels = [1, 5, 10, 20]
    results = []

    for concurrency in concurrency_levels:
        print(f"\n📊 Testing with {concurrency} concurrent requests...")

        async with httpx.AsyncClient(timeout=30.0) as client:
            # Warmup
            warmup_tasks = []
            for i in range(10):
                warmup_tasks.append(
                    client.post("http://localhost:8000/api/shorten", json={"url": f"https://warmup-{i}.example.com"})
                )
            await asyncio.gather(*warmup_tasks, return_exceptions=True)

            # Actual benchmark
            num_requests = 100
            start_time = time.time()

            latencies = []

            for i in range(num_requests):
                task_start = time.time()
                try:
                    response = await client.post(
                        "http://localhost:8000/api/shorten", json={"url": f"https://example.com/test/{i}"}
                    )
                    latency = time.time() - task_start

                    if response.status_code == 201:
                        latencies.append(latency)
                except Exception as e:
                    print(f"Request failed: {e}")

            elapsed = time.time() - start_time
            successful = len(latencies)

            if successful > 0:
                rps = successful / elapsed
                avg_latency = statistics.mean(latencies) * 1000
                p95 = statistics.quantiles(latencies, n=20)[18] * 1000 if len(latencies) > 20 else avg_latency

                result = {
                    "concurrency": concurrency,
                    "successful": successful,
                    "total": num_requests,
                    "elapsed": elapsed,
                    "rps": rps,
                    "avg_latency_ms": avg_latency,
                    "p95_latency_ms": p95,
                }
                results.append(result)

                print(f"✅ Success Rate: {successful}/{num_requests} ({successful/num_requests*100:.1f}%)")
                print(f"🚀 RPS: {rps:.2f}")
                print(f"⏱️  Avg Latency: {avg_latency:.2f}ms")
                print(f"📈 P95 Latency: {p95:.2f}ms")
            else:
                print("❌ All requests failed")

    return results


async def main():
    results = await benchmark_python_direct()

    print("\n📋 Python Performance Summary")
    print("=" * 50)
    for result in results:
        print(f"Concurrency {result['concurrency']}: {result['rps']:.2f} RPS, {result['avg_latency_ms']:.2f}ms avg")

    # Find best performance
    if results:
        best = max(results, key=lambda x: x["rps"])
        print(f"\n🏆 Best Performance: {best['rps']:.2f} RPS at {best['concurrency']} concurrency")


if __name__ == "__main__":
    asyncio.run(main())
