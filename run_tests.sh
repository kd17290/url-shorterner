#!/bin/bash
"""
Docker-based test execution script for Keygen Service.

Usage:
  ./run_tests.sh [test_type]

Test types:
  - regression: Run regression tests only
  - load: Run load tests only
  - benchmark: Run quick benchmark only
  - full: Run complete test suite (default)
  - cleanup: Clean up test environment
"""

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
COMPOSE_FILE="docker-compose.test.yml"
TEST_TYPE="${1:-full}"
RESULTS_DIR="test_results"

# Helper functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    # Check Docker
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed or not in PATH"
        exit 1
    fi
    
    # Check Docker Compose
    if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
        log_error "Docker Compose is not installed or not in PATH"
        exit 1
    fi
    
    # Check if compose file exists
    if [ ! -f "$COMPOSE_FILE" ]; then
        log_error "Docker compose file not found: $COMPOSE_FILE"
        exit 1
    fi
    
    log_success "Prerequisites check passed"
}

# Setup environment
setup_environment() {
    log_info "Setting up test environment..."
    
    # Create results directory
    mkdir -p "$RESULTS_DIR"
    mkdir -p "load_test_results"
    mkdir -p "benchmark_results"
    
    log_success "Environment setup complete"
}

# Start services
start_services() {
    log_info "Starting test services..."
    
    # Stop any existing containers
    docker-compose -f "$COMPOSE_FILE" down -v 2>/dev/null || true
    
    # Build and start services
    docker-compose -f "$COMPOSE_FILE" up -d --build
    
    log_success "Services started"
}

# Wait for services to be healthy
wait_for_services() {
    log_info "Waiting for services to be healthy..."
    
    local max_wait=300
    local wait_interval=5
    local waited=0
    
    while [ $waited -lt $max_wait ]; do
        local healthy=true
        
        # Check PostgreSQL
        if ! docker-compose -f "$COMPOSE_FILE" exec -T postgres-test pg_isready -U test_user -d url_shortener_test &>/dev/null; then
            healthy=false
        fi
        
        # Check Redis
        if ! docker-compose -f "$COMPOSE_FILE" exec -T redis-test redis-cli ping &>/dev/null; then
            healthy=false
        fi
        
        # Check Keygen Service
        if ! curl -f http://localhost:8001/health &>/dev/null; then
            healthy=false
        fi
        
        if [ "$healthy" = true ]; then
            log_success "All services are healthy"
            return 0
        fi
        
        log_info "Waiting for services... (${waited}s/${max_wait}s)"
        sleep $wait_interval
        waited=$((waited + wait_interval))
    done
    
    log_error "Timeout waiting for services to be healthy"
    return 1
}

# Run regression tests
run_regression_tests() {
    log_info "Running regression tests..."
    
    docker-compose -f "$COMPOSE_FILE" exec -T benchmark-runner python tests/regression_test.py
    
    if [ $? -eq 0 ]; then
        log_success "Regression tests passed"
        return 0
    else
        log_error "Regression tests failed"
        return 1
    fi
}

# Run load tests
run_load_tests() {
    log_info "Running load tests..."
    
    docker-compose -f "$COMPOSE_FILE" exec -T benchmark-runner python tests/load_test.py
    
    if [ $? -eq 0 ]; then
        log_success "Load tests passed"
        return 0
    else
        log_error "Load tests failed"
        return 1
    fi
}

# Run quick benchmark
run_benchmark() {
    log_info "Running quick benchmark..."
    
    docker-compose -f "$COMPOSE_FILE" exec -T benchmark-runner python tests/quick_benchmark.py
    
    if [ $? -eq 0 ]; then
        log_success "Benchmark completed"
        return 0
    else
        log_error "Benchmark failed"
        return 1
    fi
}

# Show test results
show_results() {
    log_info "Test Results Summary:"
    
    if [ -f "$RESULTS_DIR/final_report.json" ]; then
        echo "Final Report: $RESULTS_DIR/final_report.json"
        
        # Extract key metrics
        if command -v jq &> /dev/null; then
            echo "Key Metrics:"
            jq -r '.key_metrics | to_entries[] | "  \(.key): \(.value)"' "$RESULTS_DIR/final_report.json"
        fi
    fi
    
    if [ -f "$RESULTS_DIR/regression_report.json" ]; then
        echo "Regression Report: $RESULTS_DIR/regression_report.json"
    fi
    
    if [ -f "$RESULTS_DIR/load_test_report.json" ]; then
        echo "Load Test Report: $RESULTS_DIR/load_test_report.json"
    fi
    
    if [ -f "$RESULTS_DIR/quick_benchmark.json" ]; then
        echo "Quick Benchmark: $RESULTS_DIR/quick_benchmark.json"
    fi
}

# Cleanup environment
cleanup() {
    log_info "Cleaning up test environment..."
    
    docker-compose -f "$COMPOSE_FILE" down -v
    docker image prune -f
    
    log_success "Cleanup complete"
}

# Show help
show_help() {
    echo "Usage: $0 [test_type]"
    echo ""
    echo "Test types:"
    echo "  regression    - Run regression tests only"
    echo "  load          - Run load tests only"
    echo "  benchmark     - Run quick benchmark only"
    echo "  full          - Run complete test suite (default)"
    echo "  cleanup       - Clean up test environment"
    echo ""
    echo "Examples:"
    echo "  $0 regression    # Run regression tests"
    echo "  $0 load          # Run load tests"
    echo "  $0 benchmark     # Run quick benchmark"
    echo "  $0 full          # Run complete test suite"
    echo "  $0 cleanup       # Clean up environment"
}

# Main execution
main() {
    case "$TEST_TYPE" in
        "regression")
            check_prerequisites
            setup_environment
            start_services
            wait_for_services
            run_regression_tests
            show_results
            ;;
        "load")
            check_prerequisites
            setup_environment
            start_services
            wait_for_services
            run_load_tests
            show_results
            ;;
        "benchmark")
            check_prerequisites
            setup_environment
            start_services
            wait_for_services
            run_benchmark
            show_results
            ;;
        "full")
            check_prerequisites
            setup_environment
            start_services
            wait_for_services
            run_regression_tests
            run_load_tests
            run_benchmark
            show_results
            ;;
        "cleanup")
            cleanup
            ;;
        "help"|"-h"|"--help")
            show_help
            ;;
        *)
            log_error "Unknown test type: $TEST_TYPE"
            show_help
            exit 1
            ;;
    esac
}

# Trap signals for cleanup
trap cleanup EXIT INT TERM

# Run main function
main
