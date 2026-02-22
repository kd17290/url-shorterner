"""Comprehensive unit tests for URL shortening service.

This module provides extensive test coverage for the URL shortening service
including performance benchmarks, edge cases, and integration scenarios.
"""

import asyncio
import time
from typing import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models import URL
from app.schemas import URLCreate
from app.url_service import BASE62_ALPHABET, PerformanceMetrics, URLShorteningService, _base62_encode

# ============================================================================
# TEST FIXTURES AND UTILITIES
# ============================================================================


@pytest.fixture
def settings() -> Settings:
    """Get test settings."""
    return get_settings()


@pytest.fixture
async def mock_database() -> AsyncMock:
    """Mock database session."""
    db = AsyncMock(spec=AsyncSession)
    db.execute = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.fixture
async def mock_redis() -> AsyncMock:
    """Mock Redis client."""
    redis_client = AsyncMock(spec=redis.Redis)
    redis_client.get = AsyncMock(return_value=None)
    redis_client.set = AsyncMock(return_value=True)
    redis_client.setex = AsyncMock(return_value=True)
    redis_client.incr = AsyncMock(return_value=1)
    redis_client.expire = AsyncMock(return_value=True)
    redis_client.delete = AsyncMock(return_value=1)
    redis_client.xadd = AsyncMock(return_value="123456789")
    return redis_client


@pytest.fixture
def mock_logger() -> MagicMock:
    """Mock logger."""
    logger = MagicMock()
    logger.info = MagicMock()
    logger.debug = MagicMock()
    logger.warning = MagicMock()
    logger.error = MagicMock()
    return logger


@pytest.fixture
def url_service(mock_database, mock_redis, mock_logger, settings) -> URLShorteningService:
    """Create URL service with mocked dependencies."""
    # Create a mock RequestContext
    from unittest.mock import Mock

    ctx = Mock()
    ctx.database = mock_database
    ctx.cache_writer = mock_redis
    ctx.cache_reader = mock_redis
    ctx.logger = mock_logger
    ctx.settings = settings

    return URLShorteningService(ctx)


@pytest.fixture
def sample_url_request() -> URLCreate:
    """Sample URL creation request."""
    return URLCreate(url="https://example.com")


@pytest.fixture
def sample_url() -> URL:
    """Sample URL model."""
    from datetime import datetime

    return URL(
        id=1,
        short_code="abc123",
        original_url="https://example.com",
        clicks=0,
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
    )


# ============================================================================
# UTILITY FUNCTION TESTS
# ============================================================================


def test_base62_encode_basic():
    """Test basic base62 encoding."""
    assert _base62_encode(0) == "0"
    assert _base62_encode(1) == "1"
    assert _base62_encode(61) == "Z"
    assert _base62_encode(62) == "10"


def test_base62_encode_large_numbers():
    """Test base62 encoding with large numbers."""
    assert _base62_encode(12345) == "3d7"
    assert _base62_encode(999999) == "4c91"


def test_base62_encode_negative():
    """Test base62 encoding with negative numbers."""
    with pytest.raises(ValueError, match="Number must be non-negative"):
        _base62_encode(-1)


# ============================================================================
# SERVICE CLASS TESTS
# ============================================================================


