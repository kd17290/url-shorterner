---
description: Coding standards and practices to follow for all code changes in this project
auto_execution_mode: 3
---

# Coding Standards & Practices

These are the enforced coding standards for this codebase. Follow them strictly for all code changes — new files, refactors, and reviews.

---

## Non-Negotiable Principles

These override everything else. No exceptions.

### Do Not Deviate

- Follow these rules **exactly as written** — do not bend, skip, or "improve" them.
- If a rule feels wrong for a specific case, **stop and ask** — never silently deviate.
- Do not introduce patterns, conventions, or structures not covered by these rules without explicit approval.
- Every code change must be traceable to one or more rules in this document.

### Do Not Assume

- **Never assume** intent, requirements, types, return values, or behaviour.
- If something is unclear — a function's return type, a parameter's purpose, a field's usage — **read the code or ask**.
- Do not guess what a variable contains. Read the source. Verify with the codebase.
- Do not assume a file is "fine" without reading it. Do not assume a fix is correct without verifying.
- If you cannot verify something, say so explicitly — do not proceed on assumptions.

---

# Part 1 — Everyday Rules (apply to every line of code)

These are the most frequently encountered rules. Every developer touches these on every commit.

---

## 1. Type Annotations & Static Analysis

- Every function must have a **return type annotation**.
- Every parameter must have a **type annotation** — no untyped `def foo(x):`.
- Use `X | None` union syntax (Python 3.10+), **not** `Optional[X]`.
- Use `dict[str, object]` **not** `dict[str, Any]` — avoid `Any` entirely.
- All code must pass **pyright** in `basic` mode at minimum.
- Prefer `"ClassName"` string forward references over `from __future__ import annotations`.

```python
# BAD
def run(self, steps) -> list:
def process(data: Any) -> Optional[dict]:

# GOOD
def run(self, nodes: Sequence[TaskNode]) -> list[TaskResult]:
def process(data: dict[str, object]) -> TaskMarker | None:
```

## 2. Formatting — Black, PEP 8, isort

All code must be **black**-formatted and **isort**-sorted.

- **Line length**: 120 characters max.
- **Indentation**: 4 spaces, no tabs.
- **Blank lines**: 2 before top-level definitions, 1 between methods.
- **Trailing whitespace**: none.
- **Trailing commas**: always on multi-line structures.
- **String quotes**: double quotes `"` (black default).
- **Boolean checks**: `if items:` not `if len(items) > 0:`.
- **Import order**: `STDLIB → THIRDPARTY → FIRSTPARTY → LOCALFOLDER`, separated by blank lines.
- **Import style**: `from X import Y`, not `import X` when accessing specific names.
- Imports always at the **top of the file** — never in the middle of code.
- Do not fight black — if black reformats something, accept it.

```toml
[tool.black]
line-length = 120
target-version = ["py311"]

[tool.isort]
profile = "black"
line_length = 120

[tool.pyright]
pythonVersion = "3.11"
typeCheckingMode = "basic"
reportMissingTypeStubs = false
reportUnusedImport = true
reportUnusedVariable = true
```

## 3. Identity Checks (PEP 8) & Enums

- Use `is None` / `is not None` instead of `== None` / `!= None`.
- Use `is` for enum comparisons.

### Enum Usage for Status Fields

- **Never** use string literals for status fields (`"healthy"`, `"unhealthy"`, `"pending"`, `"failed"`).
- **Always** define enums with explicit values and use them throughout the codebase.
- Enums provide type safety, IDE autocomplete, and prevent typos.

```python
# BAD — string literals
status = "healthy"
if status == "healthy":  # typo-prone, no type safety

# GOOD — enum with explicit values
from enum import StrEnum

class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"

class ServiceStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

status = HealthStatus.HEALTHY
if status is HealthStatus.HEALTHY:  # type-safe, typo-proof
```

- Use `StrEnum` (Python 3.11+) for enums that serialize to JSON.
- Add `@classmethod def from_str(cls, value: str) -> Self:` for safe parsing from external sources.
- Include `__all__` exports for all public enums.

```python
# BAD
if outcome == LockOutcome.ACQUIRED:
if value == None:

# GOOD
if outcome is LockOutcome.ACQUIRED:
if value is None:
```

## 4. Naming Conventions

- Variable names must accurately describe what they hold.
  - `lock_handle` not `file_descriptor` (for a file object, not an int fd).
  - `error_detail` not `error_msg` (when the value can be `None`).
