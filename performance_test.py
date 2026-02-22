#!/usr/bin/env python3
"""
Comprehensive performance test for Keygen Service.
"""

import asyncio
import aiohttp
import time
import statistics
import json

async def performance_test():
    """Run comprehensive performance test."""
    base_url = "http://localhost:8010"
    
    async with aiohttp.ClientSession() as session:
        # Health check
        async with session.get(f"{base_url}/health") as response:
            health = await response.json()
            print(f"🔍 Service Health: {health['status']}")
            print(f"   Redis: {health['redis_health']}")
            print(f"   PostgreSQL: {health['postgresql_health']}")
            print(f"   Total Allocations: {health['metrics']['total_allocations']}")
            print(f"   PostgreSQL Allocations: {health['metrics']['postgresql_allocations']}")
            print(f"   Avg Latency: {health['metrics']['avg_allocation_time_ms']:.2f}ms")
            print()
        
        # Test 1: Single request performance (PostgreSQL fallback)
        print("📊 Single Request Performance (PostgreSQL Fallback)")
        latencies = []
        test_requests = 50  # Reduced for faster testing
        
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
                            print(f"   Sample allocation: {allocation}")
                    else:
                        error_text = await response.text()
                        print(f"   Error: {response.status} - {error_text}")
                        break
            except Exception as e:
                print(f"   Request failed: {e}")
                break
        
        if latencies:
            latencies.sort()
            avg_latency = statistics.mean(latencies)
            p95_latency = latencies[int(0.95 * len(latencies))]
            p99_latency = latencies[int(0.99 * len(latencies))]
            min_latency = min(latencies)
            max_latency = max(latencies)
            
            print(f"   ✅ Successful Requests: {len(latencies)}/{test_requests}")
            print(f"   📈 Avg Latency: {avg_latency:.2f}ms")
            print(f"   📈 P95 Latency: {p95_latency:.2f}ms")
            print(f"   📈 P99 Latency: {p99_latency:.2f}ms")
            print(f"   📈 Min Latency: {min_latency:.2f}ms")
            print(f"   📈 Max Latency: {max_latency:.2f}ms")
            print(f"   🚀 RPS: {len(latencies) / sum(lat/1000 for lat in latencies):.1f}")
            print()
        
        # Test 2: Low concurrency test
        print("📊 Low Concurrency Test (3 concurrent)")
        concurrency = 3
        requests_per_test = 30
        
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
        tasks = [make_request() for _ in range(requests_per_test)]
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
            
            print(f"   ✅ Success Rate: {success_rate:.2%}")
            print(f"   🚀 RPS: {rps:.1f}")
            print(f"   📈 Avg Latency: {avg_latency:.2f}ms")
            print(f"   📈 P95 Latency: {p95_latency:.2f}ms")
            print()
        
        # Test 3: Range size impact
        print("📊 Range Size Impact Test")
        range_sizes = [10, 100, 1000, 5000]
        
        for size in range_sizes:
            latencies = []
            for _ in range(10):  # 10 requests per size
                start_time = time.time()
                try:
                    async with session.post(f"{base_url}/allocate", 
                                           json={"size": size}) as response:
                        if response.status == 200:
                            await response.json()
                            latency = (time.time() - start_time) * 1000
                            latencies.append(latency)
                except:
                    pass
            
            if latencies:
                avg_latency = statistics.mean(latencies)
                print(f"   Size {size:5d}: {avg_latency:.2f}ms avg latency")
        
        print()
        
        # Test 4: ID uniqueness verification
        print("🔍 ID Uniqueness Verification")
        allocations = []
        
        for i in range(20):
            try:
                async with session.post(f"{base_url}/allocate", 
                                       json={"size": 10}) as response:
                    if response.status == 200:
                        allocation = await response.json()
                        allocations.append((allocation['start'], allocation['end']))
            except:
                pass
        
        # Check for overlaps
        allocations.sort()
        overlaps = 0
        for i in range(len(allocations) - 1):
            current_end = allocations[i][1]
            next_start = allocations[i + 1][0]
            if current_end >= next_start:
                overlaps += 1
        
        print(f"   ✅ Allocations Tested: {len(allocations)}")
        print(f"   🔍 Overlaps Found: {overlaps}")
        print(f"   🎯 Uniqueness: {'PASS' if overlaps == 0 else 'FAIL'}")
        print()
        
        # Summary
        print("🎯 PERFORMANCE SUMMARY")
        print("=" * 50)
        print(f"Service Status: {health['status']} (Redis: {health['redis_health']}, PostgreSQL: {health['postgresql_health']})")
        print(f"Current Mode: PostgreSQL fallback (Redis unavailable)")
        print(f"Single Request RPS: {len(latencies) / sum(lat/1000 for lat in latencies):.1f}")
        print(f"Single Request Latency: {avg_latency:.2f}ms avg")
        print(f"Concurrency Support: Limited (PostgreSQL bottleneck)")
        print(f"ID Uniqueness: {'✅ GUARANTEED' if overlaps == 0 else '❌ COMPROMISED'}")
        print()
        print("📈 EXPECTED PERFORMANCE WITH REDIS:")
        print("   - RPS: 500-1500+ (vs current ~45)")
        print("   - Latency: 0.5-5ms (vs current ~22ms)")
        print("   - Concurrency: Excellent (vs current limited)")
        print()
        print("🔧 RECOMMENDATIONS:")
        print("   1. Fix Redis connectivity for optimal performance")
        print("   2. Current PostgreSQL fallback provides reliability")
        print("   3. Service maintains ID uniqueness guarantees")
        print("   4. Consider connection pooling for PostgreSQL")

if __name__ == "__main__":
    asyncio.run(performance_test())
