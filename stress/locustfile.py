"""Basic Locust profile for mixed create/redirect/stats operations.

This profile is convenient for local smoke load and interactive testing. It keeps
an in-user short-code pool so redirect and stats traffic can target recently
created short URLs.
"""

import random

from locust import HttpUser, between, task

MAX_CODES_PER_USER = 200


class UrlShortenerUser(HttpUser):
    """Mixed workload user for local functional load checks."""

    wait_time = between(0.1, 0.5)

    def on_start(self) -> None:
        """Initialize per-user short-code cache for follow-up read requests."""

        self.codes: list[str] = []

    @task(2)
    def create_short_url(self) -> None:
        """Create new short URLs and add successful codes to user cache."""

        url = f"https://example.com/page/{random.randint(1, 1000000)}"
        payload = {"url": url}
        response = self.client.post("/api/shorten", json=payload, name="POST /api/shorten")

        if response.status_code == 201:
            short_code = response.json().get("short_code")
            if short_code:
                self.codes.append(short_code)
                if len(self.codes) > MAX_CODES_PER_USER:
                    self.codes = self.codes[-MAX_CODES_PER_USER:]

    @task(6)
    def redirect(self) -> None:
        """Resolve an existing short code or seed one during warmup."""

        if not self.codes:
            self.create_short_url()
            return

        short_code = random.choice(self.codes)
        self.client.get(f"/{short_code}", name="GET /:short_code", allow_redirects=False)

    @task(2)
    def stats(self) -> None:
        """Fetch stats for a sampled short code from user cache."""

        if not self.codes:
            self.create_short_url()
            return

        short_code = random.choice(self.codes)
        self.client.get(f"/api/stats/{short_code}", name="GET /api/stats/:short_code")
