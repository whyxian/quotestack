"""In-process cache."""

from __future__ import annotations

from datetime import UTC, datetime

from quotestack.cache.base import CacheEntry

__all__ = ["MemoryCache"]


class MemoryCache:
    """A process-local cache with a bounded size.

    Entries are kept after they expire: freshness is decided by the caller,
    which lets a stale value be served when the upstream is unavailable. That
    is why eviction drops the entry that has gone longest without being read,
    not the one that expired first - an expired entry may still be the only
    answer available.

    A long-running service caches one entry per instrument it ever saw, and a
    full-market listing touches tens of thousands, so "no eviction" was an
    unbounded leak rather than a simplification.
    """

    def __init__(self, max_entries: int = 10_000) -> None:
        """Create an empty cache.

        Args:
            max_entries: Upper bound on stored entries. The least recently used
                entry is dropped when the bound is reached.
        """
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self._store: dict[str, CacheEntry] = {}
        self._max_entries = max_entries

    def get(self, key: str) -> CacheEntry | None:
        """Return the entry for ``key``, or ``None`` when absent.

        Reading moves the key to the most-recent end so eviction can drop the
        entry that has gone longest without being used.
        """
        entry = self._store.pop(key, None)
        if entry is not None:
            self._store[key] = entry
        return entry

    def set(self, key: str, value: object, source: str) -> None:
        """Store a value, stamped with the current time."""
        self._store.pop(key, None)
        self._store[key] = CacheEntry(
            value=value,
            fetched_at=datetime.now(UTC),
            source=source,
        )
        while len(self._store) > self._max_entries:
            oldest = next(iter(self._store))
            del self._store[oldest]

    def clear(self) -> None:
        """Drop every entry."""
        self._store.clear()

    def __len__(self) -> int:
        """Number of stored entries."""
        return len(self._store)