- Prefer descriptive boolean names: `is_bigquery`, `is_completed`, `is_succeeded`.
- Use `_UPPER_SNAKE` for module-level private constants.
- Step names use `snake_case` with colon separators for parameterized names: `"create_master_parquet_files:schema.table"`.

## 5. Error Handling

- **Never** silently swallow exceptions — at minimum log a warning with `exc_info=True`.
- Catch specific exceptions (`FileNotFoundError`) before broad ones.
- Use `finally` blocks for resource cleanup (DuckDB connections, file locks).

```python
# BAD
except Exception:
    return None

# GOOD
except Exception:
    _logger.warning("Failed to read marker file %s", path, exc_info=True)
    return None
```

## 6. Dead Code Removal

- **Always** remove dead code — unused classes, methods, parameters, imports, variables.
- Do not comment out code "for later" — use version control.
- If a parameter is no longer used, remove it from the signature.
- If a class is no longer instantiated, delete it.
- If an import is unused, remove it.
- Run `pyright` with `reportUnusedImport` and `reportUnusedVariable` enabled.

```python
# BAD — dead parameter kept "just in case"
async def create_config_parquet_files(connection_params=None):
    # connection_params is never used
    ...

# GOOD — remove it
async def create_config_parquet_files():
    ...
```

## 7. DRY — Don't Repeat Yourself

- Deduplicate identical code paths (e.g. duration calculation in try/except — compute once after).
- Remove redundant response fields that always hold the same value as another field.
- Use shared helpers for repeated patterns.

## 8. Docstrings & Module Documentation

### Method and Class Docstrings

- All public classes and methods must have docstrings.
- Use reStructuredText-style with `Args:`, `Returns:`, `Raises:` sections.
- Do **not** add or remove comments/docstrings unless explicitly asked.

### Module-Level Documentation (mandatory for every new module)

Every module must have a comprehensive docstring at the top that enables a new developer to understand the module **without reading the implementation**. Include all of the following:

1. **Summary** — one-paragraph description of what the module does and why it exists.

2. **ASCII Flow Diagram** — visual representation of the primary execution flow (decision points, branches, outcomes). Use box-drawing characters (`┌ ─ ┐ │ └ ┘ ▼ ▶ ┬ ┴ ┼`).

3. **File / Data Layout** — if the module creates or reads files, show the directory structure.

4. **Class Relationship Diagram** — ASCII diagram showing classes, their fields, and how they relate (owns, yields, accepts, returns).

5. **How to Use** — step-by-step numbered guide with **runnable code examples** for every public entry point:
   - How to **create/instantiate** the main class.
   - How to **call each public method** and handle every possible outcome.
   - How to **handle errors** (success path, failure path, unhandled exception path).
   - How to **read status/results** after the fact.

6. **Pluggability / Reuse** — if the module is generic (not tied to one feature):
   - Explicitly state it is reusable.
   - Show a second example with a **different use case** to prove it.
   - Show how to **plug in a custom implementation** of any protocol/interface.

7. **Key Behaviours** — bullet list of non-obvious runtime behaviours (e.g. "exceptions are captured, not propagated", "lock is held for the lifetime of the context").

8. **Classes list** — one-line summary of each class in the module.

```python
# Example module docstring structure:
\"""One-line summary.

Longer description of what this module does.

Flow Diagram — ``main_method()``
=================================
::
    ┌─────────┐
    │  Start  │
    └────┬────┘
         ▼
    ...

How to Use
===========
**Step 1 — Create**::
    obj = MyClass.create(...)

**Step 2 — Use**::
    with obj.do_thing() as result:
        ...

Reuse for Any Task
===================
This module is not tied to X. Example::
    ...

Key Behaviours
===============
- Behaviour 1.
- Behaviour 2.

Classes:
    MyClass:  Does X.
    MyResult: Holds Y.
\"""
```

---

# Part 2 — Structural Rules (apply when writing classes, functions, and data models)

---

## 9. Fully Typed Structures — No Loose Dicts, No Loose Lists

- **Never** use raw `dict[str, Any]`, `dict[str, object]`, or `list[list[object]]` as function arguments, return values, or **internal variables** when the schema is predictable.
- If a payload, message, row, or aggregation state has a **predictable schema** — represent it as a **Pydantic model** (for runtime-validated, serializable data) or a **frozen slotted dataclass** (for pure value objects with no serialization).
- This rule applies to **every layer**: Kafka messages, Redis cache payloads, analytics rows, aggregation state, internal accumulators, and function-local variables.
- Use `model_validate()` at the boundary (deserialization entry point) and `model_dump(mode="json")` at the exit point (serialization). Never scatter field access across the codebase.

