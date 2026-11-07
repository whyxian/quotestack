"""Cache lookup, single-flight and fallback orchestration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from quotestack.cache import CacheEntry, CacheState, classify, is_fresh
from quotestack.client.state import ClientState
from quotestack.errors import UnavailableError, UpstreamError
from quotestack.logging import event, get_logger
from quotestack.models import Capability, Instrument
from quotestack.sources.routing import candidates

__all__ = ["FlowMixin"]

_log = get_logger("client")


class FlowMixin(ClientState):

    async def _cached(
        self,
        key: str,
        capability: Capability,
        instrument: Instrument,
        *,
        fetch: Callable[[object], Awaitable[object]],
        is_expected: Callable[[object], bool],
        mark_stale: Callable[[object], object] | None = None,
        max_age: float | None = None,
    ) -> object:
        entry = self._cache.get(key)
        ttl = self._ttl[capability] if max_age is None else max_age
        state = classify(entry, ttl, self._max_stale[capability])
        event(
            _log,
            logging.DEBUG,
            "cache_lookup",
            key=key,
            state=state.value,
            capability=capability.value,
        )

        if state is CacheState.FRESH and entry is not None and is_expected(entry.value):
            return entry.value

        return await self._single_flight(
            key,
            capability,
            state,
            entry,
            instrument,
            fetch,
            mark_stale,
        )

    async def _single_flight(
        self,
        key: str,
        capability: Capability,
        state: CacheState,
        entry: CacheEntry | None,
        instrument: Instrument,
        fetch: Callable[[object], Awaitable[object]],
        mark_stale: Callable[[object], object] | None,
    ) -> object:
        task = self._inflight.get(key)
        if task is None:
            task = asyncio.create_task(
                self._fetch_and_store(key, capability, state, entry, instrument, fetch, mark_stale)
            )
            self._inflight[key] = task
            task.add_done_callback(lambda _: self._inflight.pop(key, None))
        return await asyncio.shield(task)

    async def _fetch_and_store(
        self,
        key: str,
        capability: Capability,
        state: CacheState,
        entry: CacheEntry | None,
        instrument: Instrument,
        fetch: Callable[[object], Awaitable[object]],
        mark_stale: Callable[[object], object] | None,
    ) -> object:
        attempts: list[dict[str, object]] = []
        for name in candidates(
            instrument.asset_class,
            instrument.market,
            capability,
            self._priority,
        ):
            source = self._sources.get(name)
            if source is None:
                continue
            if self._cooldown.is_cooling(name):
                attempts.append(
                    {
                        "source": name,
                        "reason": "cooldown",
                        "remaining": round(self._cooldown.remaining(name), 1),
                    }
                )
                continue

            await self._bucket.acquire()
            try:
                value = await fetch(source)
            except UpstreamError as exc:
                if self._cooldown.mark_failed(name):
                    event(
                        _log,
                        logging.WARNING,
                        "cooldown",
                        source=name,
                        action="mark",
                        duration=self._cooldown.duration,
                        hint=f"{name} failed with {exc.code}; skipping it briefly",
                    )
                attempts.append({"source": name, "reason": exc.code})
                continue

            self._cooldown.mark_ok(name)
            self._cache.set(key, value, name)
            return value

        reason = "all sources failed"
        return self._fallback(
            key,
            capability,
            state,
            entry,
            mark_stale,
            reason=reason,
            attempts=attempts,
        )

    def _fallback(
        self,
        key: str,
        capability: Capability,
        state: CacheState,
        entry: CacheEntry | None,
        mark_stale: Callable[[object], object] | None,
        *,
        reason: str,
        attempts: list[dict[str, object]] | None = None,
    ) -> object:
        if state is CacheState.STALE and entry is not None:
            stale_value = mark_stale(entry.value) if mark_stale else entry.value
            event(
                _log,
                logging.WARNING,
                "stale_served",
                capability=capability.value,
                key=key,
                source=entry.source,
                hint=f"serving cached value because {reason}",
            )
            return stale_value
        raise UnavailableError(reason, attempts=attempts or [])

    def _fresh_entry(self, key: str, capability: Capability) -> CacheEntry | None:
        entry = self._cache.get(key)
        if entry is None or not is_fresh(entry, self._ttl[capability]):
            return None
        return entry
