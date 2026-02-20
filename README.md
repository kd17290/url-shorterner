# URL Shortener

[![CI](https://github.com/kd17290/url-shorterner/actions/workflows/ci.yml/badge.svg)](https://github.com/kd17290/url-shorterner/actions/workflows/ci.yml)

A modern, scalable URL shortener built with **FastAPI**, **PostgreSQL**, **Redis**, **Kafka**, **ClickHouse**, and **Docker**.

## Quick Start

```bash
# One command to start everything
make up
```

That's it. The API is available via load balancer at `http://localhost:8080`.

## Architecture

```text
[Client] -> [Nginx LB :8080] -> [app1/app2/app3]
                               -> [Redis + PostgreSQL + Kafka]
                               -> [Ingestion workers] -> [ClickHouse]
```

See [docs/architecture.md](docs/architecture.md) for the full end-to-end Mermaid diagram.

## API Usage

### Shorten a URL
```bash
curl -X POST http://localhost:8080/api/shorten \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.google.com"}'
```

### Shorten with custom code
```bash
curl -X POST http://localhost:8080/api/shorten \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.github.com", "custom_code": "gh"}'
```

### Redirect
```bash
curl -L http://localhost:8080/aB3xK9m
```

### Get stats
```bash
curl http://localhost:8080/api/stats/aB3xK9m
```

### Interactive API docs
- **Swagger UI**: http://localhost:8080/docs
- **ReDoc**: http://localhost:8080/redoc

## Commands

| Command | Description |
|---|---|
| `make up` | Start all services (build + run) |
| `make down` | Stop all services |
| `make test` | Run test suite (Dockerized) |
| `make lint` | Check formatting (black + isort, Docker) |
| `make typecheck` | Run pyright static analysis (Docker) |
| `make standards-check` | Run ruff + Pydantic pattern checks (Docker) |
| `make bench` | Full workflow benchmark: writer + reader + celebrity (Docker) |
| `make orchestrator` | Run 10-minute request generator |
| `make orchestrator-celebrity` | Run hot-key / celebrity traffic scenario |
| `make orchestrator-100k` | Run high-throughput generator profile (~100k rps target) |
| `make orchestrator-100k-dist` | Run distributed high-throughput profile (master + workers) |
| `make smoke` | Run short distributed smoke load, then strict infra checks |
| `make load-ui` | Start live test + service activity UIs |
| `make boards` | One-command bootstrap for all boards + live data |
| `make doctor` | One-command health report for boards + metrics flow |
| `make doctor-strict` | Fail-fast infra checks for partitioning + load distribution |
| `make celebrity-assert` | Assert top celebrity links reach required click threshold |
| `make logs` | Tail all logs |
| `make logs-api` | Tail API logs |
| `make clean` | Remove containers, volumes, images |
| `make restart` | Restart API service |
| `make status` | Show running containers |

## Running Tests

```bash
make test
```

Tests run in isolated Docker containers with their own PostgreSQL and Redis instances.

## CI/CD Pipeline

Every push and pull request runs the full pipeline automatically:

```
lint ──┐
        ├──► standards-check ──► test ──► bench-regression
typecheck ──┘
```

| Job | What it checks |
|---|---|
| **Format Check** | black + isort formatting |
| **Type Check** | pyright static analysis |
| **Coding Standards** | ruff rules + no loose-dict payloads + Pydantic model usage |
| **Functional Tests** | Full pytest suite against live stack |
| **Benchmark Regression** | writer + reader + celebrity RPS vs `docs/bench_baselines.json` (≤15% tolerance) |

A commit is **blocked** if any job fails or if benchmark RPS regresses more than 15%.

## Running Load Generation

```bash
# 10-minute generator profile (1000 read/s + 500 write/s target shape)
make orchestrator

# live load UI + observability boards
make load-ui
```

> Achieved throughput depends on host/network capacity. Dashboard values show observed rates.

### 100k-rps target profile

```bash
make orchestrator-100k
```

This launches `request-generator-100k` with a high-throughput Locust profile.

Tune without editing code:

```bash
REQUEST_GENERATOR_USERS_100K=6000 \
REQUEST_GENERATOR_SPAWN_RATE_100K=1500 \
REQUEST_GENERATOR_PROCESSES_100K=6 \
TARGET_READ_USERS_100K=5000 \
TARGET_WRITE_USERS_100K=1000 \
TARGET_READ_RPS_PER_USER_100K=20 \
TARGET_WRITE_RPS_PER_USER_100K=20 \
make orchestrator-100k
```

> Important: `100k rps` is a target envelope. Single-host Docker setups usually need substantial CPU/network headroom and may require distributed load agents for sustained real 100k+.

### Celebrity / hot-key scenario

```bash
make orchestrator-celebrity
```

This simulates heavy skew where most reads hit a small celebrity code pool.
Tune with env vars:

```bash
CELEBRITY_TRAFFIC_PERCENT_CELEBRITY=0.9 \
CELEBRITY_POOL_SIZE_CELEBRITY=100 \
make orchestrator-celebrity
```

### Distributed 100k-user profile (recommended)

```bash
REQUEST_GENERATOR_WORKERS_DIST=8 \
REQUEST_GENERATOR_USERS_DIST=100000 \
REQUEST_GENERATOR_SPAWN_RATE_DIST=5000 \
REQUEST_GENERATOR_DURATION_DIST=10m \
TARGET_READ_USERS_DIST=95000 \
TARGET_WRITE_USERS_DIST=5000 \
TARGET_READ_RPS_PER_USER_DIST=1 \
TARGET_WRITE_RPS_PER_USER_DIST=1 \
make orchestrator-100k-dist
```

Use this when single-container `orchestrator-100k` saturates before target rates.

For stronger generation on a single machine, start with:

```bash
REQUEST_GENERATOR_WORKERS_DIST=24 \
REQUEST_GENERATOR_PROCESSES_DIST=2 \
REQUEST_GENERATOR_USERS_DIST=100000 \
REQUEST_GENERATOR_SPAWN_RATE_DIST=5000 \
REQUEST_GENERATOR_DURATION_DIST=10m \
TARGET_READ_USERS_DIST=95000 \
TARGET_WRITE_USERS_DIST=5000 \
TARGET_READ_RPS_PER_USER_DIST=1 \
TARGET_WRITE_RPS_PER_USER_DIST=1 \
make orchestrator-100k-dist
```

If you still observe ~1k-2k rps, bottleneck is platform capacity (CPU/network/502 saturation), not Locust config. Scale workers to separate hosts for true 100k+ sustained rates.

## Live Test and Service Visualization UI

```bash
make load-ui
```

- Locust web UI: `http://localhost:8089` (ongoing load metrics)
- Dozzle logs UI: `http://localhost:9999` (live Docker service logs/actions)
- Grafana: `http://localhost:3000` (live request counters, status-code groups, per-app usage)
- Prometheus targets/query UI: `http://localhost:9090`
- ClickHouse SQL UI: `http://localhost:8088`

## One-Go bootstrap for all boards with live data

```bash
make boards
```

This starts:
- app cluster + load balancer
- Kafka + ingestion consumers + ClickHouse
- Locust live load UI and request generator (so dashboards receive traffic)
- Prometheus + Grafana + Dozzle + ClickHouse SQL UI

### Required defaults for immediate visibility
- Grafana login: `admin / admin`
- Prometheus target health should show `up` for `app_nodes` and `clickhouse_exporter`
- Locust should be in running state (autostarted in `load-ui`)

### Quick checks
```bash
# Prometheus targets
curl -s http://localhost:9090/api/v1/targets

# Per-app request rate split
curl -s "http://localhost:9090/api/v1/query?query=sum%20by%20(instance)%20(rate(http_requests_total%7Bjob%3D%22app_nodes%22%7D%5B1m%5D))"
```

Or run all checks together:
```bash
make doctor
```

Strict infra checks (fail on bad partitioning/load spread):

```bash
make doctor-strict
```

Tune strict checks for bursty workloads:

```bash
DOCTOR_RATE_WINDOW=2m \
DOCTOR_INGESTION_RATE_WINDOW=2m \
DOCTOR_5XX_WINDOW=5m \
DOCTOR_MIN_APP_RPS=0.5 \
DOCTOR_MIN_INGESTION_RPS=0.2 \
DOCTOR_MAX_5XX_RPS=50 \
make doctor-strict
```

Immediate-pass variant when one app is intentionally near-idle:

```bash
DOCTOR_MIN_APP_RPS=0.1 make doctor-strict
```

Smoke + strict validation in one command:

```bash
make smoke
```

Celebrity objective assertion (defaults: top 100 links each >= 10,000 clicks):

```bash
make celebrity-assert
```

## View ClickHouse Metrics and Tables

### 1) Prometheus metrics from ClickHouse
```bash
curl http://localhost:9090/api/v1/query?query=up%7Bjob%3D%22clickhouse_exporter%22%7D
```

### 2) Inspect click events row growth
```bash
docker compose exec -T clickhouse clickhouse-client \
  --user default --password clickhouse \
  --query "SELECT count() AS rows FROM click_events"
```

### 3) Top clicked short codes in analytics DB
```bash
docker compose exec -T clickhouse clickhouse-client \
  --user default --password clickhouse \
  --query "SELECT short_code, sum(delta) AS clicks FROM click_events GROUP BY short_code ORDER BY clicks DESC LIMIT 20"
```

## Main DB options for larger scale

If PostgreSQL single-primary becomes bottlenecked, common next steps are:

1. **PostgreSQL + Citus** (recommended first): shard URLs by `short_code`, keep SQL compatibility.
2. **PostgreSQL primary + multiple read replicas**: easy path for read-heavy expansions.
3. **CockroachDB**: distributed SQL with horizontal writes, higher operational complexity.
4. **FoundationDB + stateless layer**: very high scale, but requires custom data modeling.

For this project architecture, **PostgreSQL + Citus** is the most pragmatic next move.

## Project Structure

```
.
├── app/
│   ├── __init__.py
│   ├── main.py          # FastAPI app + lifespan
│   ├── config.py         # Settings via env vars
│   ├── database.py       # SQLAlchemy async engine
│   ├── redis.py          # Redis client
│   ├── models.py         # ORM models
│   ├── schemas.py        # Pydantic schemas
│   ├── service.py        # Business logic
│   └── routes.py         # API endpoints
├── tests/
│   ├── conftest.py       # Fixtures
│   ├── test_health.py
│   ├── test_shorten.py
│   ├── test_redirect.py
│   ├── test_stats.py
│   └── test_service.py
├── docker/
│   └── api/
│       └── Dockerfile
├── services/
│   ├── keygen/          # Separate key generation service
│   └── ingestion/       # Separate click-ingestion consumer service
├── docs/
│   ├── architecture.md   # System architecture
│   ├── scaling-strategy.md
│   ├── strategies.md     # Design trade-offs
│   └── api.md            # API documentation
├── stress/
│   └── locustfile.py     # Stress and concurrency scenarios
├── docker-compose.yml
├── Makefile
├── requirements.txt
├── pytest.ini
└── README.md
```

## Tech Stack

| Layer | Technology |
|---|---|
| API | Python 3.12 + FastAPI |
| Database | PostgreSQL 16 |
| Cache | Redis 7 |
| ORM | SQLAlchemy 2.0 (async) |
| Validation | Pydantic v2 |
| Testing | pytest + httpx |
| Infrastructure | Docker Compose |
| Live Load UI | Locust Web UI + Dozzle |

## Documentation

- [Architecture](docs/architecture.md) — distributed topology, runtime flows, service inventory, observability surfaces
- [Scaling Strategy](docs/scaling-strategy.md) — scaling phases, bottlenecks, and operational progression
- [Design Strategies](docs/strategies.md) — strategy catalog with scope, benefits, drawbacks, and upgrade triggers
- [Coding Standards](docs/coding-standards.md) — enforced readability, typing, and maintainability rules
- [API Reference](docs/api.md) — endpoint documentation

## Implementation Phases

- [x] **Phase 1**: Foundation — API, DB, cache, tests, docs
- [ ] **Phase 2**: Frontend + Analytics — React UI, click tracking, dashboard
- [ ] **Phase 3**: Scalability — Rate limiting, Nginx LB, horizontal scaling
- [ ] **Phase 4**: Testing Infrastructure — Stress testing, regression, concurrency
- [ ] **Phase 5**: Documentation & Diagrams — Mermaid diagrams, extended docs

## License

MIT
