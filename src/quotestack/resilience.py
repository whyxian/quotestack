"""Resilience primitives: per-source cooldown and outbound rate limiting.

Both exist to protect the upstream rather than the caller:

- Cooldown stops us from paying a full timeout on every request when a source
  is already known to be down.
- The token bucket keeps our request rate polite when several callers share
  one process.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from quotestack.errors import RateLimitedError

__all__ = ["Cooldown", "TokenBucket"]


@dataclass(slots=True)
class Cooldown:
    """Temporarily skip a source after it fails.

    Args:
        duration: How long to skip the source, in seconds.
        failure_threshold: Consecutive failures required before cooling. Two,
            not one: a single blip is common and cooling the source would make
            every other instrument fail for the whole window.
    """

    duration: float = 30.0
    failure_threshold: int = 2
    _failures: dict[str, int] = field(default_factory=dict)
    _until: dict[str, float] = field(default_factory=dict)
    _clock: object = field(default=time.monotonic, repr=False)

    def _now(self) -> float:
        return float(self._clock())  # type: ignore[operator]

    def is_cooling(self, source: str) -> bool:
        """Whether the source is currently being skipped."""
        return self._until.get(source, 0.0) > self._now()

    def remaining(self, source: str) -> float:
        """Seconds left in the cooldown, or ``0`` when not cooling."""
        return max(0.0, self._until.get(source, 0.0) - self._now())

    def mark_failed(self, source: str) -> bool:
        """Record a failure.

        Returns:
            ``True`` when this failure started a cooldown.
        """
        count = self._failures.get(source, 0) + 1
        self._failures[source] = count
        if count < self.failure_threshold:
            return False
        self._until[source] = self._now() + self.duration
        return True

    def cool_for(self, source: str, seconds: float) -> None:
        """Skip the source for as long as it asked, not for the default.

        A source that answers ``Retry-After: 120`` knows better than our fixed
        30 seconds; retrying sooner is how a throttle turns into a block.
        """
        self._until[source] = self._now() + max(0.0, seconds)

    def mark_ok(self, source: str) -> None:
        """Clear the failure count and any cooldown."""
        self._failures.pop(source, None)
        self._until.pop(source, None)

    def reset(self) -> None:
        """Forget every source."""
        self._failures.clear()
        self._until.clear()


class TokenBucket:
    """A classic token bucket.

    Args:
        rate: Tokens added per second.
        capacity: Maximum burst size. Kept at 1 by default so requests are
            spaced evenly: sending a burst of ten back to back is what earns a
            514 from Eastmoney's rate limiter.
        rate: Four per second is the measured ceiling for Eastmoney's fund
            pages over a reused connection; five trips their throttle.

    Example:
        Four requests per second, strictly spaced, is the safest default::

            bucket = TokenBucket(rate=4.0, capacity=1)
    """

    def __init__(self, rate: float = 4.0, capacity: int = 1) -> None:
        """Create a bucket that starts full."""
        if rate <= 0:
            msg = "rate must be positive"
            raise ValueError(msg)
        if capacity < 1:
            msg = "capacity must be at least 1"
            raise ValueError(msg)
        self._rate = rate
        self._capacity = float(capacity)
        self._tokens = float(capacity)
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, max_wait: float | None = 5.0) -> None:
        """Take one token, waiting until one is available.

        Args:
            max_wait: Maximum time to wait for a token. ``None`` waits forever.

        Raises:
            RateLimitedError: No token became available within ``timeout``.
        """
        async with self._lock:
            if max_wait is None:
                await self._wait_for_token()
                return
            try:
                async with asyncio.timeout(max_wait):
                    await self._wait_for_token()
            except TimeoutError as exc:
                msg = "rate limit queue timed out"
                raise RateLimitedError(msg, source="quotestack") from exc

    async def _wait_for_token(self) -> None:
        while True:
            now = time.monotonic()
            elapsed = now - self._updated
            self._updated = now
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return
            deficit = (1.0 - self._tokens) / self._rate
            await asyncio.sleep(deficit)

    @property
    def tokens(self) -> float:
        """Currently available tokens."""
        return self._tokens
