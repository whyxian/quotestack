"""In-process cache."""

from __future__ import annotations

from datetime import UTC, datetime

from quotestack.cache.base import CacheEntry

__all__ = ["MemoryCache"]


class MemoryCache:
    """A process-local cache with no eviction.

    Entries are kept after they expire: freshness is decided by the caller,
    which lets a stale value be served when the upstream is unavailable.
    """

    def __init__(self) -> None:
        """Create an empty cache."""
        self._store: dict[str, CacheEntry] = {}

    def get(self, key: str) -> CacheEntry | None:
        """Return the entry for ``key``, or ``None`` when absent."""
        return self._store.get(key)

    def set(self, key: str, value: object, source: str) -> None:
        """Store a value, stamped with the current time."""
        self._store[key] = CacheEntry(
            value=value,
            fetched_at=datetime.now(UTC),
            source=source,
        )

    def clear(self) -> None:
        """Drop every entry."""
        self._store.clear()

    def __len__(self) -> int:
        """Number of stored entries."""
        return len(self._store)