class TestURLShorteningService:
    """Test suite for URLShorteningService class."""

    def test_service_initialization(self, url_service):
        """Test service initialization."""
        assert url_service._db is not None
        assert url_service._cache_write is not None
        assert url_service._cache_read is not None
        assert url_service._logger is not None
        assert url_service._settings is not None
        assert url_service._metrics is not None

    @pytest.mark.asyncio
    async def test_create_short_url_success(self, url_service, sample_url_request, sample_url):
        """Test successful URL creation."""
        # Mock database operations
        url_service._db.execute.return_value.scalar_one_or_none.return_value = None
        url_service._db.commit.return_value = None

        # Mock the database to properly set up the URL object
        def mock_refresh(obj):
            obj.id = sample_url.id
            obj.clicks = sample_url.clicks
            obj.created_at = sample_url.created_at
            obj.updated_at = sample_url.updated_at

        url_service._db.refresh.side_effect = mock_refresh

        # Mock ID allocation
        with patch("app.url_service._allocate_short_code_with_cache", return_value="abc123"):
            url = await url_service.create_short_url(sample_url_request)

        assert url.short_code == "abc123"
        assert url.original_url == str(sample_url_request.url)
        assert url.id == sample_url.id
        assert url.clicks == sample_url.clicks
        url_service._db.add.assert_called_once()
        url_service._db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_short_url_custom_code_collision(self, url_service, sample_url_request):
        """Test custom code collision handling."""
        # Mock existing URL found
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_url
        url_service._db.execute.return_value = mock_result

        # Test with custom code
        request_with_custom = URLCreate(url="https://example.com", custom_code="abc123")

        with pytest.raises(ValueError, match="Custom code 'abc123' is already taken"):
            await url_service.create_short_url(request_with_custom)

    @pytest.mark.asyncio
    async def test_lookup_url_cache_hit(self, url_service, sample_url):
        """Test URL lookup with cache hit."""
        # Mock cache hit
        cached_data = (
            '{"id":1,"short_code":"abc123","original_url":"https://example.com",'
            '"clicks":0,"created_at":"2024-01-01T00:00:00Z","updated_at":"2024-01-01T00:00:00Z"}'
        )
        url_service._cache_read.get.return_value = cached_data

        url = await url_service.lookup_url_by_code("abc123")

        assert url is not None
        assert url.short_code == "abc123"
        assert url.original_url == "https://example.com"
        url_service._cache_read.get.assert_called_once_with("url:abc123")

    @pytest.mark.asyncio
    async def test_lookup_url_cache_miss(self, url_service, sample_url):
        """Test URL lookup with cache miss."""
        # Mock cache miss
        url_service._cache_read.get.return_value = None

        # Mock database hit
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_url
        url_service._db.execute.return_value = mock_result

        # Mock lock acquisition
        url_service._cache_write.set.return_value = True
        url_service._cache_write.delete.return_value = True

        url = await url_service.lookup_url_by_code("abc123")

        assert url is not None
        assert url.short_code == "abc123"
        url_service._db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_lookup_url_not_found(self, url_service):
        """Test URL lookup when URL not found."""
        # Mock cache miss
        url_service._cache_read.get.return_value = None

        # Mock database miss
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        url_service._db.execute.return_value = mock_result

        # Mock lock acquisition
        url_service._cache_write.set.return_value = True
        url_service._cache_write.delete.return_value = True

        url = await url_service.lookup_url_by_code("nonexistent")

        assert url is None

    @pytest.mark.asyncio
    async def test_track_url_click(self, url_service, sample_url):
        """Test click tracking."""
        # Mock Redis operations
        url_service._cache_write.incr.return_value = 1
        url_service._cache_write.expire.return_value = True

        # Mock Kafka success
        with patch("app.url_service.publish_click_event", return_value=True):
            await url_service.track_url_click(sample_url)

        url_service._cache_write.incr.assert_called_once()
        url_service._cache_write.expire.assert_called_once()

    @pytest.mark.asyncio
    async def test_track_url_click_kafka_failure(self, url_service, sample_url):
        """Test click tracking with Kafka failure."""
        # Mock Redis operations
        url_service._cache_write.incr.return_value = 1
        url_service._cache_write.expire.return_value = True
        url_service._cache_write.xadd.return_value = "123456789"

        # Mock Kafka failure
        with patch("app.url_service.publish_click_event", return_value=False):
            await url_service.track_url_click(sample_url)

        url_service._cache_write.xadd.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_url_statistics_with_buffered_clicks(self, url_service, sample_url):
        """Test getting statistics with buffered clicks."""
        # Mock buffered clicks
        url_service._cache_write.get.return_value = "5"

        # Mock URL lookup
        with patch.object(url_service, "lookup_url_by_code", return_value=sample_url):
            stats = await url_service.get_url_statistics("abc123")

        assert stats is not None
        assert stats.clicks == 5  # Original 0 + buffered 5


# ============================================================================
# PERFORMANCE TESTS
# ============================================================================


