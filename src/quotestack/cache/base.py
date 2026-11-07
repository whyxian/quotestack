"""Cache primitives.

Entries store when they were fetched rather than when they expire: freshness
is computed at read time from the current TTL configuration, so changing a TTL
takes effect immediately.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from quotestack.models import Capability

__all__ = ["CacheEntry", "CacheKey", "default_ttl", "make_key"]

CACHE_VERSION = "v1"

# Seconds. Chosen per capability, not per source.
_DEFAULT_TTL: dict[Capability, float] = {
    Capability.RESOLVE: 7 * 24 * 3600,
    Capability.QUOTE: 30.0,
    Capability.HISTORY: 3600.0,
    Capability.NAV: 6 * 3600.0,
    Capability.PROFILE: 24 * 3600.0,
    Capability.HOLDINGS: float("inf"),  # historical quarters never change
    Capability.BENCHMARK: 6 * 3600.0,
    Capability.ESTIMATE: 30.0,
    Capability.FX: 3600.0,
}


@dataclass(frozen=True, slots=True)
class CacheEntry:
    """A cached value plus the metadata needed to judge its freshness.

    Args:
        value: The cached payload.
        fetched_at: When the payload was retrieved, timezone-aware.
        source: Which source produced it.
    """

    value: object
    fetched_at: datetime
    source: str


class CacheKey(str):
    """A cache key. A plain string, typed for readability."""


class Cache(Protocol):
    """Minimal cache contract."""

    def get(self, key: str) -> CacheEntry | None:
        """Return the entry for ``key``, or ``None`` when absent."""
        ...

    def set(self, key: str, value: object, source: str) -> None:
        """Store a value under ``key``."""
        ...


def default_ttl() -> dict[Capability, float]:
    """Return a mutable copy of the built-in TTL table."""
    return dict(_DEFAULT_TTL)


def make_key(capability: Capability, instrument_id: str, *parts: str) -> CacheKey:
    """Build a cache key.

    Args:
        capability: Which capability produced the value.
        instrument_id: Canonical instrument identifier.
        *parts: Extra dimensions such as interval or adjustment.

    Returns:
        A key like ``v1|history|CN:STOCK:600519|1d|qfq``.
    """
    segments = [CACHE_VERSION, capability.value.lower(), instrument_id, *parts]
    return CacheKey("|".join(segments))


def is_fresh(entry: CacheEntry, ttl: float, now: datetime | None = None) -> bool:
    """Whether an entry is still within its TTL.

    Args:
        entry: The cached entry.
        ttl: Time to live in seconds.
        now: Reference instant, defaults to the current UTC time.

    Returns:
        ``True`` when the entry has not expired.
    """
    reference = now or datetime.now(UTC)
    age = (reference - entry.fetched_at).total_seconds()
    return age < ttl


def age_seconds(entry: CacheEntry, now: datetime | None = None) -> float:
    """Return how old an entry is, in seconds."""
    reference = now or datetime.now(UTC)
    return (reference - entry.fetched_at).total_seconds()


def merge_ttl(overrides: Mapping[Capability, float] | None) -> dict[Capability, float]:
    """Merge caller-supplied TTL overrides onto the defaults."""
    merged = default_ttl()
    if overrides:
        merged.update(overrides)
    return merged
