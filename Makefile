.PHONY: up down build test orchestrator orchestrator-celebrity orchestrator-100k orchestrator-100k-dist orchestrator-100k-dist-fresh smoke load-ui boards doctor doctor-strict celebrity-assert logs clean restart status fmt lint typecheck bench standards-check python-infra-up rust-infra-up infra-down rust-build rust-bench bench-compare

# ── Stack switcher ─────────────────────────────────────────────────────────────
# Only one stack runs at a time. Both share the same infra (postgres/redis/kafka).
#
#   make python-infra-up   start Python stack (docker-compose.yml)
#   make rust-infra-up     start Rust stack   (docker-compose.rust.yml)
#   make infra-down        stop whichever stack is running

python-infra-up:
	@echo "==> Starting Python stack..."
	docker compose -f docker-compose.rust.yml down --remove-orphans 2>/dev/null || true
	docker compose up --build -d
	@echo "==> Python stack up at http://localhost:8080"

rust-infra-up:
	@echo "==> Starting Rust stack..."
	docker compose down --remove-orphans 2>/dev/null || true
	docker compose -f docker-compose.rust.yml up --build -d
	@echo "==> Rust stack up at http://localhost:8080"

infra-down:
	docker compose down --remove-orphans 2>/dev/null || true
	docker compose -f docker-compose.rust.yml down --remove-orphans 2>/dev/null || true

# Build Rust binaries only (no start)
rust-build:
	docker compose -f docker-compose.rust.yml build

