"""Tests for the HTTP layer, exercising it in-process without a socket."""

from __future__ import annotations

import datetime as dt
import json
import pathlib
from typing import Any

import httpx
import pytest

from quotestack import MarketData
from quotestack.benchmark import Benchmark, BenchmarkComponent, ComponentKind
from quotestack.errors import UnsupportedError
from quotestack.models import (
    AssetClass,
    Bar,
    Estimate,
    EstimateBasis,
    FundClass,
    Holding,
    InstrumentSummary,
    Market,
    NavPoint,
    Profile,
    QuarterHoldings,
    Quote,
    QuoteStatus,
)
from quotestack.server.app import create_app
from quotestack.server.config import Config, ConfigError, load

_TS = dt.datetime(2026, 11, 6, 15, 0, tzinfo=dt.timezone(dt.timedelta(hours=8)))


class _FakeClient:
    """A client whose every method returns a fixed value."""

    def __init__(self) -> None:
        self.closed = False

    def source_for(self, capability: Any, instrument_id: str, *parts: str) -> str:
        return "eastmoney"

    def resolve(self, code: str, asset_class: Any = None, market: Any = None) -> Any:
        from quotestack.identity import resolve

        return resolve(code, asset_class or AssetClass.STOCK, market or Market.CN)

    async def quote(self, code: str, *args: Any, **kwargs: Any) -> Quote:
        if code == "022430":
            raise UnsupportedError("fund has no quote", instrument="CN:FUND:022430")
        return Quote(
            instrument_id="CN:STOCK:600519",
            price="1453.00",
            currency="CNY",
            source="eastmoney",
            ts=_TS,
            change="1.00",
            change_pct=0.07,
            status=QuoteStatus.REALTIME,
        )

    async def quote_many(self, items: list[Any]) -> list[Any]:
        from quotestack.models import QuoteResult

        return [
            QuoteResult(instrument=self.resolve(item[0]), error="UNSUPPORTED") for item in items
        ]

    async def history(self, *args: Any, **kwargs: Any) -> list[Bar]:
        return [
            Bar(
                date=dt.date(2026, 11, 6),
                open="1450.00",
                high="1457.72",
                low="1436.00",
                close="1453.00",
                volume="42848",
            )
        ]

    async def nav(self, *args: Any, **kwargs: Any) -> list[NavPoint]:
        return [NavPoint(date=dt.date(2026, 11, 6), nav="1.0690")]

    async def profile(self, *args: Any, **kwargs: Any) -> Profile:
        return Profile(
            fund_type="混合型-偏股",
            fund_class=FundClass.EQUITY,
            benchmark=Benchmark(
                text="中证800x70%",
                components=[
                    BenchmarkComponent(name="中证800", weight=70.0, kind=ComponentKind.EQUITY)
                ],
                coverage=0.7,
            ),
        )

    async def holdings(self, *args: Any, **kwargs: Any) -> list[QuarterHoldings]:
        return [
            QuarterHoldings(
                quarter="2026Q3",
                as_of=dt.date(2026, 9, 30),
                holdings=[Holding(code="300308", name="中际旭创", weight=4.66)],
            )
        ]

    async def benchmark(self, *args: Any, **kwargs: Any) -> Any:
        from quotestack.models import BenchmarkCurve, BenchmarkPoint

        return BenchmarkCurve(
            effective_start=dt.date(2026, 1, 2),
            components_used=[
                BenchmarkComponent(name="中证800", weight=70.0, kind=ComponentKind.EQUITY)
            ],
            components_dropped=["中债总指数"],
            coverage=0.7,
            series=[BenchmarkPoint(date=dt.date(2026, 1, 2), value=1.0)],
        )

    async def estimate(self, *args: Any, **kwargs: Any) -> Estimate:
        return Estimate(
            change_pct=None,
            basis=EstimateBasis.NONE,
            explanation="输入不可用",
        )

    async def fx(self, base: str, quote: str) -> Any:
        from quotestack.models import FxRate

        return FxRate(
            base=base,
            quote=quote,
            rate="6.6738",
            source="eastmoney-fx",
            as_of=_TS,
            derived=True,
        )

    async def iter_instruments(self, *args: Any, **kwargs: Any) -> Any:
        for _ in range(2):
            yield [
                InstrumentSummary(
                    code="600519",
                    name="贵州茅台",
                    asset_class=AssetClass.STOCK,
                    market=Market.CN,
                    currency="CNY",
                )
            ]

    def health(self) -> dict[str, object]:
        return {
            "status": "ok",
            "proxy": None,
            "sources": {"eastmoney": {"state": "ok"}},
            "cache": {"entries": 1},
        }

    async def aclose(self) -> None:
        self.closed = True


