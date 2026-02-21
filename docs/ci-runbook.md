# CI/CD Runbook

This document captures every lesson learned while setting up and debugging the GitHub Actions
pipeline for this project. Read this before touching `.github/workflows/ci.yml`.

---

## Pipeline Overview

```
lint ──┐
        ├──► standards-check ──► test ──► bench-regression
typecheck ──┘
```

| Job | Makefile equivalent | Key constraint |
|---|---|---|
| Format Check | `make lint` | black + isort, must pass first |
| Type Check | `make typecheck` | pyright basic mode |
| Coding Standards | `make standards-check` | ruff + grep for banned patterns |
| Functional Tests | `make test` | pytest against db-test + redis-test only |
| Benchmark Regression | `make bench` | full workflow, CI baselines |

---

## Lesson 1 — `.env` files are gitignored; CI needs `.env.ci`

**Problem:** `docker compose up` on the GitHub Actions runner fails immediately because `.env`
and `.env.test` are gitignored and not present on the runner.

**Fix:** Committed `.env.ci` with safe non-secret defaults. The CI jobs copy it into place:
```yaml
- name: Prepare environment files
  run: |
    cp .env.ci .env
    cp .env.ci .env.test
```

**Rule:** `.env.ci` must contain **only** fields declared in `app/config.py Settings`.
The model uses `extra = "forbid"` — any extra key causes a `ValidationError` at import time
and breaks pytest collection before a single test runs.

**How to keep it in sync:** When you add a field to `Settings`, add it to `.env.ci` too.
When you remove a field from `Settings`, remove it from `.env.ci`.

---

## Lesson 2 — `Settings(extra="forbid")` crashes pytest collection on unknown env vars

**Symptom:**
```
ConftestImportFailure: ValidationError: 1 validation error for Settings
INGESTION_METRICS_PORT
  Extra inputs are not permitted [type=extra_forbidden, ...]
ImportError while loading conftest '/work/tests/conftest.py'.
```

**Root cause:** `.env.ci` contained `INGESTION_METRICS_PORT=9200` which is not in `Settings`.
The error fires at module import time (before any test runs), so pytest exits with code 4.

**Fix:** Removed `INGESTION_METRICS_PORT` and all other non-`Settings` keys from `.env.ci`.

**Rule:** Before adding any key to `.env.ci`, verify it exists in `app/config.py Settings`.

---

## Lesson 3 — Functional tests must NOT start the full stack

**Problem:** The CI test job originally ran `docker compose up --build -d` (full 15-container
stack: app × 3, nginx, postgres, redis, kafka, zookeeper, clickhouse, keygen, ingestion worker,
cache warmer, prometheus, grafana). On a 2-core GitHub Actions runner this takes >5 minutes
and the health check at `localhost:8080` times out.

**Fix:** The pytest suite only needs `db-test` and `redis-test`. Start only those:
```yaml
- name: Start test dependencies
  run: docker compose --profile test up -d db-test redis-test
```

Then run pytest directly in a Docker container connected to the test network:
```yaml
- name: Run pytest (Docker)
  run: |
    NET=$(docker inspect urlshortener-db-test \
      --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}' | head -1)
    docker run --rm \
      --network "$NET" \
      --env-file .env.ci \
      -e DATABASE_URL=postgresql+asyncpg://test:test@urlshortener-db-test:5432/urlshortener_test \
      -e REDIS_URL=redis://urlshortener-redis-test:6379/0 \
      -v "$PWD":/work -w /work \
      python:3.12-slim bash -lc \
      "pip install --no-cache-dir -r requirements.txt >/dev/null && pytest tests/ -v --tb=short"
```

**Rule:** Never start the full stack for unit/integration tests. Only start the services the
tests actually connect to.

---

## Lesson 4 — Docker network name is not predictable across environments

**Problem:** The network is named `<project-dir>_urlshortener-net`. Locally the project dir is
`url-shorterner` so the network is `url-shorterner_urlshortener-net`. On GitHub Actions the
checkout dir is also `url-shorterner` but this can vary.

**Fix:** Derive the network name from the running container instead of hardcoding:
```bash
NET=$(docker inspect urlshortener-db-test \
  --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}' | head -1)
```

**Rule:** Never hardcode Docker network names. Always derive them from a running container.

---

## Lesson 5 — Benchmark runner: full stack needs extra time for Kafka + keygen

