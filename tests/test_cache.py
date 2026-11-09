"""Cache behaviour: three-state classification and bounded retention."""

from __future__ import annotations

import pytest

from quotestack.cache.memory import MemoryCache


def test_cache_evicts_the_least_recently_used_entry() -> None:
    """A bounded cache: a service that sees a whole market must not grow forever."""
    cache = MemoryCache(max_entries=2)
    cache.set("a", 1, "s")
    cache.set("b", 2, "s")
    cache.get("a")  # reading a makes b the oldest
    cache.set("c", 3, "s")

    assert len(cache) == 2
    assert cache.get("a") is not None
    assert cache.get("b") is None
    assert cache.get("c") is not None


def test_cache_rejects_a_zero_bound() -> None:
    with pytest.raises(ValueError):
        MemoryCache(max_entries=0)
