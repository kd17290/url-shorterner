"""Locust orchestrator profile for mixed read/write traffic.

This module drives a steady-state traffic pattern against the URL shortener API.
It keeps a shared in-memory short-code pool and splits user behavior into:

- Writer users: create new short URLs.
- Reader users: resolve short URLs via redirect endpoint.

Runtime tuning is controlled by environment variables so docker-compose services
can target different load envelopes without code edits.
"""

import os
import random

from locust import FastHttpUser, constant_throughput, task

WRITE_USER_COUNT = int(os.getenv("TARGET_WRITE_USERS", "500"))
READ_USER_COUNT = int(os.getenv("TARGET_READ_USERS", "1000"))
WRITE_USER_RPS = float(os.getenv("TARGET_WRITE_RPS_PER_USER", "1"))
READ_USER_RPS = float(os.getenv("TARGET_READ_RPS_PER_USER", "1"))
MAX_SHARED_CODES = int(os.getenv("MAX_SHARED_CODES", "100000"))
CELEBRITY_TRAFFIC_PERCENT = min(max(float(os.getenv("CELEBRITY_TRAFFIC_PERCENT", "0")), 0.0), 1.0)
CELEBRITY_POOL_SIZE = int(os.getenv("CELEBRITY_POOL_SIZE", "100"))

TOTAL_USER_TARGET = max(WRITE_USER_COUNT + READ_USER_COUNT, 1)
WRITE_USER_WEIGHT = max(int((WRITE_USER_COUNT / TOTAL_USER_TARGET) * 1000), 1)
READ_USER_WEIGHT = max(int((READ_USER_COUNT / TOTAL_USER_TARGET) * 1000), 1)


class SharedCodes:
    """Shared in-process code pool used by all Locust users in this worker."""

    codes: list[str] = []
    celebrity_codes: list[str] = []


class WriterUser(FastHttpUser):
    """Writer profile generating short URLs at configured throughput."""

    weight = WRITE_USER_WEIGHT
    wait_time = constant_throughput(WRITE_USER_RPS)

    @task
    def create_short_url(self) -> None:
        """Create short URLs and retain the newest short codes for readers."""

        url = f"https://example.com/write/{random.randint(1, 10_000_000_000)}"
        response = self.client.post("/api/shorten", json={"url": url}, name="WRITE /api/shorten")
        if response.status_code == 201:
            code = response.json().get("short_code")
            if code:
                SharedCodes.codes.append(code)
                if len(SharedCodes.celebrity_codes) < CELEBRITY_POOL_SIZE:
                    SharedCodes.celebrity_codes.append(code)
                if len(SharedCodes.codes) > MAX_SHARED_CODES:
                    SharedCodes.codes = SharedCodes.codes[-MAX_SHARED_CODES:]


class ReaderUser(FastHttpUser):
    """Reader profile resolving short URLs at configured throughput."""

    weight = READ_USER_WEIGHT
    wait_time = constant_throughput(READ_USER_RPS)

    @task
    def redirect(self) -> None:
        """Resolve regular or celebrity short codes based on configured traffic mix."""

        if not SharedCodes.codes:
            return

        use_celebrity = bool(SharedCodes.celebrity_codes) and random.random() < CELEBRITY_TRAFFIC_PERCENT
        if use_celebrity:
            code = random.choice(SharedCodes.celebrity_codes)
            self.client.get(f"/{code}", name="READ /:short_code (celebrity)", allow_redirects=False)
            return

        code = random.choice(SharedCodes.codes)
        self.client.get(f"/{code}", name="READ /:short_code", allow_redirects=False)