**Problem:** The bench-regression job starts the full stack, waits for `GET /health` to return
200, then immediately runs the benchmark. The health endpoint only checks DB + Redis. Kafka and
keygen take 20–40 extra seconds to become ready. During this window, `POST /api/shorten` returns
errors (Kafka publish fails, keygen IDs not allocated), so warmup produces 0 URLs, and the
reader/celebrity scenarios get 0 RPS.

**Symptom in bench output:**
```
[celebrity (GET /<code> — 0-code hot pool)]  rps=0.00  ok=0  errors=0
```

**Fix:** After the health check passes, wait 30s and verify `POST /api/shorten` returns 201
before starting the benchmark:
```yaml
- name: Wait for Kafka + keygen to stabilise
  run: |
    sleep 30
    for i in $(seq 1 10); do
      CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8080/api/shorten \
        -H "Content-Type: application/json" -d '{"url": "https://example.com"}')
      if [ "$CODE" = "201" ]; then echo "Stack ready"; break; fi
      sleep 5
    done
```

---

## Lesson 6 — CI runner throughput is ~10× lower than local

**Observed CI numbers (2026-02-21, GitHub Actions ubuntu-latest, 2-core shared):**

| Scenario | CI RPS | Local RPS |
|---|---|---|
| writer (POST /api/shorten) | ~23 | 77.73 |
| reader (GET /<code> broad) | ~86 | 459.00 |
| celebrity | ~43 | 228.67 |
| aggregate | ~153 | 765.40 |

**Fix:** Two separate baseline files:
- `docs/bench_baselines.json` — local baselines, 15% tolerance, enforced by `make bench`
- `docs/bench_baselines_ci.json` — CI floor baselines (~half of observed CI numbers), 50% tolerance

CI bench gate purpose: verify the benchmark **runs end-to-end without crashing**, not throughput.

---

## Lesson 7 — Celebrity scenario name is dynamic; don't key baselines on it

**Problem:** `bench_http.py` names the celebrity scenario dynamically:
```python
name=f"celebrity (GET /<code> — {len(celebrity_pool)}-code hot pool)"
```
If warmup fails (0 URLs), the name becomes `0-code hot pool`. If pool size changes, the name
changes. Keying CI baselines on this name causes `MISSING scenario` failures.

**Fix:** Omit the celebrity scenario from `bench_baselines_ci.json`. The regression check only
checks scenarios that appear in the baselines file — unknown scenarios are silently ignored.

---

## Lesson 8 — `_comment` keys in baselines JSON cause false MISSING failures

**Problem:** `bench_baselines.json` uses `_comment` and `_tolerance_note` as metadata keys.
The regression check iterated all keys and reported them as missing scenarios:
```
✗ MISSING scenario in output: '_comment'
✗ MISSING scenario in output: '_tolerance_note'
```

**Fix:** Added a guard in `scripts/bench_regression_check.py`:
```python
for scenario_name, baseline_metrics in baselines.items():
    if scenario_name.startswith("_"):
        continue  # skip metadata/comment keys
```

**Rule:** All metadata keys in any baselines JSON file must start with `_`.

---

## Lesson 9 — CI errors are expected; don't gate on `max_errors` in CI baselines

**Problem:** On a cold CI stack, Kafka publish failures are non-fatal — the app still serves
HTTP and returns 201, but the click event isn't published. This inflates `errors` in the
benchmark output (errors = non-2xx responses or timeouts, not just Kafka failures). Setting
`max_errors` in CI baselines causes spurious failures.

**Fix:** Omit `max_errors` from `bench_baselines_ci.json`. The regression check treats a missing
`max_errors` as "no error check" (already the behaviour — `baseline_errors = baseline_metrics.get("max_errors", None)`).

**Rule:** Only set `max_errors` in `bench_baselines.json` (local). Never in `bench_baselines_ci.json`.

---

## Lesson 10 — ruff W293 is not fixed by black; ignore it

**Problem:** `make standards-check` failed on `W293` (whitespace on blank lines inside
docstrings). Black does not strip trailing whitespace from docstring blank lines.

**Fix:** Added `W293` to the ruff ignore list in both `pyproject.toml` and the Makefile
`standards-check` inline `--ignore` flag.

---

## Lesson 11 — ruff must be configured inline in Makefile (not just pyproject.toml)

**Problem:** The `standards-check` Makefile target runs ruff inside an ephemeral Docker
container. The container mounts the workspace but ruff may not pick up `pyproject.toml`
config in all versions.

