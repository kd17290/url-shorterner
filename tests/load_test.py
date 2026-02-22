#!/usr/bin/env python3
"""
Advanced load testing script for Keygen Service using Locust.

Simulates realistic traffic patterns including:
- Warmup phase
- Burst testing
- Sustained load
- Stress testing
- Performance metrics collection
"""

import asyncio
import aiohttp
import time
import json
import statistics
import sys
import os
import random
from typing import List, Dict, Any
from dataclasses import dataclass
from datetime import datetime
import logging
from concurrent.futures import ThreadPoolExecutor
import threading

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class LoadTestPhase:
    name: str
    duration_seconds: int
    target_rps: int
    range_size: int
    description: str

@dataclass
class LoadTestMetrics:
    phase: str
    rps: float
    avg_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    error_rate: float
    total_requests: int
    successful_requests: int
    duration: float

class KeygenLoadTester:
    def __init__(self, base_url: str = "http://localhost:8001"):
        self.base_url = base_url
        self.session = None
        self.metrics: List[LoadTestMetrics] = []
        self.stop_event = threading.Event()
        
        # Load test phases
        self.phases = [
            LoadTestPhase("warmup", 30, 10, 100, "Gradual warmup to prepare service"),
            LoadTestPhase("baseline", 60, 50, 100, "Baseline performance measurement"),
            LoadTestPhase("moderate_load", 120, 200, 100, "Moderate sustained load"),
            LoadTestPhase("high_load", 180, 500, 100, "High load testing"),
            LoadTestPhase("burst_test", 60, 1000, 50, "Short burst testing"),
            LoadTestPhase("stress_test", 120, 1500, 50, "Stress testing near limits"),
            LoadTestPhase("recovery", 60, 100, 100, "Recovery testing after stress"),
        ]

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            connector=aiohttp.TCPConnector(limit=1000, limit_per_host=1000)
        )
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def run_load_test(self) -> Dict[str, Any]:
        """Run complete load test suite."""
        logger.info("Starting comprehensive load test suite...")
        logger.info(f"Target service: {self.base_url}")
        
        # Health check before starting
        if not await self.health_check():
            logger.error("Service health check failed!")
            return {"error": "Service not healthy"}
        
        all_phase_metrics = []
        
        for phase in self.phases:
            logger.info(f"\n{'='*60}")
            logger.info(f"PHASE: {phase.name.upper()}")
            logger.info(f"Duration: {phase.duration_seconds}s")
            logger.info(f"Target RPS: {phase.target_rps}")
            logger.info(f"Range Size: {phase.range_size}")
            logger.info(f"Description: {phase.description}")
            logger.info(f"{'='*60}")
            
            metrics = await self.run_phase(phase)
            all_phase_metrics.append(metrics)
            
            # Brief pause between phases
            await asyncio.sleep(5)
        
        # Generate comprehensive report
        return self.generate_load_test_report(all_phase_metrics)

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

    async def run_phase(self, phase: LoadTestPhase) -> LoadTestMetrics:
        """Run a single load test phase."""
        start_time = time.time()
        
        # Calculate request timing
        interval = 1.0 / phase.target_rps
        requests_per_batch = max(1, int(phase.target_rps * 0.1))  # 10% of RPS per batch
        
        latencies = []
        errors = []
        total_requests = 0
        successful_requests = 0
        
        # Request generator
        async def request_generator():
            nonlocal total_requests, successful_requests, latencies, errors
            
            while not self.stop_event.is_set() and (time.time() - start_time) < phase.duration_seconds:
                batch_start = time.time()
                
                # Create batch of requests
                batch_tasks = []
                for _ in range(requests_per_batch):
                    task = self.make_allocation_request(phase.range_size)
                    batch_tasks.append(task)
                
                # Execute batch
                batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
                
                # Process results
                for result in batch_results:
                    total_requests += 1
                    if isinstance(result, tuple):  # Success
                        latency, _ = result
                        latencies.append(latency)
                        successful_requests += 1
                    else:  # Error
                        errors.append(str(result))
                
                # Rate limiting
                batch_duration = time.time() - batch_start
                expected_batch_duration = requests_per_batch * interval
                if batch_duration < expected_batch_duration:
                    await asyncio.sleep(expected_batch_duration - batch_duration)
                
                # Stop if phase duration exceeded
                if (time.time() - start_time) >= phase.duration_seconds:
                    break
        
        # Run the phase
        await request_generator()
        
        actual_duration = time.time() - start_time
        
        # Calculate metrics
        if latencies:
            latencies.sort()
            rps = total_requests / actual_duration
            avg_latency = statistics.mean(latencies)
            p95_latency = latencies[int(0.95 * len(latencies))]
            p99_latency = latencies[int(0.99 * len(latencies))]
        else:
            rps = 0
            avg_latency = p95_latency = p99_latency = 0
        
        error_rate = len(errors) / total_requests if total_requests > 0 else 0
        
        metrics = LoadTestMetrics(
            phase=phase.name,
            rps=rps,
            avg_latency_ms=avg_latency,
            p95_latency_ms=p95_latency,
            p99_latency_ms=p99_latency,
            error_rate=error_rate,
            total_requests=total_requests,
            successful_requests=successful_requests,
            duration=actual_duration
        )
        
        # Log phase results
        logger.info(f"Phase {phase.name} completed:")
        logger.info(f"  Actual RPS: {rps:.1f} (target: {phase.target_rps})")
        logger.info(f"  Total Requests: {total_requests}")
        logger.info(f"  Success Rate: {(1-error_rate)*100:.1f}%")
        logger.info(f"  Avg Latency: {avg_latency:.2f}ms")
        logger.info(f"  P95 Latency: {p95_latency:.2f}ms")
        logger.info(f"  P99 Latency: {p99_latency:.2f}ms")
        
        self.metrics.append(metrics)
        return metrics

    async def make_allocation_request(self, range_size: int) -> tuple[float, Dict[str, Any]]:
        """Make a single allocation request and return latency and response."""
        request_start = time.time()
        
        try:
            async with self.session.post(
                f"{self.base_url}/allocate",
                json={"range_size": range_size},
                headers={"Content-Type": "application/json"}
            ) as response:
                if response.status == 200:
                    allocation = await response.json()
                    latency = (time.time() - request_start) * 1000  # Convert to ms
                    return latency, allocation
                else:
                    error_text = await response.text()
                    raise Exception(f"HTTP {response.status}: {error_text}")
                    
        except Exception as e:
            raise Exception(f"Request failed: {str(e)}")

    def generate_load_test_report(self, phase_metrics: List[LoadTestMetrics]) -> Dict[str, Any]:
        """Generate comprehensive load test report."""
        
        # Calculate overall statistics
        total_requests = sum(m.total_requests for m in phase_metrics)
        total_successful = sum(m.successful_requests for m in phase_metrics)
        total_duration = sum(m.duration for m in phase_metrics)
        overall_rps = total_requests / total_duration if total_duration > 0 else 0
        overall_success_rate = total_successful / total_requests if total_requests > 0 else 0
        
        # Find best and worst performance
        best_rps = max(m.rps for m in phase_metrics)
        worst_latency = max(m.avg_latency_ms for m in phase_metrics)
        best_latency = min(m.avg_latency_ms for m in phase_metrics)
        
        report = {
            "summary": {
                "total_duration": total_duration,
                "total_requests": total_requests,
                "successful_requests": total_successful,
                "overall_rps": overall_rps,
                "overall_success_rate": overall_success_rate,
                "best_rps_achieved": best_rps,
                "best_latency_ms": best_latency,
                "worst_latency_ms": worst_latency
            },
            "phases": [
                {
                    "name": m.phase,
                    "duration": m.duration,
                    "target_rps": next(p.target_rps for p in self.phases if p.name == m.phase),
                    "actual_rps": m.rps,
                    "avg_latency_ms": m.avg_latency_ms,
                    "p95_latency_ms": m.p95_latency_ms,
                    "p99_latency_ms": m.p99_latency_ms,
                    "error_rate": m.error_rate,
                    "total_requests": m.total_requests,
                    "successful_requests": m.successful_requests,
                    "success_rate": m.successful_requests / m.total_requests if m.total_requests > 0 else 0
                }
                for m in phase_metrics
            ],
            "performance_analysis": {
                "rps_trend": [m.rps for m in phase_metrics],
                "latency_trend": [m.avg_latency_ms for m in phase_metrics],
                "error_rate_trend": [m.error_rate for m in phase_metrics],
                "throughput_stability": statistics.stdev([m.rps for m in phase_metrics]) if len(phase_metrics) > 1 else 0
            },
            "recommendations": self.generate_recommendations(phase_metrics),
            "timestamp": datetime.now().isoformat()
        }
        
        # Print comprehensive summary
        self.print_load_test_summary(report)
        
        return report

    def generate_recommendations(self, phase_metrics: List[LoadTestMetrics]) -> List[str]:
        """Generate performance recommendations based on test results."""
        recommendations = []
        
        # Analyze RPS performance
        max_rps = max(m.rps for m in phase_metrics)
        high_rps_phases = [m for m in phase_metrics if m.rps > 1000]
        
        if max_rps < 500:
            recommendations.append("Consider optimizing service for higher throughput - current max RPS is low")
        
        if high_rps_phases:
            avg_high_rps_latency = statistics.mean([m.avg_latency_ms for m in high_rps_phases])
            if avg_high_rps_latency > 10:
                recommendations.append("High latency detected under load - consider scaling Redis or optimizing database operations")
        
        # Analyze latency
        high_latency_phases = [m for m in phase_metrics if m.avg_latency_ms > 5]
        if high_latency_phases:
            recommendations.append("Latency exceeds 5ms under load - investigate bottlenecks in allocation path")
        
        # Analyze error rates
        high_error_phases = [m for m in phase_metrics if m.error_rate > 0.01]
        if high_error_phases:
            recommendations.append("Error rate exceeds 1% under load - improve error handling and resource management")
        
        # Analyze stability
        if len(phase_metrics) > 1:
            rps_std = statistics.stdev([m.rps for m in phase_metrics])
            if rps_std > 100:
                recommendations.append("RPS variability is high - improve service stability and resource management")
        
        # Recovery analysis
        recovery_phase = next((m for m in phase_metrics if m.phase == "recovery"), None)
        if recovery_phase and recovery_phase.avg_latency_ms > 2:
            recommendations.append("Service recovery is slow - investigate cleanup and reset procedures")
        
        if not recommendations:
            recommendations.append("Performance is excellent - service handles load well with low latency and high throughput")
        
        return recommendations

    def print_load_test_summary(self, report: Dict[str, Any]):
        """Print comprehensive load test summary."""
        logger.info(f"\n{'='*80}")
        logger.info(f"COMPREHENSIVE LOAD TEST REPORT")
        logger.info(f"{'='*80}")
        
        # Summary
        summary = report["summary"]
        logger.info(f"Total Duration: {summary['total_duration']:.1f}s")
        logger.info(f"Total Requests: {summary['total_requests']:,}")
        logger.info(f"Successful Requests: {summary['successful_requests']:,}")
        logger.info(f"Overall RPS: {summary['overall_rps']:.1f}")
        logger.info(f"Success Rate: {summary['overall_success_rate']*100:.1f}%")
        logger.info(f"Best RPS Achieved: {summary['best_rps_achieved']:.1f}")
        logger.info(f"Best Latency: {summary['best_latency_ms']:.2f}ms")
        logger.info(f"Worst Latency: {summary['worst_latency_ms']:.2f}ms")
        
        # Phase details
        logger.info(f"\n{'='*80}")
        logger.info(f"PHASE-BY-PHASE RESULTS")
        logger.info(f"{'='*80}")
        
        for phase in report["phases"]:
            logger.info(f"\n{phase['name'].upper()}:")
            logger.info(f"  Duration: {phase['duration']:.1f}s")
            logger.info(f"  Target RPS: {phase['target_rps']}")
            logger.info(f"  Actual RPS: {phase['actual_rps']:.1f}")
            logger.info(f"  Success Rate: {phase['success_rate']*100:.1f}%")
            logger.info(f"  Avg Latency: {phase['avg_latency_ms']:.2f}ms")
            logger.info(f"  P95 Latency: {phase['p95_latency_ms']:.2f}ms")
            logger.info(f"  P99 Latency: {phase['p99_latency_ms']:.2f}ms")
            logger.info(f"  Error Rate: {phase['error_rate']*100:.2f}%")
        
        # Recommendations
        logger.info(f"\n{'='*80}")
        logger.info(f"PERFORMANCE RECOMMENDATIONS")
        logger.info(f"{'='*80}")
        
        for i, rec in enumerate(report["recommendations"], 1):
            logger.info(f"{i}. {rec}")

async def main():
    """Main load test runner."""
    base_url = os.getenv("TARGET_SERVICE", "http://localhost:8001")
    
    async with KeygenLoadTester(base_url) as tester:
        report = await tester.run_load_test()
        
        # Save report to file
        os.makedirs("/app/results", exist_ok=True)
        with open("/app/results/load_test_report.json", "w") as f:
            json.dump(report, f, indent=2)
        
        logger.info(f"\nDetailed report saved to: /app/results/load_test_report.json")
        
        # Determine success based on performance criteria
        success_criteria = (
            report["summary"]["overall_success_rate"] >= 0.95 and  # 95% success rate
            report["summary"]["best_rps_achieved"] >= 500 and      # 500+ RPS
            report["summary"]["worst_latency_ms"] <= 50            # < 50ms worst latency
        )
        
        logger.info(f"\nLoad test {'PASSED' if success_criteria else 'FAILED'}")
        sys.exit(0 if success_criteria else 1)

if __name__ == "__main__":
    asyncio.run(main())
