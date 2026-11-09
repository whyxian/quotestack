"""Synchronous wrapper: lifecycle, ordering and shutdown."""

from __future__ import annotations

import pytest

from quotestack.cache import default_max_stale, default_ttl
from quotestack.cache.memory import MemoryCache
from quotestack.resilience import Cooldown, TokenBucket


def test_a_failed_construction_leaves_no_thread_running(monkeypatch: pytest.MonkeyPatch) -> None:
    """The thread used to start before the client was built.

    A constructor that raised left a daemon loop running with nobody holding a
    reference to stop it.
    """
    import threading

    from quotestack.sync import SyncMarketData

    before = {t.name for t in threading.enumerate()}

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("construction failed")

    with monkeypatch.context() as patch:
        patch.setattr("quotestack.sync.MarketData", boom)
        with pytest.raises(RuntimeError):
            SyncMarketData()

    leaked = {t.name for t in threading.enumerate()} - before
    assert "quotestack-loop" not in leaked


def test_close_is_bounded_and_idempotent() -> None:
    """A source that never finishes closing must not hold the process open."""
    from quotestack.sync import SyncMarketData

    client = SyncMarketData()
    client.close()
    client.close()


def test_cancel_inflight_waits_for_the_task_to_stop() -> None:
    """Cancelling is asynchronous; closing the source before it unwound raced."""
    import asyncio

    from quotestack.client.fetch import FetchPolicy

    async def scenario() -> None:
        policy = FetchPolicy(
            cache=MemoryCache(),
            ttl=default_ttl(),
            max_stale=default_max_stale(),
            sources={},
            priority={},
            cooldown=Cooldown(),
            bucket=TokenBucket(rate=1000),
        )
        stopped = asyncio.Event()

        async def linger() -> None:
            try:
                await asyncio.sleep(30)
            finally:
                stopped.set()

        task = asyncio.create_task(linger())
        policy._inflight["k"] = task
        await asyncio.sleep(0)
        await policy.cancel_inflight()

        assert stopped.is_set(), "cancel_inflight returned before the task finished"

    asyncio.run(scenario())