class TestServicePerformance:
    """Test suite for service performance characteristics."""

    @pytest.mark.asyncio
    async def test_create_short_url_performance(self, url_service, sample_url_request, sample_url):
        """Test URL creation performance."""
        # Mock database operations for realistic timing
        url_service._db.execute.return_value.scalar_one_or_none.return_value = None
        url_service._db.commit.return_value = None

        # Mock the database to properly set up the URL object
        def mock_refresh(obj):
            obj.id = sample_url.id
            obj.clicks = sample_url.clicks
            obj.created_at = sample_url.created_at
            obj.updated_at = sample_url.updated_at

        url_service._db.refresh.side_effect = mock_refresh

        # Mock ID allocation
        with patch("app.url_service._allocate_short_code_with_cache", return_value="perf123"):
            start_time = time.perf_counter()
            url = await url_service.create_short_url(sample_url_request)
            duration = time.perf_counter() - start_time

        assert url.short_code == "perf123"
        assert duration < 1.0  # Should complete within 1 second

    @pytest.mark.asyncio
    async def test_lookup_url_performance_cache_hit(self, url_service):
        """Test URL lookup performance with cache hit."""
        # Mock cache hit
        cached_data = (
            '{"id":1,"short_code":"abc123","original_url":"https://example.com",'
            '"clicks":0,"created_at":"2024-01-01T00:00:00Z","updated_at":"2024-01-01T00:00:00Z"}'
        )
        url_service._cache_read.get.return_value = cached_data

        start_time = time.perf_counter()
        url = await url_service.lookup_url_by_code("abc123")
        duration = time.perf_counter() - start_time

        assert url is not None
        assert duration < 0.01  # Cache hits should be very fast (<10ms)

    @pytest.mark.asyncio
    async def test_lookup_url_performance_cache_miss(self, url_service, sample_url):
        """Test URL lookup performance with cache miss."""
        # Mock cache miss
        url_service._cache_read.get.return_value = None

        # Mock database hit
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_url
        url_service._db.execute.return_value = mock_result

        # Mock lock operations
        url_service._cache_write.set.return_value = True
        url_service._cache_write.delete.return_value = True

        start_time = time.perf_counter()
        url = await url_service.lookup_url_by_code("abc123")
        duration = time.perf_counter() - start_time

        assert url is not None
        assert duration < 0.05  # Cache misses should be fast (<50ms)

    @pytest.mark.asyncio
    async def test_track_click_performance(self, url_service, sample_url):
        """Test click tracking performance."""
        # Mock Redis operations
        url_service._cache_write.incr.return_value = 1
        url_service._cache_write.expire.return_value = True

        # Mock Kafka success
        with patch("app.url_service.publish_click_event", return_value=True):
            start_time = time.perf_counter()
            await url_service.track_url_click(sample_url)
            duration = time.perf_counter() - start_time

        assert duration < 0.01  # Click tracking should be very fast (<10ms)

    @pytest.mark.asyncio
    async def test_concurrent_url_creation(self, url_service, sample_url_request, sample_url):
        """Test concurrent URL creation performance."""
        # Mock database operations
        url_service._db.execute.return_value.scalar_one_or_none.return_value = None
        url_service._db.commit.return_value = None

        # Mock the database to properly set up the URL object
        def mock_refresh(obj):
            obj.id = sample_url.id
            obj.clicks = sample_url.clicks
            obj.created_at = sample_url.created_at
            obj.updated_at = sample_url.updated_at

        url_service._db.refresh.side_effect = mock_refresh

        # Mock ID allocation with different codes for each request
        codes = [f"conc{i}" for i in range(5)]

        async def create_url(code):
            with patch("app.url_service._allocate_short_code_with_cache", return_value=code):
                return await url_service.create_short_url(sample_url_request)

        # Create multiple URLs concurrently
        tasks = [create_url(code) for code in codes]
        urls = await asyncio.gather(*tasks)

        assert len(urls) == 5
        assert all(url.short_code in codes for url in urls)


# ============================================================================
# PERFORMANCE MONITORING TESTS
# ============================================================================


