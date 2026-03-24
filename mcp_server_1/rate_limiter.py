"""
Generic token-bucket rate limiter for external API calls.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict


class RateLimiter:
    """Simple token-bucket rate limiter keyed by source name."""

    def __init__(self):
        self._buckets: dict[str, dict] = {}

    def configure(self, source: str, max_per_minute: int) -> None:
        self._buckets[source] = {
            "max_tokens": max_per_minute,
            "tokens": float(max_per_minute),
            "last_refill": time.monotonic(),
            "refill_rate": max_per_minute / 60.0,
        }

    async def acquire(self, source: str) -> None:
        if source not in self._buckets:
            return

        bucket = self._buckets[source]
        while True:
            now = time.monotonic()
            elapsed = now - bucket["last_refill"]
            bucket["tokens"] = min(
                bucket["max_tokens"],
                bucket["tokens"] + elapsed * bucket["refill_rate"],
            )
            bucket["last_refill"] = now

            if bucket["tokens"] >= 1.0:
                bucket["tokens"] -= 1.0
                return

            wait_time = (1.0 - bucket["tokens"]) / bucket["refill_rate"]
            await asyncio.sleep(wait_time)


rate_limiter = RateLimiter()
