"""Fetch orchestration: cache state, single-flight and source fallback.

This is a mechanism, not a part of the public API, so it lives in its own
object. :class:`MarketData` owns one instance and asks it for values.

The three cache states come from ``cache.classify``:

- ``FRESH``: serve immediately, no network
- ``STALE``: try the network, but serve this value if every source fails
- ``EXPIRED``: try the network, and raise if every source fails
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from quotestack.cache import Cache, CacheEntry, CacheState, classify, is_fresh
from quotestack.errors import SchemaChangedError, UnavailableError, UpstreamError
from quotestack.logging import event, get_logger
from quotestack.models import Capability, Instrument
from quotestack.resilience import Cooldown, TokenBucket
from quotestack.sources.routing import candidates

__all__ = ["FetchPolicy"]

_log = get_logger("client")


class FetchPolicy:
    """Coordinates cache, single-flight, rate limiting and fallback.

    Args:
        cache: Storage backend.
        ttl: Freshness window per capability, in seconds.
        max_stale: How long past the TTL a value may still be served.
        sources: Source registry keyed by name.
        priority: Optional per-capability source order override.
        cooldown: Per-source cooldown policy.
        bucket: Outbound rate limiter.
    """

    def __init__(
        self,
        *,
        cache: Cache,
        ttl: dict[Capability, float],
        max_stale: dict[Capability, float],
        sources: dict[str, object],
        priority: dict[str, list[str]],
        cooldown: Cooldown,
        bucket: TokenBucket,
    ) -> None:
        self._cache = cache
        self._ttl = ttl
        self._max_stale = max_stale
        self._sources = sources
        self._priority = priority
        self._cooldown = cooldown
        self._bucket = bucket
        self._inflight: dict[str, asyncio.Task[object]] = {}

    def cancel_inflight(self) -> None:
        """Cancel every in-flight fetch."""
        for task in self._inflight.values():
            task.cancel()
        self._inflight.clear()

    async def get(
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
            if attempts:
                # Reaching here with a recorded attempt means the previous
                # source failed; that switch is worth counting.
                event(
                    _log,
                    logging.DEBUG,
                    "fallback",
                    capability=capability.value,
                    from_source=attempts[-1].get("source"),
                    to_source=name,
                    hint=f"trying {name} after {attempts[-1].get('source')} failed",
                )
            try:
                value = await fetch(source)
            except SchemaChangedError as exc:
                event(
                    _log,
                    logging.ERROR,
                    "schema_changed",
                    capability=capability.value,
                    source=name,
                    assertion=exc.context.get("assertion"),
                    hint="the upstream payload changed shape; the parser needs updating",
                )
                attempts.append({"source": name, "reason": exc.code})
                continue
            except UpstreamError as exc:
                # Cooling a whole source because one instrument is missing
                # would take the other instruments down with it.
                if exc.retryable and self._cooldown.mark_failed(name):
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
        event(
            _log,
            logging.ERROR,
            "all_sources_failed",
            capability=capability.value,
            key=key,
            reason=reason,
            attempts=len(attempts or []),
            hint="every configured source failed; see attempts for per-source reasons",
        )
        raise UnavailableError(reason, attempts=attempts or [])

    def fresh_entry(self, key: str, capability: Capability) -> CacheEntry | None:
        entry = self._cache.get(key)
        if entry is None or not is_fresh(entry, self._ttl[capability]):
            return None
        return entry
