# Keygen Service Docker-Based Testing Framework

This comprehensive testing framework provides Docker-based regression testing, load testing, and benchmarking for the Keygen Service.

## 🎯 Overview

The testing framework includes:

- **Regression Testing**: Comprehensive functional tests with collision prevention validation
- **Load Testing**: Multi-phase load testing with realistic traffic patterns
- **Benchmarking**: Quick performance measurements and resource utilization
- **Docker Isolation**: Fully containerized test environment
- **Automated Reporting**: Detailed JSON reports with performance metrics
- **Health Monitoring**: Service health checks and resource utilization tracking

## 🏗️ Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Test Runner    │    │  Docker Compose │    │  Test Services  │
│                 │    │                 │    │                 │
│ • Orchestrates  │───▶│ • PostgreSQL     │───▶│ • Keygen Service │
│ • Executes Tests│    │ • Redis          │    │ • Load Generator │
│ • Reports       │    │ • Redis Sentinel │    │ • Benchmark     │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## 🚀 Quick Start

### Prerequisites

- Docker and Docker Compose installed
- At least 4GB RAM available
- Ports 5433, 6380, 26380, 8001 available

### Basic Usage

```bash
# Run complete test suite
./run_tests.sh

# Run specific test types
./run_tests.sh regression    # Regression tests only
./run_tests.sh load          # Load tests only
./run_tests.sh benchmark     # Quick benchmark only
./run_tests.sh cleanup       # Clean up environment
```

## 📋 Test Types

### 1. Regression Tests

**Purpose**: Validate functionality and prevent regressions

**Coverage**:
- Health check endpoint
- Basic ID allocation
- Range allocation validation
- Concurrent allocation testing
- Collision prevention
- Error handling
- Data consistency

**Success Criteria**:
- 95%+ test pass rate
- Zero ID collisions
- Proper error handling

### 2. Load Tests

**Purpose**: Performance testing under various load conditions

**Test Phases**:
1. **Warmup** (30s @ 10 RPS): Gradual service preparation
2. **Baseline** (60s @ 50 RPS): Baseline performance measurement
3. **Moderate Load** (120s @ 200 RPS): Moderate sustained load
4. **High Load** (180s @ 500 RPS): High load testing
5. **Burst Test** (60s @ 1000 RPS): Short burst testing
6. **Stress Test** (120s @ 1500 RPS): Stress testing near limits
7. **Recovery** (60s @ 100 RPS): Recovery testing after stress

**Success Criteria**:
- 95%+ success rate
- 500+ RPS achieved
- < 50ms worst latency

### 3. Quick Benchmark

**Purpose**: Fast performance measurements

**Tests**:
- Single request latency
- Concurrent request throughput
- Sustained load performance
- Resource utilization

**Performance Ratings**:
- **Excellent**: 1000+ RPS, < 1ms latency
- **Good**: 500+ RPS, < 2ms latency
- **Acceptable**: 200+ RPS, < 5ms latency
- **Needs Improvement**: Below thresholds

## 📊 Metrics and Reporting

### Key Metrics

- **RPS (Requests Per Second)**: Throughput measurement
- **Latency**: Average, P95, P99 response times
- **Error Rate**: Percentage of failed requests
- **Resource Usage**: CPU and memory utilization
- **Success Rate**: Percentage of successful operations

### Report Files

All tests generate detailed JSON reports:

```
test_results/
├── final_report.json          # Comprehensive test summary
├── regression_report.json      # Regression test details
├── load_test_report.json       # Load test results
└── quick_benchmark.json        # Quick benchmark results
```

### Report Structure

```json
{
  "test_suite_summary": {
    "total_duration": 1200.5,
    "overall_success": true,
    "timestamp": "2024-01-01T12:00:00Z"
  },
  "key_metrics": {
    "regression_success_rate": 0.98,
    "load_test_success_rate": 0.96,
    "best_rps_achieved": 1250.0,
    "worst_latency_ms": 45.2
  },
  "recommendations": [
    "Excellent performance! Service ready for production deployment"
  ]
}
```

## 🔧 Configuration

### Environment Variables

```bash
# Service URLs
TARGET_SERVICE=http://localhost:8001
REDIS_URL=redis://localhost:6380
POSTGRES_URL=postgresql+asyncpg://test_user:test_password@localhost:5433/url_shortener_test

# Test Configuration
CONCURRENT_REQUESTS=100
TEST_DURATION=300
RANGE_SIZE=100
```