class TestPerformanceMonitoring:
    """Test suite for performance monitoring functionality."""

    def test_performance_metrics_initialization(self):
        """Test performance metrics initialization."""
        metrics = PerformanceMetrics()
        assert metrics.operation_count == 0
        assert metrics.total_duration == 0.0
        assert metrics.cache_hits == 0
        assert metrics.cache_misses == 0

    def test_performance_metrics_calculation(self):
        """Test performance metrics calculations."""
        metrics = PerformanceMetrics()
        metrics.operation_count = 100
        metrics.total_duration = 2.5
        metrics.cache_hits = 95
        metrics.cache_misses = 5

        assert metrics.average_duration == 0.025
        assert metrics.cache_hit_rate == 95.0


# ============================================================================
# INTEGRATION TESTS
# ============================================================================


class TestServiceIntegration:
    """Integration tests for service components."""

    @pytest.mark.asyncio
    async def test_end_to_end_url_workflow(self, url_service, sample_url_request, sample_url):
        """Test complete URL creation and lookup workflow."""
        # Mock database operations
        url_service._db.execute.return_value.scalar_one_or_none.return_value = None
        url_service._db.commit.return_value = None

        # Mock the database to properly set up the URL object
        refresh_called = False

        def mock_refresh(obj):
            nonlocal refresh_called
            refresh_called = True
            obj.id = sample_url.id
            obj.clicks = sample_url.clicks
            obj.created_at = sample_url.created_at
            obj.updated_at = sample_url.updated_at

        url_service._db.refresh.side_effect = mock_refresh

        # Mock cache operations to avoid validation issues
        url_service._cache_write.set.return_value = True
        url_service._cache_write.delete.return_value = True

        # Mock the cache_url_object method to avoid validation errors
        async def mock_cache_url_object(url, cache=None):
            pass

        url_service._cache_url_object = mock_cache_url_object

        # Step 1: Create URL
        with patch("app.url_service._allocate_short_code_with_cache", return_value="abc123"):
            created_url = await url_service.create_short_url(sample_url_request)

        # Verify refresh was called
        assert refresh_called, "Database refresh was not called"

        assert created_url.short_code == "abc123"
        assert created_url.id == sample_url.id
        assert created_url.clicks == sample_url.clicks

        # Step 2: Lookup URL (cache miss scenario)
        url_service._cache_read.get.return_value = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = created_url
        url_service._db.execute.return_value = mock_result

        looked_up_url = await url_service.lookup_url_by_code("abc123")

        assert looked_up_url is not None
        assert looked_up_url.short_code == "abc123"
        assert looked_up_url.original_url == str(sample_url_request.url)

        # Step 3: Track click
        url_service._cache_write.incr.return_value = 1
        url_service._cache_write.expire.return_value = True

        with patch("app.url_service.publish_click_event", return_value=True):
            await url_service.track_url_click(looked_up_url)

        # Verify all operations were called
        url_service._db.add.assert_called_once()
        url_service._db.commit.assert_called()
        url_service._cache_write.incr.assert_called_once()


# ============================================================================
# BENCHMARK UTILITIES
# ============================================================================


def run_performance_benchmark():
    """Run comprehensive performance benchmark."""
    print("Running URL Shortening Service Performance Benchmark")
    print("=" * 60)

    # Test base62 encoding performance
    print("\n1. Base62 Encoding Performance:")
    start_time = time.perf_counter()
    for i in range(10000):
        _base62_encode(i)
    duration = time.perf_counter() - start_time
    print(f"   10,000 encodings in {duration:.3f}s")
    print(f"   Average: {(duration / 10000) * 1000:.3f}ms per encoding")

    # Test random code generation performance
    print("\n2. Random Code Generation Performance:")
    start_time = time.perf_counter()
    codes = [generate_random_short_code() for _ in range(1000)]
    duration = time.perf_counter() - start_time
    print(f"   1,000 codes generated in {duration:.3f}s")
    print(f"   Average: {(duration / 1000) * 1000:.3f}ms per code")
    print(f"   Uniqueness: {len(set(codes))}/1000")

    print("\n3. Memory Usage:")
    import sys

    print(f"   Process memory: {sys.getsizeof(codes) / 1024:.1f}KB for 1,000 codes")

    print("\nBenchmark completed!")


if __name__ == "__main__":
    run_performance_benchmark()