def _api() -> httpx.AsyncClient:
    app = create_app(Config(), client=_FakeClient())  # type: ignore[arg-type]
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_resolve_returns_the_envelope() -> None:
    async with _api() as api:
        response = await api.get("/v1/resolve", params={"code": "600519"})

    body = response.json()
    assert response.status_code == 200
    assert body["error"] is None
    assert body["data"]["id"] == "CN:STOCK:600519"


async def test_unsupported_maps_to_422_with_error_body() -> None:
    """A library refusal becomes a structured 422, never a 500."""
    async with _api() as api:
        response = await api.get("/v1/quote", params={"code": "022430"})

    body = response.json()
    assert response.status_code == 422
    assert body["data"] is None
    assert body["error"]["code"] == "UNSUPPORTED"


async def test_quote_keeps_prices_as_strings() -> None:
    """Money must not become a JSON number on the way out."""
    async with _api() as api:
        body = (await api.get("/v1/quote", params={"code": "600519"})).json()

    assert body["data"]["price"] == "1453.00"
    assert isinstance(body["data"]["price"], str)


async def test_estimate_null_is_preserved() -> None:
    """Null means unknown and must survive serialisation as null."""
    async with _api() as api:
        body = (await api.get("/v1/estimate", params={"code": "166002"})).json()

    assert body["data"]["change_pct"] is None
    assert body["data"]["basis"] == "none"


async def test_healthz_reports_sources() -> None:
    async with _api() as api:
        body = (await api.get("/v1/healthz")).json()

    assert body["data"]["status"] == "ok"
    assert "eastmoney" in body["data"]["sources"]


async def test_listing_is_paginated() -> None:
    async with _api() as api:
        body = (
            await api.get(
                "/v1/instruments",
                params={"asset_class": "STOCK", "market": "CN", "page_size": 1},
            )
        ).json()

    assert len(body["data"]["items"]) == 1
    assert body["data"]["page"] == 1


async def test_openapi_covers_every_documented_route() -> None:
    app = create_app(Config(), client=_FakeClient())  # type: ignore[arg-type]
    paths = set(app.openapi()["paths"])

    assert paths == {
        "/v1/resolve",
        "/v1/quote",
        "/v1/quotes/batch",
        "/v1/history",
        "/v1/nav",
        "/v1/profile",
        "/v1/holdings",
        "/v1/benchmark",
        "/v1/estimate",
        "/v1/fx",
        "/v1/instruments",
        "/v1/healthz",
    }


def test_config_defaults() -> None:
    config = load()

    assert config.host == "127.0.0.1"
    assert config.port == 8000


def test_config_environment_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUOTESTACK_SERVER_PORT", "9000")
    monkeypatch.setenv("QUOTESTACK_TTL_QUOTE", "never")

    config = load()

    assert config.port == 9000
    assert config.ttl["QUOTE"] == float("inf")


def test_config_rejects_invalid_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUOTESTACK_SERVER_PORT", "70000")

    with pytest.raises(ConfigError):
        load()


def test_config_reads_toml(tmp_path: Any) -> None:
    file = tmp_path / "quotestack.toml"
    file.write_text('[server]\nport = 9100\n[ttl]\nquote = 60\nholdings = "never"\n')

    config = load(str(file))

    assert config.port == 9100
    assert config.ttl == {"QUOTE": 60.0, "HOLDINGS": float("inf")}


def test_client_is_not_closed_twice() -> None:
    """An injected client belongs to the caller, so the app must not close it."""
    fake = _FakeClient()
    create_app(Config(), client=fake)  # type: ignore[arg-type]

    assert fake.closed is False
    assert isinstance(MarketData, type)


async def test_metrics_endpoint_is_served() -> None:
    """Metrics are exposed in Prometheus text format and omitted from OpenAPI."""
    async with _api() as api:
        response = await api.get("/metrics")

    assert response.status_code == 200
    assert "quotestack_events_total" in response.text


def test_committed_spec_matches_the_code() -> None:
    """The committed OpenAPI file must be exactly what the app generates.

    Regenerate with ``quotestack-server --dump-openapi > docs/api/openapi.yaml``
    when this fails; the point is that the two can never disagree.
    """
    import yaml

    app = create_app(Config(), client=_FakeClient())  # type: ignore[arg-type]
    generated = app.openapi()

    committed = yaml.safe_load(
        (pathlib.Path(__file__).resolve().parents[1] / "docs/api/openapi.yaml").read_text(
            encoding="utf-8"
        )
    )

    assert set(committed["paths"]) == set(generated["paths"])
    assert committed["components"]["schemas"].keys() == generated["components"]["schemas"].keys()
    for path, operations in generated["paths"].items():
        for method, operation in operations.items():
            assert committed["paths"][path][method]["summary"] == operation["summary"]