### Docker Compose Configuration

The test environment includes:

- **PostgreSQL**: Test database with pre-configured schema
- **Redis**: In-memory cache with AOF persistence
- **Redis Sentinel**: High availability configuration
- **Keygen Service**: Test instance with debug logging
- **Benchmark Runner**: Test execution environment
- **Load Generator**: Stress testing capabilities

## 📈 Performance Benchmarks

### Expected Performance

| Metric | Target | Excellent | Good | Acceptable |
|--------|--------|----------|-------|-------------|
| **RPS** | 500+ | 1000+ | 500+ | 200+ |
| **P95 Latency** | < 10ms | < 1ms | < 2ms | < 5ms |
| **P99 Latency** | < 25ms | < 2ms | < 5ms | < 10ms |
| **Error Rate** | < 1% | < 0.1% | < 0.5% | < 1% |

### Scaling Characteristics

| Load Level | Expected RPS | Expected Latency | Behavior |
|------------|--------------|------------------|----------|
| **Low** (< 100 RPS) | 100+ | < 1ms | Optimal performance |
| **Medium** (100-500 RPS) | 500+ | < 2ms | Stable performance |
| **High** (500-1000 RPS) | 1000+ | < 5ms | Slight latency increase |
| **Stress** (> 1000 RPS) | 1500+ | < 10ms | Graceful degradation |

## 🛠️ Advanced Usage

### Custom Test Scenarios

```bash
# Run tests with custom configuration
CONCURRENT_REQUESTS=200 TEST_DURATION=600 ./run_tests.sh load

# Run tests with different service URL
TARGET_SERVICE=http://localhost:9000 ./run_tests.sh regression
```

### Manual Test Execution

```bash
# Start services manually
docker-compose -f docker-compose.test.yml up -d --build

# Run individual tests
docker-compose -f docker-compose.test.yml exec benchmark-runner python tests/regression_test.py
docker-compose -f docker-compose.test.yml exec benchmark-runner python tests/load_test.py
docker-compose -f docker-compose.test.yml exec benchmark-runner python tests/quick_benchmark.py

# View logs
docker-compose -f docker-compose.test.yml logs -f keygen-test
```

### Custom Test Development

Add new tests to the `tests/` directory:

```python
# tests/custom_test.py
async def test_custom_scenario():
    """Custom test scenario."""
    async with aiohttp.ClientSession() as session:
        # Test implementation
        pass
```

## 🔍 Troubleshooting

### Common Issues

**Service Not Starting**:
```bash
# Check logs
docker-compose -f docker-compose.test.yml logs keygen-test

# Check port conflicts
lsof -i :8001
```

**Tests Failing**:
```bash
# Check service health
curl http://localhost:8001/health

# Check resource usage
docker stats
```

**Performance Issues**:
```bash
# Monitor system resources
htop
iostat -x 1

# Check container limits
docker-compose -f docker-compose.test.yml exec keygen-test ulimit -a
```

### Debug Mode

Enable debug logging:
```bash
# Set debug environment variable
LOG_LEVEL=DEBUG ./run_tests.sh regression
```

### Cleanup Issues

Force cleanup:
```bash
# Remove all containers and images
docker-compose -f docker-compose.test.yml down -v --rmi all
docker system prune -a
```

## 📚 Test Development

### Adding New Tests

1. Create test file in `tests/` directory
2. Follow existing test patterns
3. Add error handling and logging
4. Update documentation

### Test Best Practices

- Use async/await for I/O operations
- Implement proper error handling
- Add comprehensive logging
- Include performance metrics
- Test edge cases and error conditions

### Continuous Integration

Integrate with CI/CD pipeline:

```yaml
# .github/workflows/test.yml
name: Test Suite
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Run Tests
        run: ./run_tests.sh full
```

## 📄 License

This testing framework is part of the Keygen Service project and follows the same licensing terms.

## 🤝 Contributing

Contributions to the testing framework are welcome! Please:

1. Add tests for new features
2. Improve existing test coverage
3. Enhance performance testing
4. Fix bugs and issues
5. Update documentation

## 📞 Support

For questions or issues with the testing framework:

1. Check existing documentation
2. Review test logs and reports
3. Consult troubleshooting section
4. Create an issue with detailed information

---

**Happy Testing! 🧪✨**
