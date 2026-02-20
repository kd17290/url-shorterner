"""High-throughput Locust profile targeting approximately 50k read RPS.

This profile separates writer and reader users to sustain a hot pool of short
codes while driving redirect-heavy traffic.
"""

import random

from locust import FastHttpUser, constant_throughput, task

MAX_SHARED_CODES = 20000
WRITER_COUNT = 100
WRITER_RPS_PER_USER = 5
READER_COUNT = 1000
READER_RPS_PER_USER = 50


class SharedCodes:
    """Shared in-process short-code pool used by all users in this worker."""

    codes: list[str] = []


class WriterUser(FastHttpUser):
    """Writer profile that continuously produces short URLs."""

    fixed_count = WRITER_COUNT
    wait_time = constant_throughput(WRITER_RPS_PER_USER)

    @task
    def create_short_url(self) -> None:
        """Create short URL and keep recent codes for readers."""

        url = f"https://example.com/write/{random.randint(1, 100000000)}"
        response = self.client.post("/api/shorten", json={"url": url}, name="WRITE /api/shorten")
        if response.status_code == 201:
            code = response.json().get("short_code")
            if code:
                SharedCodes.codes.append(code)
                if len(SharedCodes.codes) > MAX_SHARED_CODES:
                    SharedCodes.codes = SharedCodes.codes[-MAX_SHARED_CODES:]


class ReaderUser(FastHttpUser):
    """Reader profile targeting redirect-heavy throughput."""

    fixed_count = READER_COUNT
    wait_time = constant_throughput(READER_RPS_PER_USER)

    @task
    def redirect(self) -> None:
        """Resolve random shared short code or warm up health endpoint."""

        if not SharedCodes.codes:
            self.client.get("/health", name="READ /health (warmup)")
            return
        code = random.choice(SharedCodes.codes)
        self.client.get(f"/{code}", name="READ /:short_code", allow_redirects=False)