### When to use Pydantic vs dataclass

| Situation | Use |
|---|---|
| Kafka message payload (serialized/deserialized) | `BaseModel` |
| Redis cache payload (JSON in/out) | `BaseModel` |
| Analytics row for ClickHouse insert | `BaseModel` |
| Aggregation accumulator passed between functions | `BaseModel` |
| Pure value object, no serialization needed | `@dataclass(frozen=True, slots=True)` |
| API request/response schema | `BaseModel` |

### Pydantic model rules

- Define models **once**, in a shared location (`app/schemas.py` for cross-service models, or at the top of the module for module-private models).
- Use `Field(...)` with `description=` and `examples=` for every non-obvious field.
- Use `model_config = {"from_attributes": True}` when the model is populated from ORM objects.
- Use `@property` on models for derived values (e.g. `total_deltas`).
- **Never** duplicate field definitions — if two modules need the same shape, import the shared model.

```python
# BAD — loose dict passed between functions
async def _buffer_batch(batch: list[dict[str, str | int]]) -> bool:
    aggregated: dict[str, int] = defaultdict(int)
    for payload in batch:
        short_code = payload.get("short_code")   # no type safety, no validation
        delta = int(payload.get("delta", 1))
        aggregated[str(short_code)] += delta

# BAD — loose list for analytics rows
analytics_rows: list[list[object]] = []
analytics_rows.append([short_code, delta, datetime.utcnow()])

# GOOD — Pydantic model for every predictable schema
class ClickEvent(BaseModel):
    """Kafka click event payload, keyed by short_code for partition affinity."""
    short_code: str = Field(..., description="Short code being clicked")
    delta: int = Field(1, description="Click increment, typically 1", ge=1)

class ClickAggregates(BaseModel):
    """Aggregated click deltas grouped by short_code, ready to flush."""
    by_short_code: dict[str, int] = Field(default_factory=dict)

    @property
    def total_deltas(self) -> int:
        return sum(self.by_short_code.values())

class ClickHouseClickEventRow(BaseModel):
    """One analytics row for ClickHouse click_events table."""
    short_code: str
    delta: int
    event_time: datetime.datetime

# GOOD — typed function signatures using models
async def _buffer_batch(client: AsyncRedis, batch: list[ClickEvent]) -> bool:
    aggregates = ClickAggregates()
    for click_event in batch:
        aggregates.by_short_code[click_event.short_code] = (
            aggregates.by_short_code.get(click_event.short_code, 0) + click_event.delta
        )
    ...

async def _process_batch(
    client: AsyncRedis,
    clickhouse_client: ClickHouseClient,
    aggregated: ClickAggregates,       # NOT dict[str, int]
) -> None:
    analytics_rows: list[ClickHouseClickEventRow] = [
        ClickHouseClickEventRow(
            short_code=short_code,
            delta=delta,
            event_time=datetime.datetime.utcnow(),
        )
        for short_code, delta in aggregated.by_short_code.items()
    ]
    ...
    clickhouse_client.insert(
        data=[[row.short_code, row.delta, row.event_time] for row in analytics_rows],
        ...
    )
```

### Shared model location rule

- Models shared between **two or more services** (e.g. app + ingestion worker) live in `app/schemas.py`.
- Models used only within a single module are defined at the **top of that module**, above all functions.
- Never define the same shape twice — always import from the canonical location.

```python
# app/schemas.py — canonical shared models
class ClickEvent(BaseModel): ...
class CachedURLPayload(BaseModel): ...

# services/ingestion/worker.py — imports shared model, defines module-private models
from app.schemas import ClickEvent

class ClickAggregates(BaseModel): ...       # ingestion-private
class ClickHouseClickEventRow(BaseModel): ...  # ingestion-private
```

### Boundary validation rule

- **Deserialize at the entry point** — validate incoming data (Kafka record, Redis hash, HTTP body) into a Pydantic model immediately on receipt. Never pass raw dicts downstream.
- **Serialize at the exit point** — call `model_dump(mode="json")` only when writing to an external system (Kafka, Redis, HTTP response).
- Log a warning and skip the record on validation failure — never crash the consumer loop.

```python
# GOOD — validate at Kafka consumer boundary
for record in topic_partition_records:
    try:
        batch.append(ClickEvent.model_validate(record.value))
    except Exception:
        logger.warning("invalid kafka click payload", exc_info=True)

# GOOD — validate at Redis stream boundary
for message_id, payload in messages:
    try:
        fallback_batch.append(ClickEvent.model_validate(payload))
    except Exception:
        logger.warning("invalid fallback click payload", exc_info=True)

# GOOD — serialize at Kafka producer boundary
payload = ClickEvent(short_code=short_code, delta=delta).model_dump(mode="json")
await producer.send_and_wait(topic, payload, key=short_code.encode())
```