# Benchmark Rust stack (same script, same knobs as Python bench)
rust-bench:
	@docker run --rm --network host \
		-e BENCH_BASE_URL=$${BENCH_BASE_URL:-http://host.docker.internal:8080} \
		-e BENCH_DURATION_SECONDS=$${BENCH_DURATION_SECONDS:-15} \
		-e BENCH_TIMEOUT_SECONDS=$${BENCH_TIMEOUT_SECONDS:-2} \
		-e BENCH_WRITER_CONCURRENCY=$${BENCH_WRITER_CONCURRENCY:-10} \
		-e BENCH_READER_CONCURRENCY=$${BENCH_READER_CONCURRENCY:-60} \
		-e BENCH_CELEBRITY_CONCURRENCY=$${BENCH_CELEBRITY_CONCURRENCY:-30} \
		-e BENCH_CELEBRITY_POOL_SIZE=$${BENCH_CELEBRITY_POOL_SIZE:-5} \
		-e BENCH_WARMUP_URLS=$${BENCH_WARMUP_URLS:-200} \
		-v "$$(pwd)":/work -w /work python:3.12-slim bash -lc \
		"pip install --no-cache-dir httpx==0.26.0 >/dev/null && python scripts/bench_http.py"

# Run both stacks sequentially and produce a side-by-side comparison.
# Results saved to /tmp/bench_python.txt and /tmp/bench_rust.txt.
bench-compare:
	@echo "=== Step 1: Python stack ==="
	$(MAKE) python-infra-up
	@echo "Waiting 30s for stack to stabilise..."
	@sleep 30
	$(MAKE) bench | tee /tmp/bench_python.txt
	@echo ""
	@echo "=== Step 2: Rust stack ==="
	$(MAKE) rust-infra-up
	@echo "Waiting 30s for stack to stabilise..."
	@sleep 30
	$(MAKE) rust-bench | tee /tmp/bench_rust.txt
	@echo ""
	@echo "=== Comparison ==="
	@python3 scripts/bench_compare.py /tmp/bench_python.txt /tmp/bench_rust.txt

# One command to start everything
up:
	docker compose up --build -d

# Stop all services
down:
	docker compose down

# Build without starting
build:
	docker compose build

# Run tests (spins up test DB + test Redis)
test:
	docker compose --profile test up --build --abort-on-container-exit test

# Run orchestrated load generator (10m, 1000 read/s + 500 write/s target)
orchestrator:
	docker compose up --abort-on-container-exit request-generator

# Run hot-key / celebrity traffic scenario
orchestrator-celebrity:
	docker compose up --abort-on-container-exit request-generator-celebrity

# Run high-throughput generator profile (targeting ~100k rps aggregate)
orchestrator-100k:
	docker compose up --abort-on-container-exit request-generator-100k

# Run distributed high-throughput profile (master + N workers)
orchestrator-100k-dist:
	docker compose up --no-deps --scale request-generator-dist-worker=$${REQUEST_GENERATOR_WORKERS_DIST:-24} --abort-on-container-exit request-generator-dist-master request-generator-dist-worker

# Full reset then run distributed high-throughput profile
orchestrator-100k-dist-fresh:
	docker ps -a --format '{{.Names}}' | grep '^urlshortener-' | xargs -r docker rm -f
	docker compose down -v --remove-orphans
	docker compose up --build -d
	docker compose up --no-deps --scale request-generator-dist-worker=$${REQUEST_GENERATOR_WORKERS_DIST:-24} --abort-on-container-exit request-generator-dist-master request-generator-dist-worker

# Short smoke load + strict infra validation
smoke:
	REQUEST_GENERATOR_WORKERS_DIST=$${REQUEST_GENERATOR_WORKERS_DIST:-6} \
	REQUEST_GENERATOR_USERS_DIST=$${REQUEST_GENERATOR_USERS_DIST:-12000} \
	REQUEST_GENERATOR_SPAWN_RATE_DIST=$${REQUEST_GENERATOR_SPAWN_RATE_DIST:-4000} \
	REQUEST_GENERATOR_DURATION_DIST=$${REQUEST_GENERATOR_DURATION_DIST:-90s} \
	TARGET_READ_USERS_DIST=$${TARGET_READ_USERS_DIST:-11400} \
	TARGET_WRITE_USERS_DIST=$${TARGET_WRITE_USERS_DIST:-600} \
	TARGET_READ_RPS_PER_USER_DIST=$${TARGET_READ_RPS_PER_USER_DIST:-1} \
	TARGET_WRITE_RPS_PER_USER_DIST=$${TARGET_WRITE_RPS_PER_USER_DIST:-1} \
	docker compose up --no-deps --scale request-generator-dist-worker=$${REQUEST_GENERATOR_WORKERS_DIST:-6} --abort-on-container-exit request-generator-dist-master request-generator-dist-worker
	$(MAKE) doctor-strict

# Launch live UIs for load and service activity
load-ui:
	docker compose up -d load-ui dozzle grafana clickhouse-dashboard prometheus

# One command: start platform + all boards + traffic generators
boards:
	docker compose up --build -d
	docker compose up -d load-ui request-generator dozzle grafana clickhouse-dashboard prometheus

# One command: health report for boards and data flow
doctor:
	@echo "== containers =="
	@docker compose ps app1 app2 app3 load-balancer ingestion-1 ingestion-2 ingestion-3 prometheus grafana load-ui request-generator request-generator-100k request-generator-dist-master clickhouse clickhouse-exporter dozzle
	@echo ""
	@echo "== prometheus targets =="
	@python3 -c "import json, urllib.request; obj=json.loads(urllib.request.urlopen('http://localhost:9090/api/v1/targets').read().decode()); [print(t['labels'].get('job'), t['labels'].get('instance'), t['health']) for t in obj['data']['activeTargets']]"
	@echo ""
	@echo "== per-app req/s =="
	@python3 -c "import json, urllib.parse, urllib.request; q='sum by (instance) (rate(http_requests_total{job=\"app_nodes\"}[1m]))'; u='http://localhost:9090/api/v1/query?query='+urllib.parse.quote(q); obj=json.loads(urllib.request.urlopen(u).read().decode()); [print(r['metric']['instance'], r['value'][1]) for r in sorted(obj['data']['result'], key=lambda item: item['metric']['instance'])]"
	@echo ""
	@echo "== per-ingestion consume/s =="
	@python3 -c "import json, urllib.parse, urllib.request; q='sum by (instance) (rate(ingestion_kafka_events_total{job=\"ingestion_workers\"}[1m]))'; u='http://localhost:9090/api/v1/query?query='+urllib.parse.quote(q); obj=json.loads(urllib.request.urlopen(u).read().decode()); [print(r['metric']['instance'], r['value'][1]) for r in sorted(obj['data']['result'], key=lambda item: item['metric']['instance'])]"
	@echo ""
	@echo "== app 5xx/s =="
	@python3 -c "import json, urllib.parse, urllib.request; q='sum(rate(http_requests_total{job=\"app_nodes\",status_code=~\"5..\"}[1m]))'; u='http://localhost:9090/api/v1/query?query='+urllib.parse.quote(q); obj=json.loads(urllib.request.urlopen(u).read().decode()); print(obj['data']['result'][0]['value'][1] if obj['data']['result'] else '0')"
	@echo ""
	@echo "== kafka topic partitions =="
	@docker compose exec -T kafka rpk -X brokers=kafka:9092 topic describe click_events | awk '/^PARTITIONS/{print $$0}'
	@echo ""
	@echo "== kafka consumer group =="
	@docker compose exec -T kafka rpk -X brokers=kafka:9092 group describe click_ingestion_group | sed -n '1,12p'
	@echo ""
	@echo "== clickhouse rows =="
	@docker compose exec -T clickhouse clickhouse-client --user default --password clickhouse --query "SELECT count() AS rows FROM click_events"

# Infra-level strict checks (fails fast on imbalance/regressions)
doctor-strict:
	@echo "== strict: kafka partition and consumer topology =="
	@parts=$$(docker compose exec -T kafka rpk -X brokers=kafka:9092 topic describe click_events | awk '/^PARTITIONS/{print $$2}'); \
	if [ -z "$$parts" ] || [ "$$parts" -lt 6 ]; then echo "FAIL: click_events partitions=$$parts (<6)"; exit 1; else echo "OK: click_events partitions=$$parts"; fi
	@members=$$(docker compose exec -T kafka rpk -X brokers=kafka:9092 group describe click_ingestion_group | awk '/^MEMBERS/{print $$2}'); \
	if [ -z "$$members" ] || [ "$$members" -lt 3 ]; then echo "FAIL: consumer members=$$members (<3)"; exit 1; else echo "OK: consumer members=$$members"; fi
	@echo "== strict: app and ingestion load distribution =="
	@python3 -c "import json,os,sys,urllib.parse,urllib.request; w=os.getenv('DOCTOR_RATE_WINDOW','2m'); m=float(os.getenv('DOCTOR_MIN_APP_RPS','0.5')); q=f'sum by (instance) (rate(http_requests_total{{job=\"app_nodes\"}}[{w}]))'; u='http://localhost:9090/api/v1/query?query='+urllib.parse.quote(q); rs=json.loads(urllib.request.urlopen(u).read().decode())['data']['result']; rows=sorted((r['metric'].get('instance','unknown'), float(r['value'][1])) for r in rs); print('app_rps_window', w); [print(f'  {i}: {v:.3f}') for i,v in rows]; failed=[(i,v) for i,v in rows if v<m]; (print(f'FAIL: expected 3 app instances, got {len(rows)}') or sys.exit(1)) if len(rows)<3 else None; (print(f'FAIL: app instances below DOCTOR_MIN_APP_RPS={m}') or [print(f'  {i}: {v:.3f}') for i,v in failed] or sys.exit(1)) if failed else None"
	@python3 -c "import json,os,sys,urllib.parse,urllib.request; w=os.getenv('DOCTOR_INGESTION_RATE_WINDOW', os.getenv('DOCTOR_RATE_WINDOW','2m')); m=float(os.getenv('DOCTOR_MIN_INGESTION_RPS','0.2')); q=f'sum by (instance) (rate(ingestion_kafka_events_total{{job=\"ingestion_workers\"}}[{w}]))'; u='http://localhost:9090/api/v1/query?query='+urllib.parse.quote(q); rs=json.loads(urllib.request.urlopen(u).read().decode())['data']['result']; rows=sorted((r['metric'].get('instance','unknown'), float(r['value'][1])) for r in rs); print('ingestion_rps_window', w); [print(f'  {i}: {v:.3f}') for i,v in rows]; failed=[(i,v) for i,v in rows if v<m]; (print(f'FAIL: expected 3 ingestion instances, got {len(rows)}') or sys.exit(1)) if len(rows)<3 else None; (print(f'FAIL: ingestion instances below DOCTOR_MIN_INGESTION_RPS={m}') or [print(f'  {i}: {v:.3f}') for i,v in failed] or sys.exit(1)) if failed else None"
	@python3 -c "import json,os,sys,urllib.parse,urllib.request; w=os.getenv('DOCTOR_5XX_WINDOW','5m'); mx=float(os.getenv('DOCTOR_MAX_5XX_RPS','50')); q=f'sum(rate(http_requests_total{{job=\"app_nodes\",status_code=~\"5..\"}}[{w}]))'; u='http://localhost:9090/api/v1/query?query='+urllib.parse.quote(q); rs=json.loads(urllib.request.urlopen(u).read().decode())['data']['result']; v=float(rs[0]['value'][1]) if rs else 0.0; print('app_5xx_window', w); print(f'  total_5xx_rps: {v:.3f}'); (print(f'FAIL: total_5xx_rps {v:.3f} > DOCTOR_MAX_5XX_RPS={mx}') or sys.exit(1)) if v>mx else None"
	@echo "OK: strict doctor checks passed"

# Assert celebrity objective: top N links each must have at least MIN clicks.
# Defaults target: top 100 links each >= 10000 clicks.
celebrity-assert:
	@docker compose exec -T db psql -U urlshortener -d urlshortener -v ON_ERROR_STOP=1 -c "WITH top_codes AS (SELECT short_code, clicks FROM urls ORDER BY clicks DESC LIMIT $${CELEBRITY_ASSERT_TOP_N:-100}) SELECT CASE WHEN count(*) = $${CELEBRITY_ASSERT_TOP_N:-100} AND min(clicks) >= $${CELEBRITY_ASSERT_MIN_CLICKS:-10000} THEN 'OK: celebrity target met' ELSE ('FAIL: top=' || count(*) || ', min_clicks=' || COALESCE(min(clicks),0)::text || ', expected_top=' || $${CELEBRITY_ASSERT_TOP_N:-100}::text || ', expected_min=' || $${CELEBRITY_ASSERT_MIN_CLICKS:-10000}::text) END AS result FROM top_codes;"
	@docker compose exec -T db psql -U urlshortener -d urlshortener -v ON_ERROR_STOP=1 -At -c "WITH top_codes AS (SELECT clicks FROM urls ORDER BY clicks DESC LIMIT $${CELEBRITY_ASSERT_TOP_N:-100}) SELECT CASE WHEN count(*) = $${CELEBRITY_ASSERT_TOP_N:-100} AND min(clicks) >= $${CELEBRITY_ASSERT_MIN_CLICKS:-10000} THEN 0 ELSE 1 END FROM top_codes;" | grep -q '^0$$'

# View logs
logs:
	docker compose logs -f

# View logs for specific service
logs-api:
	docker compose logs -f app1 app2 app3 load-balancer

logs-db:
	docker compose logs -f db

logs-redis:
	docker compose logs -f redis

# Clean everything (volumes, images)
clean:
	docker compose down -v --rmi local

# Restart API (useful during development)
restart:
	docker compose restart app1 app2 app3 load-balancer

# Show running containers
status:
	docker compose ps

# Docker-only formatting (no local installs)
fmt:
	@docker run --rm -v "$$(pwd)":/work -w /work python:3.12-slim bash -lc "pip install --no-cache-dir black==24.1.1 isort==5.13.2 >/dev/null && black . && isort ."

# Docker-only lint/typecheck (no local installs)
lint:
	@docker run --rm -v "$$(pwd)":/work -w /work python:3.12-slim bash -lc "pip install --no-cache-dir black==24.1.1 isort==5.13.2 >/dev/null && black --check . && isort --check-only ."

typecheck:
	@docker run --rm -v "$$(pwd)":/work -w /work python:3.12-slim bash -lc "export DEBIAN_FRONTEND=noninteractive; apt-get update >/dev/null && apt-get install -y --no-install-recommends libatomic1 nodejs npm >/dev/null && pip install --no-cache-dir -r requirements.txt >/dev/null && npm -g --silent install pyright@1.1.408 >/dev/null && pyright"

# Full workflow benchmark: writer + reader + celebrity hot-key (no local installs)
# This is the canonical benchmark — covers the complete request lifecycle.
# Env knobs:
#   BENCH_BASE_URL              (default http://host.docker.internal:8080)
#   BENCH_DURATION_SECONDS      (default 15)
#   BENCH_TIMEOUT_SECONDS       (default 2)
#   BENCH_WRITER_CONCURRENCY    (default 10)
#   BENCH_READER_CONCURRENCY    (default 60)
#   BENCH_CELEBRITY_CONCURRENCY (default 30)
#   BENCH_CELEBRITY_POOL_SIZE   (default 5)
#   BENCH_WARMUP_URLS           (default 200)
bench:
	@docker run --rm --network host \
		-e BENCH_BASE_URL=$${BENCH_BASE_URL:-http://host.docker.internal:8080} \
		-e BENCH_DURATION_SECONDS=$${BENCH_DURATION_SECONDS:-15} \
		-e BENCH_TIMEOUT_SECONDS=$${BENCH_TIMEOUT_SECONDS:-2} \
		-e BENCH_WRITER_CONCURRENCY=$${BENCH_WRITER_CONCURRENCY:-10} \
		-e BENCH_READER_CONCURRENCY=$${BENCH_READER_CONCURRENCY:-60} \
		-e BENCH_CELEBRITY_CONCURRENCY=$${BENCH_CELEBRITY_CONCURRENCY:-30} \
		-e BENCH_CELEBRITY_POOL_SIZE=$${BENCH_CELEBRITY_POOL_SIZE:-5} \
		-e BENCH_WARMUP_URLS=$${BENCH_WARMUP_URLS:-200} \
		-v "$$(pwd)":/work -w /work python:3.12-slim bash -lc \
		"pip install --no-cache-dir httpx==0.26.0 >/dev/null && python scripts/bench_http.py"

# Coding standards check: verifies Pydantic model usage, naming patterns, and no loose dicts
# Runs inside Docker — no local installs required.
standards-check:
	@docker run --rm -v "$$(pwd)":/work -w /work python:3.12-slim bash -lc \
		"pip install --no-cache-dir ruff==0.3.0 >/dev/null && \
		 ruff check app/ services/ scripts/ \
		   --select=E,W,F,UP,B,C4,SIM,RUF \
		   --ignore=B008,UP011,E501,W293 \
		   --output-format=concise"
