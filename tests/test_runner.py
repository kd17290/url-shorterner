#!/usr/bin/env python3
"""
Docker-based test runner for Keygen Service regression and performance testing.

This script orchestrates:
1. Environment setup
2. Service startup
3. Regression testing
4. Load testing
5. Benchmark reporting
6. Cleanup
"""

import asyncio
import subprocess
import time
import json
import sys
import os
import signal
from typing import Dict, Any, List
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class DockerTestRunner:
    def __init__(self):
        self.compose_file = "docker-compose.test.yml"
        self.test_results = {}
        self.start_time = None
        
    async def run_full_test_suite(self) -> Dict[str, Any]:
        """Run the complete test suite."""
        self.start_time = time.time()
        
        logger.info("🚀 Starting Docker-based Keygen Service Test Suite")
        logger.info("=" * 60)
        
        try:
            # Step 1: Setup environment
            await self.setup_environment()
            
            # Step 2: Start services
            await self.start_services()
            
            # Step 3: Wait for services to be healthy
            await self.wait_for_services()
            
            # Step 4: Run regression tests
            regression_results = await self.run_regression_tests()
            
            # Step 5: Run load tests
            load_test_results = await self.run_load_tests()
            
            # Step 6: Generate comprehensive report
            final_report = await self.generate_final_report(regression_results, load_test_results)
            
            return final_report
            
        except Exception as e:
            logger.error(f"Test suite failed: {e}")
            return {"error": str(e)}
            
        finally:
            # Step 7: Cleanup
            await self.cleanup()
    
    async def setup_environment(self):
        """Setup test environment."""
        logger.info("📋 Setting up test environment...")
        
        # Create necessary directories
        os.makedirs("test_results", exist_ok=True)
        os.makedirs("load_test_results", exist_ok=True)
        os.makedirs("benchmark_results", exist_ok=True)
        
        # Check Docker availability
        try:
            result = subprocess.run(["docker", "--version"], capture_output=True, text=True)
            logger.info(f"Docker version: {result.stdout.strip()}")
        except FileNotFoundError:
            raise Exception("Docker is not installed or not in PATH")
        
        # Check docker-compose
        try:
            result = subprocess.run(["docker-compose", "--version"], capture_output=True, text=True)
            logger.info(f"Docker Compose version: {result.stdout.strip()}")
        except FileNotFoundError:
            try:
                result = subprocess.run(["docker", "compose", "--version"], capture_output=True, text=True)
                logger.info(f"Docker Compose version: {result.stdout.strip()}")
            except FileNotFoundError:
                raise Exception("Docker Compose is not installed or not in PATH")
        
        logger.info("✅ Environment setup complete")
    
    async def start_services(self):
        """Start all test services."""
        logger.info("🐳 Starting test services...")
        
        # Stop any existing containers
        await self.run_command("docker-compose", ["-f", self.compose_file, "down", "-v"])
        
        # Build and start services
        await self.run_command("docker-compose", ["-f", self.compose_file, "up", "-d", "--build"])
        
        logger.info("✅ Services started")
    
    async def wait_for_services(self):
        """Wait for all services to be healthy."""
        logger.info("⏳ Waiting for services to be healthy...")
        
        services = ["postgres-test", "redis-test", "keygen-test"]
        max_wait_time = 300  # 5 minutes
        wait_interval = 5
        
        for service in services:
            waited_time = 0
            logger.info(f"Waiting for {service}...")
            
            while waited_time < max_wait_time:
                try:
                    # Check service health
                    result = await self.run_command(
                        "docker-compose", 
                        ["-f", self.compose_file, "ps", service, "-q"],
                        capture_output=True
                    )
                    
                    if result.stdout.strip():
                        container_id = result.stdout.strip()
                        
                        # Check health status
                        health_result = await self.run_command(
                            "docker", 
                            ["inspect", container_id, "--format", "{{.State.Health.Status}}"],
                            capture_output=True
                        )
                        
                        health_status = health_result.stdout.strip()
                        
                        if health_status == "healthy" or service == "redis-sentinel-test":
                            logger.info(f"✅ {service} is healthy")
                            break
                        elif health_status == "unhealthy":
                            logger.error(f"❌ {service} is unhealthy")
                            raise Exception(f"Service {service} failed health check")
                        
                except Exception as e:
                    logger.debug(f"Health check for {service}: {e}")
                
                await asyncio.sleep(wait_interval)
                waited_time += wait_interval
            
            if waited_time >= max_wait_time:
                raise Exception(f"Timeout waiting for {service} to become healthy")
        
        logger.info("✅ All services are healthy")
    
    async def run_regression_tests(self) -> Dict[str, Any]:
        """Run regression tests."""
        logger.info("🧪 Running regression tests...")
        
        try:
            # Run regression tests in benchmark container
            result = await self.run_command(
                "docker-compose", 
                ["-f", self.compose_file, "exec", "benchmark-runner", 
                 "python", "tests/regression_test.py"],
                capture_output=True
            )
            
            if result.returncode == 0:
                logger.info("✅ Regression tests passed")
                
                # Parse results
                try:
                    with open("test_results/regression_report.json", "r") as f:
                        regression_results = json.load(f)
                except FileNotFoundError:
                    regression_results = {"summary": {"success_rate": 0}, "error": "Results file not found"}
                
                return regression_results
            else:
                logger.error(f"❌ Regression tests failed: {result.stderr}")
                return {"error": result.stderr, "summary": {"success_rate": 0}}
                
        except Exception as e:
            logger.error(f"❌ Regression test execution failed: {e}")
            return {"error": str(e), "summary": {"success_rate": 0}}
    
    async def run_load_tests(self) -> Dict[str, Any]:
        """Run load tests."""
        logger.info("⚡ Running load tests...")
        
        try:
            # Run load tests in benchmark container
            result = await self.run_command(
                "docker-compose", 
                ["-f", self.compose_file, "exec", "benchmark-runner", 
                 "python", "tests/load_test.py"],
                capture_output=True,
                timeout=900  # 15 minutes timeout
            )
            
            if result.returncode == 0:
                logger.info("✅ Load tests completed")
                
                # Parse results
                try:
                    with open("test_results/load_test_report.json", "r") as f:
                        load_test_results = json.load(f)
                except FileNotFoundError:
                    load_test_results = {"summary": {"overall_success_rate": 0}, "error": "Results file not found"}
                
                return load_test_results
            else:
                logger.error(f"❌ Load tests failed: {result.stderr}")
                return {"error": result.stderr, "summary": {"overall_success_rate": 0}}
                
        except asyncio.TimeoutError:
            logger.error("❌ Load tests timed out")
            return {"error": "Load tests timed out", "summary": {"overall_success_rate": 0}}
        except Exception as e:
            logger.error(f"❌ Load test execution failed: {e}")
            return {"error": str(e), "summary": {"overall_success_rate": 0}}
    
    async def generate_final_report(self, regression_results: Dict[str, Any], load_test_results: Dict[str, Any]) -> Dict[str, Any]:
        """Generate comprehensive final report."""
        logger.info("📊 Generating final report...")
        
        total_duration = time.time() - self.start_time
        
        # Extract key metrics
        regression_success_rate = regression_results.get("summary", {}).get("success_rate", 0)
        load_test_success_rate = load_test_results.get("summary", {}).get("overall_success_rate", 0)
        best_rps = load_test_results.get("summary", {}).get("best_rps_achieved", 0)
        worst_latency = load_test_results.get("summary", {}).get("worst_latency_ms", 0)
        
        # Determine overall success
        overall_success = (
            regression_success_rate >= 0.95 and  # 95% regression test success
            load_test_success_rate >= 0.95 and   # 95% load test success
            best_rps >= 500 and                  # 500+ RPS achieved
            worst_latency <= 50                  # < 50ms worst latency
        )
        
        final_report = {
            "test_suite_summary": {
                "total_duration": total_duration,
                "overall_success": overall_success,
                "timestamp": datetime.now().isoformat()
            },
            "regression_tests": regression_results,
            "load_tests": load_test_results,
            "key_metrics": {
                "regression_success_rate": regression_success_rate,
                "load_test_success_rate": load_test_success_rate,
                "best_rps_achieved": best_rps,
                "worst_latency_ms": worst_latency
            },
            "recommendations": self.generate_overall_recommendations(regression_results, load_test_results)
        }
        
        # Save final report
        with open("test_results/final_report.json", "w") as f:
            json.dump(final_report, f, indent=2)
        
        # Print summary
        self.print_final_summary(final_report)
        
        return final_report
    
    def generate_overall_recommendations(self, regression_results: Dict[str, Any], load_test_results: Dict[str, Any]) -> List[str]:
        """Generate overall recommendations."""
        recommendations = []
        
        # Regression test recommendations
        regression_success_rate = regression_results.get("summary", {}).get("success_rate", 0)
        if regression_success_rate < 0.95:
            recommendations.append("Regression tests need attention - fix failing tests before production deployment")
        
        # Load test recommendations
        best_rps = load_test_results.get("summary", {}).get("best_rps_achieved", 0)
        if best_rps < 500:
            recommendations.append("Performance below target - optimize for higher throughput")
        
        worst_latency = load_test_results.get("summary", {}).get("worst_latency_ms", 0)
        if worst_latency > 50:
            recommendations.append("Latency too high under load - investigate bottlenecks and optimize critical path")
        
        # Load test specific recommendations
        load_recommendations = load_test_results.get("recommendations", [])
        recommendations.extend(load_recommendations)
        
        if not recommendations:
            recommendations.append("Excellent performance! Service is ready for production deployment")
        
        return recommendations
    
    def print_final_summary(self, report: Dict[str, Any]):
        """Print comprehensive final summary."""
        logger.info("\n" + "=" * 80)
        logger.info("🎯 FINAL TEST SUITE RESULTS")
        logger.info("=" * 80)
        
        summary = report["test_suite_summary"]
        metrics = report["key_metrics"]
        
        logger.info(f"Total Duration: {summary['total_duration']:.1f}s")
        logger.info(f"Overall Success: {'✅ PASS' if summary['overall_success'] else '❌ FAIL'}")
        logger.info(f"Regression Test Success Rate: {metrics['regression_success_rate']*100:.1f}%")
        logger.info(f"Load Test Success Rate: {metrics['load_test_success_rate']*100:.1f}%")
        logger.info(f"Best RPS Achieved: {metrics['best_rps_achieved']:.1f}")
        logger.info(f"Worst Latency: {metrics['worst_latency_ms']:.2f}ms")
        
        logger.info("\n" + "=" * 80)
        logger.info("📋 RECOMMENDATIONS")
        logger.info("=" * 80)
        
        for i, rec in enumerate(report["recommendations"], 1):
            logger.info(f"{i}. {rec}")
        
        logger.info("\n" + "=" * 80)
        logger.info("📁 REPORT FILES")
        logger.info("=" * 80)
        logger.info("Detailed reports saved to:")
        logger.info("  - test_results/final_report.json")
        logger.info("  - test_results/regression_report.json")
        logger.info("  - test_results/load_test_report.json")
        
        logger.info("\n" + "=" * 80)
        if summary['overall_success']:
            logger.info("🎉 ALL TESTS PASSED - SERVICE READY FOR PRODUCTION!")
        else:
            logger.info("⚠️  SOME TESTS FAILED - REVIEW RECOMMENDATIONS")
        logger.info("=" * 80)
    
    async def cleanup(self):
        """Clean up test environment."""
        logger.info("🧹 Cleaning up test environment...")
        
        try:
            # Stop and remove containers
            await self.run_command("docker-compose", ["-f", self.compose_file, "down", "-v"])
            
            # Remove unused images
            await self.run_command("docker", ["image", "prune", "-f"])
            
            logger.info("✅ Cleanup complete")
            
        except Exception as e:
            logger.warning(f"Cleanup warning: {e}")
    
    async def run_command(self, cmd: str, args: List[str], capture_output: bool = False, timeout: int = None) -> subprocess.CompletedProcess:
        """Run a command with proper error handling."""
        try:
            if capture_output:
                result = await asyncio.create_subprocess_exec(
                    cmd, *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await asyncio.wait_for(result.communicate(), timeout=timeout)
                return subprocess.CompletedProcess(args, result.returncode, stdout, stderr)
            else:
                process = await asyncio.create_subprocess_exec(cmd, *args)
                return await asyncio.wait_for(process.wait(), timeout=timeout)
                
        except asyncio.TimeoutError:
            logger.error(f"Command timed out: {cmd} {' '.join(args)}")
            raise
        except Exception as e:
            logger.error(f"Command failed: {cmd} {' '.join(args)} - {e}")
            raise

async def main():
    """Main test runner."""
    runner = DockerTestRunner()
    
    # Setup signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        logger.info("Received interrupt signal, shutting down...")
        asyncio.create_task(runner.cleanup())
        sys.exit(1)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        report = await runner.run_full_test_suite()
        
        # Exit with appropriate code
        sys.exit(0 if report["test_suite_summary"]["overall_success"] else 1)
        
    except KeyboardInterrupt:
        logger.info("Test suite interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Test suite failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