### Cache payload rule

- Redis cache values must always be serialized from and deserialized into a **named Pydantic model** — never hand-rolled dicts with `.isoformat()` scattered across callers.
- The model must be shared between the writer (app/service.py) and the reader (cache warmer, redirect handler).

```python
# BAD — hand-rolled dict in _cache_url
data = {
    "id": url.id,
    "short_code": url.short_code,
    "created_at": url.created_at.isoformat() if url.created_at else None,
    ...
}
await cache.set(key, json.dumps(data))

# GOOD — shared Pydantic model
payload = CachedURLPayload.model_validate(url)
await cache.set(key, json.dumps(payload.model_dump(mode="json")))
```

## 10. Frozen Slotted Dataclasses

- All value-object dataclasses must use `@dataclass(frozen=True, slots=True)`.
- Mutable dataclasses (e.g. `LockResult`) use `@dataclass(slots=True)` without frozen.
- Private fields use `field(default=..., init=False, repr=False)`.

```python
@dataclass(frozen=True, slots=True)
class TaskMarker:
    started_at: float
    completed_at: float | None = None
```

## 11. No Loosely Structured Arguments

- **Never** pass `*args`, `**kwargs`, or `dict[str, str | float | None]` style arguments.
- Every parameter must be explicitly typed with a named field.
- Use the bare `*` **keyword-only separator** for methods with optional or defaulted parameters. This forces callers to pass them by name, making call sites self-documenting and safe against future parameter additions.
- Do **not** use `*` when all parameters are required and obvious — it adds noise without benefit.

```python
# BAD — loosely structured
def complete(self, **kwargs): ...

# BAD — optional param without keyword-only enforcement
def audit_trail(self, last_n: int | None = None): ...
# allows: guard.audit_trail(5)  — unclear what 5 means

# GOOD — keyword-only for optional/defaulted params
def complete(self, *, error: str | None = None) -> None: ...
def audit_trail(self, *, last_n: int | None = None) -> list[AuditEntry]: ...
# forces: guard.audit_trail(last_n=5)  — self-documenting

# GOOD — no * needed, required params are obvious
def __init__(self, paths: LockPaths, ttl_seconds: int) -> None: ...
```

## 12. Class-Based Approach Over Standalone Functions

- **Prefer classes** over standalone/static functions for any logic with state, configuration, or lifecycle.
- Group related operations into a class with clear responsibilities.
- Use `__init__` for dependency injection and configuration.
- Standalone functions are acceptable **only** for:
  - Pure utility functions with no state (e.g. `_to_dict()`).
  - Module-level constants/helpers (e.g. `_noop()`).
  - Factory functions that return class instances.

```python
# BAD — scattered standalone functions
async def run_parquet_build():
    guard = create_guard()
    runner = create_runner()
    ...

# GOOD — class with injected dependencies
class ParquetBuildService:
    def __init__(self) -> None:
        self._lock = IdempotentProcessLock.create(...)
        self._executor = AsyncTaskGraphExecutor(logger)

    async def run(self) -> ParquetBuildResponse:
        ...
```

- **Static methods** (`@staticmethod`) are acceptable for operations that logically belong to a class but don't need instance state.
- **Class methods** (`@classmethod`) are for factory construction (`create()`, `from_raw()`).

## 13. Read-Only Properties Over Private Field Access

- **Never** access `_private` fields from outside the owning class.
- Expose read-only `@property` methods instead.

```python
# BAD (in another class)
succeeded = guard_result._completed and guard_result._error is None

# GOOD
@property
def is_succeeded(self) -> bool:
    return self._completed and self._error is None

# Then use:
succeeded = guard_result.is_succeeded
```

## 14. Co-located Serialization

- `to_json_dict()` and `from_json_dict()` belong **on the dataclass itself**, not scattered in callers.
- Use a shared `_to_dict()` helper using `dataclasses.fields()` to DRY up serialization across multiple dataclasses.

```python
def _to_dict(obj: object) -> dict[str, object]:
    return {
        f.name: getattr(obj, f.name)
        for f in fields(obj)
        if getattr(obj, f.name) is not None
    }
```

## 15. Maximum Assertions for Defensive Programming

**Assert aggressively.** Every method should guard against bad inputs, bad state, and bad outcomes. If something *can* go wrong, assert that it hasn't.

