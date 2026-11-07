"""Client state, lifecycle and introspection."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Mapping, Sequence
from types import TracebackType
from typing import Self

from quotestack.cache import MemoryCache, default_max_stale, merge_ttl
from quotestack.client.state import ClientState
from quotestack.errors import UnsupportedError
from quotestack.identity import resolve as resolve_rules
from quotestack.logging import event, get_logger
from quotestack.models import AssetClass, Capability, Instrument, Market
from quotestack.resilience import Cooldown, TokenBucket
from quotestack.sources import (
    BinanceSource,
    EastMoneySource,
    FxSource,
    TencentSource,
    TiantianSource,
)

__all__ = ["CoreMixin", "default_sources"]

_log = get_logger("client")


def default_sources(proxy: str | None = None) -> dict[str, object]:
    """Build the built-in source registry."""
    return {
        "eastmoney": EastMoneySource(proxy=proxy),
        "tencent": TencentSource(proxy=proxy),
        "tiantian": TiantianSource(proxy=proxy),
        "fx": FxSource(proxy=proxy),
        "binance": BinanceSource(proxy=proxy),
    }


class CoreMixin(ClientState):

    def __init__(
        self,
        *,
        cache: MemoryCache | None = None,
        ttl: Mapping[Capability, float] | None = None,
        max_stale: Mapping[Capability, float] | None = None,
        sources: Mapping[str, object] | None = None,
        proxy: str | None = None,
        source_priority: Mapping[str, Sequence[str]] | None = None,
        cooldown: Cooldown | None = None,
        bucket: TokenBucket | None = None,
    ) -> None:
        """Create a client."""
        self._cache = cache if cache is not None else MemoryCache()
        self._ttl = merge_ttl(ttl)
        self._max_stale = {**default_max_stale(), **(max_stale or {})}
        self._sources: dict[str, object] = (
            dict(sources) if sources is not None else default_sources(proxy)
        )
        self._priority: dict[str, list[str]] = {
            key: list(value) for key, value in (source_priority or {}).items()
        }
        self._cooldown = cooldown if cooldown is not None else Cooldown()
        self._bucket = bucket if bucket is not None else TokenBucket()
        self._inflight: dict[str, asyncio.Task[object]] = {}

    async def __aenter__(self) -> Self:
        """Enter the async context."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the client on context exit."""
        await self.aclose()

    async def aclose(self) -> None:
        """Release resources held by the underlying source."""
        for task in self._inflight.values():
            task.cancel()
        self._inflight.clear()
        for source in self._sources.values():
            close = getattr(source, "aclose", None)
            if close is not None:
                await close()

    def resolve(
        self,
        code: str,
        asset_class: AssetClass = AssetClass.STOCK,
        market: Market = Market.CN,
    ) -> Instrument:
        """Resolve a code into an instrument using prefix rules.

        Args:
            code: Raw code, e.g. ``600519``.
            asset_class: Business classification.
            market: Trading venue.

        Returns:
            The resolved instrument.

        Raises:
            InvalidArgumentError: The code does not fit the market.
        """
        instrument = resolve_rules(code, asset_class, market)
        event(
            _log,
            logging.DEBUG,
            "resolve",
            code=code,
            market=market.value,
            asset_class=asset_class.value,
            instrument=instrument.id,
            confidence=instrument.confidence.value,
            aliases=dict(instrument.aliases),
        )
        return instrument

    def cache_stats(self) -> dict[str, int]:
        """Return a snapshot of cache occupancy."""
        return {"entries": len(self._cache)}

    def health(self) -> dict[str, object]:
        """Return the current runtime state.

        Mirrors the shape of the HTTP ``/healthz`` payload so the CLI and the
        service report the same information.
        """
        sources: dict[str, object] = {}
        degraded = False
        for name, source in self._sources.items():
            meta = source.meta  # type: ignore[attr-defined]
            cooling = self._cooldown.is_cooling(name)
            degraded = degraded or cooling
            sources[name] = {
                "state": "cooling" if cooling else "ok",
                "cooldown_remaining": round(self._cooldown.remaining(name), 1),
                "timeout": meta.timeout,
                "capabilities": sorted(c.value for c in meta.capabilities),
            }

        return {
            "status": "degraded" if degraded else "ok",
            "proxy": os.environ.get("QUOTESTACK_PROXY_URL")
            or os.environ.get("HTTPS_PROXY")
            or None,
            "sources": sources,
            "cache": self.cache_stats(),
        }

    def _require(self, instrument: Instrument, capability: Capability) -> None:
        if not instrument.supports(capability):
            raise UnsupportedError(
                f"{instrument.id} has no {capability.value.lower()} data",
                instrument=instrument.id,
                capability=capability.value,
                available=sorted(c.value for c in instrument.capabilities),
            )
