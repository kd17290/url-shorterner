# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **CI/CD pipeline** (`.github/workflows/ci.yml`) — 5-job GitHub Actions pipeline: format check → type check → coding standards → functional tests → benchmark regression gate
- **Benchmark regression gate** — `scripts/bench_regression_check.py` parses `make bench` output and fails CI if any scenario regresses >15% vs `docs/bench_baselines.json`
- **Full workflow benchmark** (`make bench`) — writer + reader + celebrity scenarios run concurrently; replaces health-only micro benchmark
- **`make standards-check`** — Docker-only ruff check (E, W, F, UP, B, C4, SIM, RUF rule sets) + grep checks for banned loose-dict payload patterns
- **Pydantic models for all predictable schemas** — `ClickEvent`, `CachedURLPayload`, `ClickAggregates`, `ClickHouseClickEventRow` replacing all loose `dict[str, ...]` and `list[list[object]]` patterns
- **Kafka partition affinity** — `publish_click_event` sends with `key=short_code.encode()` for correct per-consumer aggregation
- **Redis pipelining** — all multi-key Redis writes use `pipeline(transaction=False)` for single round-trip
- **Benchmark baselines** (`docs/bench_baselines.json`) — stored per-scenario RPS baselines for CI regression gate
- **ruff config** in `pyproject.toml` — line-length 120, excludes stress/tests, ignores FastAPI-idiomatic patterns

### Changed
- `bench-full` renamed to `bench` — it is the only benchmark target; health-only micro benchmark removed
- `app/kafka.py` — `publish_click_event` now builds payload via `ClickEvent.model_dump(mode="json")`
- `app/service.py` — `_cache_url` now uses `CachedURLPayload.model_validate(url).model_dump(mode="json")`
- `services/cache_warmer/worker.py` — `_serialize` returns `CachedURLPayload` instead of hand-rolled dict
- `services/ingestion/worker.py` — all batch types use `list[ClickEvent]`; aggregation uses `ClickAggregates`; analytics rows use `list[ClickHouseClickEventRow]`
- `app/routes.py` — `raise HTTPException(...) from exc` for proper exception chaining (B904)
- `app/main.py` — `AsyncGenerator` imported from `collections.abc` (UP035)
- `services/ingestion/worker.py` — `Awaitable` imported from `collections.abc` (UP035)
- Coding standards (`docs/coding-standards.md`) — expanded §9 (Pydantic for all predictable schemas), added §21 sub-rules (pipelining, batching, partition affinity, hot-key), added §33 (Docker-only tooling), added §34 (benchmark regression gate)
- Git author updated to `Kuldeep <kuldeep17290@gmail.com>`

## [1.0.0] - 2026-02-14

### Added
- Phase 1 complete: Foundation layer
- URL shortening API with custom code support
- Click tracking and statistics
- Health check endpoints
- Redis caching layer
- PostgreSQL data persistence
- Docker Compose orchestration
- Full test coverage (unit, integration)
- Comprehensive documentation
- ASCII architecture diagrams
- Strategy trade-off analysis
- Development tooling (Makefile, pyproject.toml)

### Features
- `POST /api/shorten` - Create short URLs
- `GET /:code` - Redirect to original URL
- `GET /api/stats/:code` - Get URL statistics
- `GET /health` - Service health check
- Custom alphanumeric short codes
- Automatic short code generation
- Click counting with atomic updates
- Read-through caching with TTL
- Environment-based configuration

### Technology Stack
- Python 3.12 + FastAPI
- PostgreSQL 16
- Redis 7
- Docker & Docker Compose
- pytest for testing
- Black + isort for formatting
- Pydantic for validation

### Documentation
- README with quick start guide
- Architecture documentation
- Scaling strategy guide
- Design strategy comparisons
- API reference
- Contributing guidelines
- Coding standards

---

## Development Phases

### Phase 1 ✅ Foundation
- [x] Project structure
- [x] Docker environment
- [x] FastAPI backend
- [x] PostgreSQL + Redis
- [x] Core endpoints
- [x] Test suite
- [x] Documentation

### Phase 2 🔄 Frontend + Analytics
- [ ] React frontend
- [ ] Click analytics dashboard
- [ ] Real-time statistics
- [ ] E2E tests

### Phase 3 ⏳ Scalability
- [ ] Rate limiting
- [ ] Custom aliases
- [ ] URL expiration
- [ ] Nginx load balancer
- [ ] Horizontal scaling

### Phase 4 ⏳ Testing Infrastructure
- [ ] Locust stress testing
- [ ] Regression suite
- [ ] Concurrency tests

### Phase 5 ⏳ Documentation & Diagrams
- [ ] Mermaid diagrams
- [ ] Extended documentation
- [ ] Performance benchmarks
