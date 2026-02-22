#!/usr/bin/env python3
"""
Quick performance test for Keygen Service.
"""

import asyncio
import aiohttp
import time
import statistics
import json

async def quick_benchmark():
    """Run quick performance benchmark."""
    base_url = "http://localhost:8010"
    
    async with aiohttp.ClientSession() as session:
        # Health check
        async with session.get(f"{base_url}/health") as response:
            health = await response.json()
            print(f"Service health: {health}")
        
        # Test 1: Single request performance
        print("\n=== Single Request Benchmark ===")
        latencies = []
        test_requests = 100
        
        for i in range(test_requests):
            start_time = time.time()
            try:
                async with session.post(f"{base_url}/allocate", 
                                       json={"size": 100}) as response:
                    if response.status == 200:
                        allocation = await response.json()
                        latency = (time.time() - start_time) * 1000
                        latencies.append(latency)
                        
                        if i == 0:
                            print(f"Sample allocation: {allocation}")
                    else:
                        error_text = await response.text()
                        print(f"Error: {response.status} - {error_text}")
                        if response.status == 503:
                            print("Service unavailable, skipping remaining tests")
                            break
            except Exception as e:
                print(f"Request failed: {e}")
                break
        
        if latencies:
            latencies.sort()
            avg_latency = statistics.mean(latencies)
            p95_latency = latencies[int(0.95 * len(latencies))]
            p99_latency = latencies[int(0.99 * len(latencies))]
            min_latency = min(latencies)
            max_latency = max(latencies)
            
            print(f"Requests: {len(latencies)}")
            print(f"Avg Latency: {avg_latency:.2f}ms")
            print(f"P95 Latency: {p95_latency:.2f}ms")
            print(f"P99 Latency: {p99_latency:.2f}ms")
            print(f"Min Latency: {min_latency:.2f}ms")
            print(f"Max Latency: {max_latency:.2f}ms")
            print(f"RPS: {len(latencies) / sum(lat/1000 for lat in latencies):.1f}")
        else:
            print("No successful requests completed")
            return
        
        # Test 2: Concurrent requests
        print("\n=== Concurrent Requests Benchmark ===")
        concurrency_levels = [5, 10, 25, 50]
        
        for concurrency in concurrency_levels:
            print(f"\nConcurrency: {concurrency}")
            
            async def make_request():
                start_time = time.time()
                try:
                    async with session.post(f"{base_url}/allocate", 
                                           json={"size": 50}) as response:
                        if response.status == 200:
                            await response.json()
                            return (time.time() - start_time) * 1000
                        else:
                            return None
                except:
                    return None
            
            # Run concurrent requests
            start_time = time.time()
            tasks = [make_request() for _ in range(200)]
            results = await asyncio.gather(*tasks)
            duration = time.time() - start_time
            
            # Process results
            latencies = [r for r in results if r is not None]
            success_rate = len(latencies) / len(results)
            
            if latencies:
                latencies.sort()
                avg_latency = statistics.mean(latencies)
                p95_latency = latencies[int(0.95 * len(latencies))]
                rps = len(latencies) / duration
                
                print(f"  Success Rate: {success_rate:.2%}")
                print(f"  RPS: {rps:.1f}")
                print(f"  Avg Latency: {avg_latency:.2f}ms")
                print(f"  P95 Latency: {p95_latency:.2f}ms")
            else:
                print(f"  No successful requests")
                break
        
        # Test 3: Sustained load
        print("\n=== Sustained Load Benchmark ===")
        duration_seconds = 30
        target_rps = 100
        
        start_time = time.time()
        end_time = start_time + duration_seconds
        
        latencies = []
        total_requests = 0
        
        while time.time() < end_time:
            batch_start = time.time()
            batch_size = max(1, int(target_rps * 0.1))
            
            # Create batch
            tasks = []
            for _ in range(batch_size):
                task = session.post(f"{base_url}/allocate", json={"size": 10})
                tasks.append(task)
            
            # Execute batch
            for task in tasks:
                request_start = time.time()
                try:
                    async with task as response:
                        if response.status == 200:
                            await response.json()
                            latencies.append((time.time() - request_start) * 1000)
                        total_requests += 1
                except:
                    pass
            
            # Rate limiting
            batch_duration = time.time() - batch_start
            expected_batch_duration = batch_size / target_rps
            if batch_duration < expected_batch_duration:
                await asyncio.sleep(expected_batch_duration - batch_duration)
        
        actual_duration = time.time() - start_time
        
        if latencies:
            latencies.sort()
            avg_latency = statistics.mean(latencies)
            p95_latency = latencies[int(0.95 * len(latencies))]
            p99_latency = latencies[int(0.99 * len(latencies))]
            rps = total_requests / actual_duration
            
            print(f"Duration: {actual_duration:.1f}s")
            print(f"Total Requests: {total_requests}")
            print(f"RPS: {rps:.1f}")
            print(f"Avg Latency: {avg_latency:.2f}ms")
            print(f"P95 Latency: {p95_latency:.2f}ms")
            print(f"P99 Latency: {p99_latency:.2f}ms")

if __name__ == "__main__":
    asyncio.run(quick_benchmark())
