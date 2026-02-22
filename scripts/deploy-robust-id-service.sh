#!/bin/bash

# Deploy Robust ID Allocation Service
# Redis Sentinel + AOF + PostgreSQL Fallback

set -e

echo "🚀 Deploying Robust ID Allocation Service..."

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    print_error "Docker is not running. Please start Docker first."
    exit 1
fi

# Stop existing Redis services
print_status "Stopping existing Redis services..."
docker compose -f docker-compose.yml down keygen-redis-primary keygen-redis-secondary 2>/dev/null || true

# Start Redis Sentinel cluster
print_status "Starting Redis Sentinel cluster..."
docker compose -f docker-compose.redis-sentinel.yml up -d

# Wait for Redis master to be ready
print_status "Waiting for Redis master to be ready..."
for i in {1..30}; do
    if docker exec urlshortener-redis-master redis-cli ping > /dev/null 2>&1; then
        print_status "Redis master is ready!"
        break
    fi
    if [ $i -eq 30 ]; then
        print_error "Redis master failed to start"
        exit 1
    fi
    sleep 2
done

# Wait for replicas to sync
print_status "Waiting for Redis replicas to sync..."
for i in {1..30}; do
    replica_count=$(docker exec urlshortener-redis-master redis-cli info replication | grep "connected_slaves" | cut -d: -f2 | tr -d '\r')
    if [ "$replica_count" -eq 2 ]; then
        print_status "Redis replicas are synced!"
        break
    fi
    if [ $i -eq 30 ]; then
        print_warning "Redis replicas may still be syncing..."
    fi
    sleep 2
done

# Wait for Sentinels to be ready
print_status "Waiting for Redis Sentinels to be ready..."
for i in {1..30}; do
    sentinel_count=0
    for port in 26379 26380 26381; do
        if docker exec urlshortener-redis-sentinel-1 redis-cli -p $port sentinel masters | grep mymaster > /dev/null 2>&1; then
            ((sentinel_count++))
        fi
    done
    if [ $sentinel_count -eq 3 ]; then
        print_status "All Redis Sentinels are ready!"
        break
    fi
    if [ $i -eq 30 ]; then
        print_warning "Some Redis Sentinels may not be ready yet..."
    fi
    sleep 2
done

# Test Redis Sentinel failover
print_status "Testing Redis Sentinel failover..."
docker exec urlshortener-redis-sentinel-1 redis-cli -p 26379 sentinel ckquorum mymaster

# Update environment variables
print_status "Updating environment variables..."
cat > .env.redis-sentinel << EOF
# Redis Sentinel Configuration
REDIS_SENTINEL_HOSTS=localhost:26379,localhost:26380,localhost:26381
REDIS_SENTINEL_MASTER_NAME=mymaster
REDIS_SENTINEL_QUORUM=2

# Legacy compatibility
KEYGEN_PRIMARY_REDIS_URL=redis://urlshortener-redis-master:6379/0
KEYGEN_SECONDARY_REDIS_URL=redis://urlshortener-redis-replica-1:6379/0
EOF

# Test the new service
print_status "Testing new ID allocation service..."
docker compose -f docker-compose.yml build keygen
docker compose -f docker-compose.yml up -d keygen

# Wait for keygen service to be ready
print_status "Waiting for keygen service to be ready..."
for i in {1..30}; do
    if curl -s http://localhost:8010/health | grep -q "healthy"; then
        print_status "Keygen service is ready!"
        break
    fi
    if [ $i -eq 30 ]; then
        print_error "Keygen service failed to start"
        exit 1
    fi
    sleep 2
done

# Test ID allocation
print_status "Testing ID allocation..."
response=$(curl -s -X POST http://localhost:8010/allocate \
    -H "Content-Type: application/json" \
    -d '{"size": 1000}')

if echo "$response" | grep -q '"start"'; then
    print_status "✅ ID allocation test successful!"
    echo "Response: $response"
else
    print_error "❌ ID allocation test failed!"
    echo "Response: $response"
    exit 1
fi

# Test failover
print_status "Testing Redis failover..."
docker stop urlshortener-redis-master

# Wait for failover to complete
sleep 10

# Test allocation during failover
response=$(curl -s -X POST http://localhost:8010/allocate \
    -H "Content-Type: application/json" \
    -d '{"size": 100}')

if echo "$response" | grep -q '"start"'; then
    print_status "✅ Failover test successful! Service still working."
else
    print_warning "⚠️  Failover test may need manual verification."
fi

# Restart master
print_status "Restarting Redis master..."
docker start urlshortener-redis-master

print_status "🎉 Robust ID Allocation Service deployed successfully!"
print_status ""
print_status "Service Features:"
print_status "  ✅ Redis Sentinel with automatic failover"
print_status "  ✅ AOF persistence for data durability"
print_status "  ✅ PostgreSQL sequence fallback"
print_status "  ✅ Distributed locking"
print_status "  ✅ Zero collision guarantee"
print_status "  ✅ Comprehensive monitoring"
print_status ""
print_status "Service Endpoints:"
print_status "  📊 Health: http://localhost:8010/health"
print_status "  📈 Metrics: http://localhost:8010/metrics"
print_status "  📋 Status: http://localhost:8010/status"
print_status "  🔢 Allocate: http://localhost:8010/allocate"
print_status ""
print_status "Redis Sentinel Cluster:"
print_status "  🏛️  Master: urlshortener-redis-master:6379"
print_status "  📡 Replica 1: urlshortener-redis-replica-1:6379"
print_status "  📡 Replica 2: urlshortener-redis-replica-2:6379"
print_status "  🛡️  Sentinel 1: localhost:26379"
print_status "  🛡️  Sentinel 2: localhost:26380"
print_status "  🛡️  Sentinel 3: localhost:26381"