### Where to assert

- **Method entry** — validate every parameter's type, non-emptiness, and range.
- **After construction** — validate that created objects are in a valid state.
- **Before use** — validate that a value is not `None` before passing it downstream.
- **After external calls** — validate return types and lengths from other modules.
- **Post-conditions** — validate that side effects happened (e.g. directory was created, list is non-empty).
- **Invariants** — validate assumptions that must hold at critical decision points.

### What to assert

- `isinstance` checks for parameter types.
- Non-empty strings: `assert name, "name must not be empty"`.
- Positive numbers: `assert ttl > 0, f"ttl must be positive, got {ttl}"`.
- Non-None values: `assert result is not None, "result must not be None"`.
- Collection lengths: `assert len(results) == len(steps)`.
- Enum membership: `assert outcome is LockOutcome.ACQUIRED`.
- Timing sanity: `assert now >= started_at`.

### Every assert must have a message

- **Never** write a bare `assert x` — always include a descriptive f-string message.
- The message should state what was expected and what was received.

```python
# BAD
assert paths
assert ttl_seconds > 0

# GOOD
def __init__(self, paths: LockPaths, ttl_seconds: int) -> None:
    assert isinstance(paths, LockPaths), f"paths must be LockPaths, got {type(paths).__name__}"
    assert isinstance(ttl_seconds, int) and ttl_seconds > 0, f"ttl_seconds must be a positive int, got {ttl_seconds!r}"

# After external call
results = await self._runner.run(steps)
assert len(results) == len(steps), f"results count ({len(results)}) must match steps count ({len(steps)})"

# Before downstream use
assert guard_result.started_at is not None, "started_at must be set for ACQUIRED"

# Post-condition
os.makedirs(lock_dir, exist_ok=True)
assert os.path.isdir(lock_dir), f"Lock dir was not created: {lock_dir}"
```

## 16. Module-Level Constants and `__all__`

- Move reusable items (like `_noop` coroutines) to module level — don't recreate per call.
- Add `__all__` to define explicit public API.

```python
__all__ = ["IdempotentProcessLock", "LockResult", "LockOutcome"]

_TTL_SECONDS: int = 120

async def _noop() -> None:
    """No-op coroutine used as a barrier step."""
```

## 17. No Over-Engineering

- Don't add unnecessary wrapper classes — fold methods into the caller if they serve no independent purpose.
- Keep class hierarchies flat.
- Remove unnecessary `list()` wrapping (e.g. `len(list(some_set))` → `len(some_set)`).

---

# Part 3 — Architectural Rules (apply when designing systems and modules)

---

## 18. SOLID Principles

Apply SOLID to a pragmatic extent — don't over-abstract, but don't violate these either.

### S — Single Responsibility Principle

- Each class has **one reason to change**.
- `IdempotentProcessLock` handles locking + TTL + markers — not pipeline execution.
- `AsyncTaskGraphExecutor` handles task execution — not task definition.
- `ParquetBuildService` orchestrates — not implements individual steps.

### O — Open/Closed Principle

- Classes should be **open for extension, closed for modification**.
- Use `typing.Protocol` so new logger implementations don't require changing the runner.
- Use factory classmethods so construction logic can be overridden in subclasses.
- Add new task types by creating new `TaskNode` instances, not modifying the executor.

### L — Liskov Substitution Principle

- Any implementation of a `Protocol` must be fully substitutable.
- If `StepLogger` requires `info()`, `error()`, `exception()` — every implementation must support all three.

### I — Interface Segregation Principle

- Keep protocols **small and focused**.
- `StepLogger` has 3 methods, not 20 — callers only depend on what they use.
- Don't force classes to implement methods they don't need.

```python
# BAD — fat interface
class Logger(Protocol):
    def info(self, msg: str) -> None: ...
    def debug(self, msg: str) -> None: ...
    def warning(self, msg: str) -> None: ...
    def error(self, msg: str) -> None: ...
    def critical(self, msg: str) -> None: ...
    def exception(self, msg: str) -> None: ...
    def set_level(self, level: int) -> None: ...

# GOOD — minimal interface for what the runner actually needs
class StepLogger(Protocol):
    def info(self, msg: str, /) -> None: ...
    def error(self, msg: str, /) -> None: ...
    def exception(self, msg: str, /) -> None: ...
```

### D — Dependency Inversion Principle

- High-level modules should not depend on low-level modules — both depend on abstractions.
- `AsyncTaskGraphExecutor` depends on `TaskLogger` protocol, not on a concrete logger class.
- `ParquetBuildService` accepts an executor, not a specific execution strategy.

