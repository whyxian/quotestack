"""Cache primitives.

Entries store when they were fetched rather than when they expire: freshness
is computed at read time from the current TTL configuration, so changing a TTL
takes effect immediately.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from quotestack.models import Capability

__all__ = [
    "NOT_CACHED",
    "CacheEntry",
    "CacheKey",
    "CachePolicy",
    "CacheState",
    "classify",
    "default_max_stale",
    "default_ttl",
    "make_key",
]

CACHE_VERSION = "v1"


@dataclass(frozen=True, slots=True)
class CachePolicy:
    """How long a capability stays fresh, and how far it may fall back.

    Args:
        ttl: Seconds the entry is fresh.
        max_stale: Seconds an expired entry may still be served when the
            upstream fails. ``inf`` means "never too old".
    """

    ttl: float
    max_stale: float


# One row per capability, no defaults and no complement: a capability either
# carries a policy or says ``None`` with the reason. Two tables (a TTL table and
# a "not cached" set) can disagree; one total table cannot, and adding a
# capability fails a test until someone decides which column it belongs in.
_CACHE_POLICY: dict[Capability, CachePolicy | None] = {
    Capability.RESOLVE: CachePolicy(7 * 24 * 3600, 30 * 24 * 3600),
    Capability.QUOTE: CachePolicy(30.0, 24 * 3600),
    Capability.HISTORY: CachePolicy(3600.0, float("inf")),
    Capability.NAV: CachePolicy(6 * 3600.0, 7 * 24 * 3600),
    Capability.PROFILE: CachePolicy(24 * 3600.0, 7 * 24 * 3600),
    # Historical quarters never change.
    Capability.HOLDINGS: CachePolicy(float("inf"), float("inf")),
    Capability.ESTIMATE: CachePolicy(30.0, 300.0),
    Capability.FX: CachePolicy(3600.0, 7 * 24 * 3600),
    # Deliberately uncached.
    Capability.BENCHMARK: None,  # composed per request from component histories
    Capability.LIST: None,  # a listing streams; storing it has no reader
}

# Derived, not declared: the negative fact is a view of the table above.
NOT_CACHED: frozenset[Capability] = frozenset(
    capability for capability, policy in _CACHE_POLICY.items() if policy is None
)


class CacheState(StrEnum):
    """Freshness of a cached entry."""

    FRESH = "fresh"
    """Within TTL — serve directly."""

    STALE = "stale"
    """Past TTL but within max_stale — serve only if the upstream fails."""

    EXPIRED = "expired"
    """Past max_stale — never serve, even as a fallback."""


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

    def __len__(self) -> int:
        """Number of stored entries."""
        ...


def default_ttl() -> dict[Capability, float]:
    """Return the default fresh-for duration of every cached capability."""
    return {
        capability: policy.ttl for capability, policy in _CACHE_POLICY.items() if policy is not None
    }


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


def classify(
    entry: CacheEntry | None,
    ttl: float,
    max_stale: float,
    now: datetime | None = None,
) -> CacheState:
    """Classify a cache entry.

    Args:
        entry: The cached entry, or ``None`` when absent.
        ttl: Freshness window in seconds.
        max_stale: How long past the TTL the value may still be served.
        now: Reference instant, defaults to the current UTC time.

    Returns:
        :class:`CacheState`. A missing entry is always ``EXPIRED``.
    """
    if entry is None:
        return CacheState.EXPIRED
    age = age_seconds(entry, now)
    if age < ttl:
        return CacheState.FRESH
    if age < max_stale:
        return CacheState.STALE
    return CacheState.EXPIRED


def default_max_stale() -> dict[Capability, float]:
    """Return how stale every cached capability may be served."""
    return {
        capability: policy.max_stale
        for capability, policy in _CACHE_POLICY.items()
        if policy is not None
    }


def merge_ttl(overrides: Mapping[Capability, float] | None) -> dict[Capability, float]:
    """Merge caller-supplied TTL overrides onto the defaults."""
    merged = default_ttl()
    if overrides:
        merged.update(overrides)
    return merged
