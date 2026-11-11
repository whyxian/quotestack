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


def test_every_capability_has_a_ttl_and_a_stale_limit() -> None:
    """The tables are passive lookups: a missing key is a KeyError at runtime.

    LIST was absent from both, so the first caching path to touch a listing
    would have crashed with KeyError instead of using a default.
    """
    from quotestack.cache.base import default_max_stale, default_ttl
    from quotestack.models import Capability

    assert set(default_ttl()) == set(Capability)
    assert set(default_max_stale()) == set(Capability)


async def test_every_capability_that_caches_actually_caches() -> None:
    """A TTL nobody reads is dead configuration.

    FX had a TTL from the first commit and fx() bypassed the cache entirely for
    weeks: nothing failed, because the table is only read inside FetchPolicy,
    which fx() never called. This asserts consumption instead of existence.
    """
    import datetime as dt

    from quotestack import AssetClass, Market, MarketData
    from quotestack.benchmark import Benchmark, BenchmarkComponent, ComponentKind
    from quotestack.cache.base import NOT_CACHED
    from quotestack.models import Allocation, Capability, FxRate, Profile
    from quotestack.sources.base import SourceMeta

    class Everything:
        meta = SourceMeta(
            name="eastmoney",
            capabilities=frozenset(Capability) - NOT_CACHED,
            markets=frozenset({(AssetClass.STOCK, Market.CN), (AssetClass.FUND, Market.CN)}),
        )

        async def profile(self, instrument: object) -> Profile:
            return Profile(
                fund_type="指数型-股票",
                benchmark=Benchmark(
                    text="中证800*100%",
                    components=[
                        BenchmarkComponent(name="中证800", weight=100.0, kind=ComponentKind.EQUITY)
                    ],
                    coverage=1.0,
                ),
            )

        async def allocation(self, instrument: object) -> Allocation:
            return Allocation(stock=90.0, bond=0.0, cash=10.0)

        async def fx(self, base: str, quote: str) -> FxRate:
            return FxRate(
                base=base,
                quote=quote,
                rate="7",
                source="eastmoney",
                as_of=dt.datetime.now(dt.UTC),
                derived=False,
            )

        async def aclose(self) -> None:
            return None

    client = MarketData(sources={"eastmoney": Everything()})
    try:
        # FX is the capability this test exists for; the others need real
        # upstream payloads, so only FX is exercised end to end here.
        await client.fx("USD", "CNY")
        keys = list(client._cache._store)  # type: ignore[attr-defined]
    finally:
        await client.aclose()

    assert any(key.startswith("v1|fx|") for key in keys), f"FX did not cache: {keys}"