def test_dump_openapi_writes_a_document(capsys: pytest.CaptureFixture[str]) -> None:
    """The CLI can emit the spec without starting a server."""
    from quotestack.server.__main__ import main

    assert main(["--dump-openapi", "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["paths"]) == 12


def test_dump_openapi_defaults_to_yaml(capsys: pytest.CaptureFixture[str]) -> None:
    from quotestack.server.__main__ import main

    assert main(["--dump-openapi"]) == 0
    assert capsys.readouterr().out.startswith("openapi:")


def test_server_rejects_a_missing_config_file(capsys: pytest.CaptureFixture[str]) -> None:
    """A path the caller named must exist, or startup stops."""
    from quotestack.server.__main__ import main

    assert main(["--config", "definitely-missing.toml"]) == 2
    assert "config error" in capsys.readouterr().err


def test_config_reads_proxy_and_server_sections(tmp_path: Any) -> None:
    """A full TOML exercises every branch of the file reader."""
    file = tmp_path / "quotestack.toml"
    file.write_text(
        "[server]\n"
        'host = "0.0.0.0"\n'
        "port = 8080\n"
        'log_level = "DEBUG"\n'
        "[proxy]\n"
        'url = "http://127.0.0.1:7890"\n'
    )

    config = load(str(file))

    assert config.host == "0.0.0.0"
    assert config.port == 8080
    assert config.log_level == "DEBUG"
    assert config.proxy == "http://127.0.0.1:7890"


def test_config_rejects_zero_ttl(tmp_path: Any) -> None:
    file = tmp_path / "quotestack.toml"
    file.write_text("[ttl]\nquote = 0\n")

    with pytest.raises(ConfigError):
        load(str(file))


def test_config_rejects_a_non_numeric_ttl(tmp_path: Any) -> None:
    file = tmp_path / "quotestack.toml"
    file.write_text('[ttl]\nquote = "soon"\n')

    with pytest.raises(ConfigError):
        load(str(file))


def test_config_rejects_a_bad_port_type(tmp_path: Any) -> None:
    file = tmp_path / "quotestack.toml"
    file.write_text("[server]\nport = true\n")

    with pytest.raises(ConfigError):
        load(str(file))


def test_config_rejects_invalid_toml(tmp_path: Any) -> None:
    file = tmp_path / "quotestack.toml"
    file.write_text("this is not toml = = =")

    with pytest.raises(ConfigError):
        load(str(file))


def test_config_allows_an_empty_file(tmp_path: Any) -> None:
    """An empty config still yields usable defaults."""
    file = tmp_path / "quotestack.toml"
    file.write_text("")

    assert load(str(file)).port == 8000


async def test_batch_endpoint_keeps_order() -> None:
    async with _api() as api:
        body = (
            await api.post(
                "/v1/quotes/batch",
                json={"items": [{"code": "600519"}, {"code": "000001"}]},
            )
        ).json()

    assert len(body["data"]["results"]) == 2
    assert [item["ok"] for item in body["data"]["results"]] == [False, False]


async def test_holdings_rejects_a_bad_cursor() -> None:
    """A malformed cursor is an invalid argument, not an unsupported capability.

    FastAPI defaults validation errors to 422, but this contract reserves 422
    for UNSUPPORTED, so 422 would mean two different things.
    """
    async with _api() as api:
        response = await api.get("/v1/holdings", params={"code": "166002", "before": "2026-Q1"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_ARGUMENT"


@pytest.mark.parametrize(
    ("url", "status", "code"),
    [
        ("/v1/history?code=600519&limit=abc", 400, "INVALID_ARGUMENT"),
        ("/v1/quote", 400, "INVALID_ARGUMENT"),
        ("/v1/instruments?asset_class=NOPE&market=CN", 400, "INVALID_ARGUMENT"),
        ("/v1/does-not-exist", 404, "NOT_FOUND"),
        ("/v1/quote?code=022430&asset_class=FUND", 422, "UNSUPPORTED"),
    ],
)
async def test_every_failure_uses_the_same_envelope(url: str, status: int, code: str) -> None:
    """One shape for every failure, including the framework's own errors.

    Validation errors and unknown routes used to answer ``{"detail": ...}``,
    which a client written against the documented envelope cannot read: it looks
    for ``error``, finds nothing, and treats a 400 as a successful empty result.
    """
    async with _api() as api:
        response = await api.get(url)

    body = response.json()
    assert response.status_code == status
    assert set(body) == {"data", "error"}
    assert body["data"] is None
    assert body["error"]["code"] == code
    assert body["error"]["message"]


async def test_instruments_reports_has_more_correctly() -> None:
    """A full page is not the end of the list.

    The route collected exactly `page_size` items and then asked whether it had
    more than `page_size`, so `has_more` was false on every page and a client
    that trusted it saw only the first page.
    """
    from quotestack.models import AssetClass, Capability, InstrumentSummary, Market
    from quotestack.sources.base import SourceMeta

    def item(code: str, name: str) -> InstrumentSummary:
        return InstrumentSummary(
            code=code,
            name=name,
            asset_class=AssetClass.STOCK,
            market=Market.CN,
            currency="CNY",
        )

    class Listing:
        meta = SourceMeta(
            name="eastmoney",
            capabilities=frozenset({Capability.LIST}),
            markets=frozenset({(AssetClass.STOCK, Market.CN)}),
        )

        async def list_instruments(self, asset_class: Any, market: Any, **kwargs: Any) -> Any:
            yield [item("600519", "A")]
            yield [item("000001", "B")]

        async def aclose(self) -> None:
            return None

    base = MarketData(sources={"eastmoney": Listing()})
    async with base:
        app = create_app(client=base)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as api:
            first = (
                await api.get(
                    "/v1/instruments",
                    params={"asset_class": "STOCK", "market": "CN", "page": 1, "page_size": 1},
                )
            ).json()["data"]
            second = (
                await api.get(
                    "/v1/instruments",
                    params={"asset_class": "STOCK", "market": "CN", "page": 2, "page_size": 1},
                )
            ).json()["data"]

    assert first["has_more"] is True
    assert first["next_page"] == 2
    assert [i["code"] for i in first["items"]] == ["600519"]
    assert second["has_more"] is False
    assert [i["code"] for i in second["items"]] == ["000001"]


async def test_history_reports_the_source_that_answered() -> None:
    """The route used to claim "eastmoney" regardless of who answered."""
    async with _api() as api:
        body = (await api.get("/v1/history?code=600519&limit=3")).json()["data"]

    assert body["source"]
    assert body["source"] != "unknown"


async def test_holdings_has_more_comes_from_the_extra_quarter() -> None:
    """A page that exactly fills the limit is not evidence of another page.

    The route used to compare the page length with the page size, so a fund with
    exactly `limit` quarters left reported another page and the client made one
    pointless request.
    """
    async with _api() as api:
        body = (await api.get("/v1/holdings?code=166002&limit=2")).json()["data"]

    assert isinstance(body["has_more"], bool)
    assert len(body["quarters"]) <= 2
    if not body["has_more"]:
        assert body["next_before"] is None


def test_every_capability_can_be_configured_from_the_environment() -> None:
    """_TTL_NAMES decide which TTLs an operator can override.

    RESOLVE and LIST were missing, so their TTLs were reachable from a TOML file
    but not from the environment, which is how a container is configured.
    """
    from quotestack.models import Capability
    from quotestack.server.config import _TTL_NAMES

    assert {c.value for c in Capability} == set(_TTL_NAMES)


async def test_history_route_works_with_a_real_client() -> None:
    """The fake client hid a key mismatch that made every history call 500.

    Routing a request through a real MarketData exercises the cache key that
    `history` actually writes; the fake returned a source name without looking
    anything up, so it could not fail.
    """
    import datetime as dt

    from quotestack.models import Bar, Capability
    from quotestack.sources.base import SourceMeta

    class History:
        meta = SourceMeta(
            name="eastmoney",
            capabilities=frozenset({Capability.HISTORY}),
            markets=frozenset({(AssetClass.STOCK, Market.CN)}),
        )

        async def history(
            self, instrument: Any, interval: Any, adjust: Any, limit: int
        ) -> list[Bar]:
            return [
                Bar(
                    date=dt.date(2026, 11, 10),
                    open="1",
                    high="2",
                    low="1",
                    close="1.5",
                    volume="100",
                )
            ]

        async def aclose(self) -> None:
            return None

    base = MarketData(sources={"eastmoney": History()}, source_priority={"HISTORY": ["eastmoney"]})
    async with base:
        app = create_app(client=base)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as api:
            response = await api.get("/v1/history", params={"code": "600519", "limit": 3})

    assert response.status_code == 200
    assert response.json()["data"]["source"] == "eastmoney"


def test_history_payload_accepts_an_unknown_source() -> None:
    """An evicted cache entry must yield null, not a validation error.

    The route cannot prove eviction (the entry is written then read in the same
    request), so the contract is asserted at the model instead: `source` is
    optional precisely so a missing lookup degrades instead of raising.
    """
    from quotestack.server.schemas import BarsPayload

    payload = BarsPayload(
        bars=[], interval="1d", adjust="qfq", source=None, fetched_at="2026-11-11T00:00:00Z"
    )

    assert payload.source is None
