"""Tests for cooldown and rate limiting."""

from __future__ import annotations

import pytest

from quotestack.errors import RateLimitedError
from quotestack.resilience import Cooldown, TokenBucket


class _Clock:
    """A manually advanced monotonic clock."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_cooldown_starts_inactive() -> None:
    """A fresh cooldown never skips a source."""
    assert not Cooldown().is_cooling("eastmoney")


def test_cooldown_marks_and_expires() -> None:
    """Two consecutive failures start a cooldown that later expires."""
    clock = _Clock()
    cooldown = Cooldown(duration=30.0, _clock=clock)

    assert cooldown.mark_failed("eastmoney") is False
    assert cooldown.mark_failed("eastmoney") is True
    assert cooldown.is_cooling("eastmoney")
    assert cooldown.remaining("eastmoney") == pytest.approx(30.0)

    clock.advance(29.9)
    assert cooldown.is_cooling("eastmoney")

    clock.advance(0.2)
    assert not cooldown.is_cooling("eastmoney")


def test_single_failure_does_not_cool_the_source() -> None:
    """A blip must not take the source down for everyone else."""
    clock = _Clock()
    cooldown = Cooldown(_clock=clock)

    assert cooldown.mark_failed("eastmoney") is False
    assert not cooldown.is_cooling("eastmoney")


def test_cooldown_respects_failure_threshold() -> None:
    """With a threshold of two, a single failure does not trigger a cooldown."""
    clock = _Clock()
    cooldown = Cooldown(duration=30.0, failure_threshold=2, _clock=clock)

    assert cooldown.mark_failed("eastmoney") is False
    assert not cooldown.is_cooling("eastmoney")

    assert cooldown.mark_failed("eastmoney") is True
    assert cooldown.is_cooling("eastmoney")


def test_cooldown_success_clears_state() -> None:
    """A success clears both the failure count and any active cooldown."""
    clock = _Clock()
    cooldown = Cooldown(duration=30.0, _clock=clock)
    cooldown.mark_failed("eastmoney")
    cooldown.mark_failed("eastmoney")

    cooldown.mark_ok("eastmoney")

    assert not cooldown.is_cooling("eastmoney")
    # The counter was cleared, so one more failure is not enough.
    assert cooldown.mark_failed("eastmoney") is False


async def test_bucket_allows_initial_burst() -> None:
    """A bucket starts full, so a burst up to capacity is immediate."""
    bucket = TokenBucket(rate=1.0, capacity=5)

    for _ in range(5):
        await bucket.acquire(max_wait=0.01)


async def test_bucket_raises_when_exhausted() -> None:
    """Exceeding the burst raises instead of blocking forever."""
    bucket = TokenBucket(rate=0.01, capacity=1)
    await bucket.acquire(max_wait=0.01)

    with pytest.raises(RateLimitedError):
        await bucket.acquire(max_wait=0.05)


async def test_bucket_refills_over_time() -> None:
    """Tokens come back at the configured rate."""
    bucket = TokenBucket(rate=1000.0, capacity=1)
    await bucket.acquire(max_wait=0.01)

    await bucket.acquire(max_wait=1.0)


def test_bucket_rejects_invalid_configuration() -> None:
    """Rate and capacity must be positive."""
    with pytest.raises(ValueError, match="rate"):
        TokenBucket(rate=0)
    with pytest.raises(ValueError, match="capacity"):
        TokenBucket(capacity=0)