## 19. Pluggable Design

- Use `typing.Protocol` for dependency injection (not abstract base classes).
- Accept interfaces, not implementations.
- Factory classmethods (`create()`) for complex construction with validation.

```python
@runtime_checkable
class StepLogger(Protocol):
    def info(self, msg: str, /) -> None: ...
    def error(self, msg: str, /) -> None: ...
    def exception(self, msg: str, /) -> None: ...
```

## 20. Context Managers for Lifecycle

- Use context managers for lock acquisition, TTL gating, and resource management.
- The `finally` block handles cleanup (lock release, marker writes, audit appends).
- Callers signal completion via `result.complete()` — if not called, the guard auto-marks failure.

## 21. Performance-Conscious Design

- Use `collections.deque(maxlen=n)` instead of loading entire files then slicing.
- Use `any()` for early failure detection instead of building full lists first.
- Move instantiations to `__init__` when the object is reused across calls.

```python
# BAD
if len([r for r in results if not r.ok]) > 0:

# GOOD
if any(not r.ok for r in results):
```

### Redis pipelining rule

- **Never** issue multiple Redis commands in a loop with individual `await` calls when they can be batched.
- Use `client.pipeline(transaction=False)` for independent writes (e.g. warming N cache keys).
- Use `client.pipeline(transaction=True)` only when atomicity is required (e.g. decrement buffer + invalidate cache key together).
- Always `await pipe.execute()` once at the end — never inside the loop.

```python
# BAD — N round-trips
for short_code, delta in aggregated.by_short_code.items():
    await client.hincrby(key, short_code, delta)   # one round-trip per code

# GOOD — 1 round-trip
pipe = client.pipeline(transaction=False)
for short_code, delta in aggregated.by_short_code.items():
    pipe.hincrby(key, short_code, delta)
await pipe.execute()
```

### Batching rule

- Consumer loops must accumulate records into a typed batch (`list[ClickEvent]`) before processing — never process one record at a time.
- Flush the batch on a **time interval** (`INGESTION_FLUSH_INTERVAL_SECONDS`) or **size threshold** (`INGESTION_BATCH_SIZE`), whichever comes first.
- Use `consumer.getmany(max_records=N)` (not `getone()`) to pull a full batch per iteration.

```python
# BAD — one record at a time
async for record in consumer:
    await _process_single(record.value)

# GOOD — batch per iteration, flush on interval
records = await consumer.getmany(
    timeout_ms=settings.INGESTION_BLOCK_MS,
    max_records=settings.INGESTION_BATCH_SIZE,
)
batch: list[ClickEvent] = []
for topic_partition_records in records.values():
    for record in topic_partition_records:
        try:
            batch.append(ClickEvent.model_validate(record.value))
        except Exception:
            logger.warning("invalid kafka click payload", exc_info=True)
if batch:
    await _buffer_batch_to_redis(client, batch)
```

### Kafka partition affinity rule

- Kafka messages with a **shared aggregation key** (e.g. `short_code`) must be sent with that key as the Kafka message key.
- This guarantees all events for the same key land on the same partition and are consumed by the same worker — enabling correct per-key aggregation without distributed locking.

```python
# GOOD — partition by short_code so all clicks for one URL go to one consumer
payload = ClickEvent(short_code=short_code, delta=delta).model_dump(mode="json")
await producer.send_and_wait(
    topic,
    payload,
    key=short_code.encode("utf-8"),   # partition affinity
)
```

### Hot-key / celebrity traffic rule

- Identify hot keys (high-frequency short codes) using a Redis ZSET scored by click count.
- Pre-warm cache for top-N hot keys on a background interval — do not rely on lazy cache population for hot paths.
- In benchmarks and load tests, model celebrity traffic as a **separate scenario**: a small pool (e.g. 5 codes) receiving a disproportionate share of reads.
- Cache warmer must prioritise hot keys from the ZSET; fall back to `ORDER BY clicks DESC` when the ZSET is empty.

```python
# GOOD — score hot URLs in Redis ZSET on every click
await cache.zincrby(settings.HOT_URLS_ZSET_KEY, 1, url.short_code)
await cache.expire(settings.HOT_URLS_ZSET_KEY, settings.HOT_URLS_TTL_SECONDS, nx=True)

# GOOD — cache warmer reads top-N from ZSET
hot_codes = await cache.zrevrange(settings.HOT_URLS_ZSET_KEY, 0, settings.CACHE_WARMER_TOP_N - 1)
```

### Naming rule for performance-critical variables