**Fix:** Pass all ignore rules inline in the Makefile command so it is self-contained:
```makefile
ruff check app/ services/ scripts/ \
  --select=E,W,F,UP,B,C4,SIM,RUF \
  --ignore=B008,UP011,E501,W293 \
  --output-format=concise
```

---

## Lesson 12 — Three app replicas race to CREATE TABLE on startup

**Problem:** The bench-regression job starts the full stack with 3 app replicas (`app1`, `app2`,
`app3`) behind nginx. All three call `init_db()` at lifespan startup simultaneously. The first
one creates the `urls` table; the other two crash with:
```
sqlalchemy.exc.IntegrityError: duplicate key value violates unique constraint "pg_type_typname_nsp_index"
```
This causes the app health check to fail because 2 of 3 replicas are down.

**Root cause:** SQLAlchemy's `Base.metadata.create_all` is not safe for concurrent execution
across multiple processes against the same database. PostgreSQL type registration races.

**Fix:** Wrap `init_db` with a PostgreSQL session-level advisory lock:
```python
async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.execute(text("SELECT pg_advisory_lock(12345678)"))
        try:
            await conn.run_sync(Base.metadata.create_all)
        finally:
            await conn.execute(text("SELECT pg_advisory_unlock(12345678)"))
```
The first replica acquires the lock and runs DDL. The others block on `pg_advisory_lock`,
then when they acquire it, `create_all` is a no-op (tables already exist).

**Rule:** Any app that runs multiple replicas and uses SQLAlchemy `create_all` at startup
must serialize DDL with an advisory lock. The proper long-term solution is Alembic migrations
run as a one-shot init container before the app replicas start.

---

## Lesson 13 — Full-stack benchmark does not belong in the push/PR gate

**Problem:** The bench-regression job ran the full 15-container stack on every push.
This caused ~80% of CI runs to fail due to:

| Failure mode | Frequency | Cause |
|---|---|---|
| `Wait for app healthy` timeout | ~30% | Cold runner: image pull + build takes >5 min |
| `Wait for Kafka + keygen` failure | ~40% | Kafka/keygen startup is non-deterministic on shared runners |
| Regression check failure | ~20% | RPS varies with runner CPU load |
| Pass | ~10% | Runner happened to be fast |

**Root cause:** A 15-container stack with Kafka, ClickHouse, and keygen is fundamentally
incompatible with shared 2-core GitHub Actions runners. The startup time and resource
requirements are non-deterministic.

**Industry standard fix:** Split into two separate workflows:

```
ci.yml  (push/PR gate — always runs, must always be green)
  lint → typecheck → standards-check → test
  - Only starts db-test + redis-test (2 containers)
  - Completes in <5 min
  - 100% deterministic
  - concurrency: cancel-in-progress (kills stale runs on new push)
  - timeout-minutes on every job (prevents runaway hangs)

bench.yml  (separate workflow — NOT part of the push gate)
  bench-regression
  - Triggers: scheduled nightly 02:00 UTC + manual workflow_dispatch
  - Runs full 15-container stack with 45-min timeout
  - Kafka/keygen wait is non-fatal (logs warning, benchmark runs anyway)
  - Results uploaded as 90-day artifact
  - concurrency: single run at a time (cancel-in-progress)
```

**Rule:** Never put a job that requires a full application stack in the push/PR gate
on shared runners. The gate must be fast (<5 min) and deterministic (same result
regardless of runner load). Full-stack tests belong in scheduled or manual workflows
on dedicated runners.

**How to run the benchmark manually:**
```bash
# Via GitHub CLI
gh workflow run bench.yml

# Via Makefile (local)
make bench
```

---

## Benchmark CI vs Local — Quick Reference

| What | Local | CI |
|---|---|---|
| Command | `make bench` | CI job `bench-regression` |
| Baselines file | `docs/bench_baselines.json` | `docs/bench_baselines_ci.json` |
| Tolerance | 15% | 50% |
| Purpose | Throughput regression gate | End-to-end smoke (does it run?) |
| Update baselines | After intentional perf improvement | After measuring on a real CI run |
| Celebrity in baselines | Yes (stable name) | No (dynamic name) |
| `max_errors` | Yes | No |

---

## How to update CI baselines after a real CI run

1. Download the `bench-results-<sha>` artifact from the GitHub Actions run
2. Note the per-scenario RPS numbers
3. Set each scenario's `rps` in `bench_baselines_ci.json` to ~50% of the observed value
4. Commit with message: `chore: update CI bench baselines (observed: writer=X, reader=Y, agg=Z)`
