"""Source registration, health reporting and lifecycle."""

from __future__ import annotations

import datetime as dt
from typing import Any

from quotestack import AssetClass, Market, MarketData
from quotestack.models import Capability, Profile
from quotestack.sources.base import SourceMeta


async def test_aclose_tolerates_a_source_without_aclose() -> None:
    """A third-party source may implement only the methods it needs."""

    class _NoClose:
        meta = SourceMeta(
            name="bare",
            capabilities=frozenset({Capability.PROFILE}),
            markets=frozenset({(AssetClass.FUND, Market.CN)}),
        )

        async def profile(self, instrument: Any) -> Profile:
            return Profile()

    client = MarketData(sources={"bare": _NoClose()})
    await client.aclose()


def test_cache_stats_reflects_stored_entries() -> None:
    client = MarketData()
    assert client.cache_stats()["entries"] == 0


def test_health_lists_every_configured_source() -> None:
    client = MarketData()
    assert set(client.health()["sources"]) == {
        "eastmoney",
        "tencent",
        "tiantian",
        "eastmoney-fx",
        "binance",
    }


def test_health_marks_a_cooling_source_as_degraded() -> None:
    """A degraded source must be visible in the status field."""
    from quotestack.resilience import Cooldown

    cooldown = Cooldown(duration=60.0, failure_threshold=1)
    client = MarketData(cooldown=cooldown)
    cooldown.mark_failed("eastmoney")

    health = client.health()
    assert health["status"] == "degraded"


def test_proxy_credentials_are_redacted_in_health() -> None:
    """`/healthz` is unauthenticated; a proxy password must not appear there."""
    from quotestack.client import _redact_proxy

    assert _redact_proxy("http://user:secret@proxy.local:7890") == (
        "http://<redacted>@proxy.local:7890"
    )
    assert _redact_proxy("http://proxy.local:7890") == "http://proxy.local:7890"
    assert _redact_proxy(None) is None


def test_a_source_is_registered_under_its_own_name() -> None:
    """One source, one name.

    The FX adapter was registered as "fx" while calling itself "eastmoney-fx",
    so the same source appeared under two names: health() said one thing and an
    error context said another.
    """
    from quotestack.client import default_sources

    for key, source in default_sources().items():
        assert key == source.meta.name, f"registered as {key}, calls itself {source.meta.name}"


async def test_fx_is_found_by_capability_not_by_name() -> None:
    """A second FX provider must work without renaming anything."""

    from quotestack.models import Capability, FxRate
    from quotestack.sources.base import SourceMeta

    class Rates:
        meta = SourceMeta(
            name="some-other-fx",
            capabilities=frozenset({Capability.FX}),
            markets=frozenset(),
        )

        async def fx(self, base: str, quote: str) -> FxRate:
            return FxRate(
                base=base,
                quote=quote,
                rate="7.0",
                source="some-other-fx",
                as_of=dt.datetime.now(dt.UTC),
                derived=False,
            )

        async def aclose(self) -> None:
            return None

    client = MarketData(sources={"some-other-fx": Rates()})
    try:
        rate = await client.fx("USD", "CNY")
    finally:
        await client.aclose()

    assert rate.rate == "7.0"
    assert rate.source == "some-other-fx"