- Never use single-letter or abbreviated names for values that persist beyond a single expression.
- Use names that encode **what the value represents**, not its type.

| BAD | GOOD | Why |
|---|---|---|
| `q` | `prometheus_query` | it's a Prometheus PromQL string |
| `u` | `prometheus_url` | it's a URL string |
| `rs` | `per_instance_results` | it's a list of per-instance metric rows |
| `w` | `rate_window` | it's a Prometheus rate window string |
| `m` | `min_app_rps` | it's a minimum RPS threshold |
| `v` | `total_5xx_rps` | it's a float rate value |
| `obj` | `prometheus_response` | it's a parsed JSON response |

Exception: conventional loop indices (`i`, `j`) and single-expression comprehensions are acceptable.

---

## 33. Docker-Only Tooling — No Local Installs

- **All** developer tooling (linting, formatting, type checking, benchmarking) must run inside ephemeral Docker containers.
- No tool may require a local `pip install`, `npm install`, or system package outside of Docker.
- Makefile targets are the single entry point for all tooling — never document raw `python -m` or `npx` commands as the primary way to run tools.
- Use `python:3.12-slim` for Python tooling containers. Install only what is needed for that specific target — keep containers minimal.
- Pass environment variables explicitly via `-e KEY=${KEY:-default}` — never rely on host environment leaking into containers.

```makefile
# GOOD — ephemeral container, no local install required
lint:
    @docker run --rm -v "$$(pwd)":/work -w /work python:3.12-slim bash -lc \
        "pip install --no-cache-dir black==24.1.1 isort==5.13.2 >/dev/null \
         && black --check . && isort --check-only ."

typecheck:
    @docker run --rm -v "$$(pwd)":/work -w /work python:3.12-slim bash -lc \
        "export DEBIAN_FRONTEND=noninteractive; \
         apt-get update >/dev/null && apt-get install -y --no-install-recommends nodejs npm >/dev/null && \
         pip install --no-cache-dir -r requirements.txt >/dev/null && \
         npm -g --silent install pyright@1.1.408 >/dev/null && pyright"
```

### Tooling target matrix (mandatory)

Every project must expose these Makefile targets:

| Target | What it does |
|---|---|
| `make fmt` | Format all Python files with black + isort (Docker) |
| `make lint` | Check formatting without modifying (Docker) |
| `make typecheck` | Run pyright static analysis (Docker) |
| `make standards-check` | Run ruff + grep checks for banned loose-dict patterns (Docker) |
| `make bench` | Full workflow benchmark: writer + reader + celebrity (Docker) |
| `make up` | Start full stack |
| `make down` | Stop full stack |
| `make test` | Run pytest suite via docker compose |

> **Note:** There is only one benchmark target — `make bench`. It runs the full workflow (writer + reader + celebrity) simultaneously. There is no separate health-check micro benchmark.

### CI/CD job execution order

```
lint ──┐
        ├──► standards-check ──► test ──► bench-regression
typecheck ──┘

All jobs run in Docker. A commit is blocked if ANY job fails.
```

| CI Job | Makefile equivalent | Blocks |
|---|---|---|
| Format Check | `make lint` | everything |
| Type Check | `make typecheck` | standards-check |
| Coding Standards | `make standards-check` | test |
| Functional Tests | `make test` | bench-regression |
| Benchmark Regression | `make bench` + regression script | merge |

---

## 34. Benchmark Regression Gate

- Every project must maintain a **stored baseline file** (`docs/bench_baselines.json`) with per-scenario RPS and max error thresholds.
- CI must run the full workflow benchmark on every commit and compare results against the baseline.
- A commit **must not pass** if any scenario's RPS drops more than **15%** below the baseline, or if errors exceed the baseline `max_errors`.
- Baselines are updated **intentionally** — after a confirmed performance improvement, run `make bench`, copy the new numbers into `docs/bench_baselines.json`, and commit with a message explaining the improvement.
- Never silently update baselines to paper over a regression.

```json
{
  "writer (POST /api/shorten)":          { "rps": 77.73,  "max_errors": 50 },
  "reader (GET /<code> — broad pool)":   { "rps": 459.00, "max_errors": 0  },
  "celebrity (GET /<code> — 5-code hot pool)": { "rps": 228.67, "max_errors": 0 },
  "aggregate":                           { "rps": 765.40, "max_errors": 50 }
}
```

### Full workflow benchmark scenarios (mandatory)

The benchmark must cover **all three traffic patterns simultaneously**:

| Scenario | Endpoint | Models used | Purpose |
|---|---|---|---|
| **writer** | `POST /api/shorten` | `URLCreate` → `URLResponse` | Measures write throughput + DB + Kafka |
| **reader** | `GET /<code>` (broad pool) | `CachedURLPayload` | Measures read throughput + Redis cache |
| **celebrity** | `GET /<code>` (hot pool, N≤10 codes) | `CachedURLPayload` | Measures hot-key handling + cache hit rate |

- Run a **warmup phase** before timing starts — create enough short URLs so readers always have valid codes.
- All three scenarios run **concurrently** — aggregate RPS is the combined throughput under realistic mixed load.
- Record results in `docs/benchmarks.md` with date, command, and all per-scenario numbers.

### Regression check script

- `scripts/bench_regression_check.py` parses `bench_http.py` stdout, compares per-scenario RPS against `docs/bench_baselines.json`, and exits non-zero on regression.
- CI invokes it immediately after the benchmark run — the commit fails if it exits non-zero.

```bash
python scripts/bench_regression_check.py \
    --results /tmp/bench_output.txt \
    --baselines docs/bench_baselines.json \
    --tolerance 0.15
```

---

# Part 4 — Domain-Specific Rules (apply to specific areas of the codebase)

---

## 22. Audit and Observability

- Maintain append-only JSONL audit trails for important operations.
- Auto-complete patterns: guard contexts should auto-record success/failure on exit.
- Include `succeeded`, `error`, `duration_seconds` in markers and audit entries.
- Provide `last_run_status()` for read-only status checks without acquiring locks.

## 23. Endpoint Security

- Internal-only endpoints must be guarded with header checks.
- Return `403 Forbidden` with a clear message when the guard fails.

```python
if x_internal_source != "lb-status-page":
    return JSONResponse(status_code=403, content={...})
```

## 24. Scope of Changes

- **Only work on staged and unstaged changes** in the local working tree.
- Do not modify files that are not part of the current task.
- When scanning for improvements, limit scope to files that are already modified (shown by `git diff` and `git diff --cached`).
- If a fix requires changes to an unmodified file, flag it for discussion first — don't silently edit unrelated files.
- Apply consistent standards across **all** changed files — don't fix one file and leave the same issue in another changed file.

---

# Part 5 — Project Standards (apply to all learning projects)

---

## 25. Docker-First Development

- **All services must be containerized** — no external installations required.
- Use `docker-compose.yml` for orchestration with health checks.
- Separate test services with `profiles: [test]`.
- Include volume mounts for development hot-reloading.
- All services must start with `make up` (one command).

## 26. Comprehensive Testing Strategy

- **Unit tests**: Every public method must be tested.
- **Integration tests**: Database, cache, and external service interactions.
- **E2E tests**: Full request-response cycles.
- Test containers must be isolated from development containers.
- Use `pytest` with async support and coverage reporting.
- All tests must pass before any merge.

## 27. External Testing Infrastructure

- **Dockerized stress testing**: Locust or Artillery for load testing.
- **Regression test suite**: Automated regression detection.
- **Concurrency testing**: Verify thread safety and race conditions.
- Testing services must be separate containers with their own profiles.

## 28. Scalable System Design

- Design for horizontal scaling from day one.
- Stateless API services.
- Separate cache layer (Redis) from database.
- Use connection pooling and resource limits.
- Document scaling strategy with capacity planning.

## 29. Comprehensive Documentation

- **README**: Quick start, commands, architecture overview.
- **Architecture docs**: System diagrams, component breakdown, data models.
- **Scaling strategy**: Bottleneck analysis, scaling dimensions, trade-offs.
- **API documentation**: Interactive docs + endpoint reference.
- **Strategy comparisons**: Design decisions with pros/cons analysis.

## 30. Phased Implementation

- Break projects into logical phases.
- Each phase must be independently runnable and tested.
- Phase 1: Foundation (API, DB, cache, tests, basic docs)
- Phase 2: Frontend + Analytics
- Phase 3: Scalability features
- Phase 4: Testing infrastructure
- Phase 5: Complete documentation + diagrams

## 31. Diagram-Based Visualizations

- **Architecture diagrams**: ASCII/mermaid showing system components.
- **Sequence diagrams**: Request flow and component interactions.
- **Data flow diagrams**: How data moves through the system.
- **Deployment diagrams**: Container orchestration and networking.

## 32. Strategy Trade-off Analysis

- Document all major design decisions.
- Compare alternatives with pros/cons tables.
- Include capacity estimates and scaling limits.
- Discuss when each approach is appropriate.
- Provide clear recommendations with justifications.
