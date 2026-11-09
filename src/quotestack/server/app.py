"""FastAPI application.

The HTTP layer is deliberately thin: it converts arguments, calls one library
method, and serialises the result. Every rule about caching, fallback and
estimation already lives in the library, and duplicating any of it here would
create a second place to keep correct.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Query, Request

from quotestack.client import MarketData
from quotestack.logging import event, get_logger
from quotestack.models import (
    Adjust,
    AssetClass,
    Capability,
    EstimateBasis,
    FundClass,
    Interval,
    Market,
)
from quotestack.server import errors, metrics
from quotestack.server.config import Config, load
from quotestack.server.schemas import (
    BarModel,
    BarsResponse,
    BatchRequest,
    BatchResponse,
    BenchmarkComponentModel,
    BenchmarkModel,
    BenchmarkPointModel,
    BenchmarkResponse,
    CurveComponentModel,
    ErrorResponse,
    EstimateModel,
    EstimateResponse,
    FxModel,
    FxResponse,
    HealthPayload,
    HealthResponse,
    HoldingModel,
    HoldingsResponse,
    InstrumentModel,
    InstrumentResponse,
    InstrumentSummaryModel,
    ListingPayload,
    ListingResponse,
    NavPointModel,
    NavResponse,
    ProfileModel,
    ProfileResponse,
    QuarterModel,
    QuoteModel,
    QuoteResponse,
    QuoteResultModel,
)

_log = get_logger("server")

__all__ = ["ERROR_RESPONSES", "create_app"]

# Declared on every data route so the generated contract tells a client which
# failures to expect. Without this FastAPI documents only the success shape,
# and code generators produce clients that cannot express an error.
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse, "description": "参数不合法"},
    404: {"model": ErrorResponse, "description": "代码不存在或已退市"},
    409: {"model": ErrorResponse, "description": "代码有多个候选"},
    410: {"model": ErrorResponse, "description": "已退市"},
    422: {"model": ErrorResponse, "description": "该标的不支持此能力"},
    429: {"model": ErrorResponse, "description": "触发上游限流"},
    502: {"model": ErrorResponse, "description": "上游失败"},
    500: {"model": ErrorResponse, "description": "服务内部错误"},
    503: {"model": ErrorResponse, "description": "所有源结构变更，需升级"},
    504: {"model": ErrorResponse, "description": "上游超时"},
}

_MAX_LIMIT = 5000


def create_app(config: Config | None = None, client: MarketData | None = None) -> FastAPI:
    """Build the application.

    Args:
        config: Runtime configuration. Loaded from disk when omitted.
        client: Pre-built client, mainly for tests.

    Returns:
        A configured :class:`FastAPI` instance.
    """
    settings = config or load()

    owned = client is None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if client is None:
            app.state.client = _build_client(settings)
        event(
            _log,
            logging.INFO,
            "startup",
            sources=len(getattr(app.state.client, "_sources", {})),
            hint="service ready",
        )
        try:
            yield
        finally:
            if owned:
                await app.state.client.aclose()

    app = FastAPI(
        title="quotestack API",
        version="0.1.0",
        summary="多源行情适配层",
        lifespan=lifespan,
    )
    # Set eagerly so an injected client works even when the ASGI transport does
    # not run the lifespan, which is the case in tests.
    app.state.config = settings
    if client is not None:
        app.state.client = client

    errors.install(app)
    _register(app)
    if _metrics_enabled():
        metrics.install(app)
    return app


def _metrics_enabled() -> bool:
    """Metrics are on unless the prometheus client is unavailable."""
    return importlib.util.find_spec("prometheus_client") is not None


def _build_client(settings: Config) -> MarketData:
    ttl = {
        capability: settings.ttl[capability.value]
        for capability in Capability
        if capability.value in settings.ttl
    }
    return MarketData(ttl=ttl or None, proxy=settings.proxy)


def _client(request: Request) -> MarketData:
    client: MarketData = request.app.state.client
    return client


Client = Annotated[MarketData, Depends(_client)]

Code = Annotated[str, Query(min_length=1, max_length=24)]
ClassParam = Annotated[AssetClass, Query()]
VenueParam = Annotated[Market, Query()]


def _register(app: FastAPI) -> None:
    """Attach every route.

    Args:
        app: The application to extend.
    """

    @app.get(
        "/v1/resolve",
        responses=ERROR_RESPONSES,
        summary="解析代码",
        description="把代码解析成内部标识，并返回各数据源的映射。纯规则解析，不发起网络请求。",
        response_model=InstrumentResponse,
        tags=["instrument"],
    )
    async def resolve(
        client: Client,
        code: Code,
        asset_class: ClassParam = AssetClass.STOCK,
        market: VenueParam = Market.CN,
    ) -> dict[str, Any]:
        return {"data": _instrument(client.resolve(code, asset_class, market))}

    @app.get(
        "/v1/quote",
        responses=ERROR_RESPONSES,
        summary="实时报价",
        description="返回单个标的的最新报价。上游失败且缓存仍在 max_stale 窗口内时，返回旧值并把 stale 置为 true。",
        response_model=QuoteResponse,
        tags=["market"],
    )
    async def quote(
        client: Client,
        code: Code,
        asset_class: ClassParam = AssetClass.STOCK,
        market: VenueParam = Market.CN,
        max_age: Annotated[int | None, Query(ge=0)] = None,
    ) -> dict[str, Any]:
        result = await client.quote(code, asset_class, market, max_age=max_age)
        return {"data": _quote(result)}

    @app.post(
        "/v1/quotes/batch",
        responses=ERROR_RESPONSES,
        summary="批量报价",
        description="一次查询多个标的。返回列表与请求等长同序，单条失败不影响其余。",
        response_model=BatchResponse,
        tags=["market"],
    )
    async def quote_many(client: Client, body: BatchRequest) -> dict[str, Any]:
        items = [
            (item.code, AssetClass(item.asset_class), Market(item.market)) for item in body.items
        ]
        results = await client.quote_many(items)
        return {
            "data": {
                "results": [_quote_result(result) for result in results],
                "fetched_at": _now(),
            }
        }

    @app.get(
        "/v1/history",
        responses=ERROR_RESPONSES,
        summary="K 线与分钟线",
        description="场外基金没有 K 线，请求它们返回 UNSUPPORTED，而不是空数组。",
        response_model=BarsResponse,
        tags=["market"],
    )
    async def history(
        client: Client,
        code: Code,
        asset_class: ClassParam = AssetClass.STOCK,
        market: VenueParam = Market.CN,
        interval: Annotated[Interval, Query()] = Interval.D1,
        adjust: Annotated[Adjust, Query()] = Adjust.QFQ,
        limit: Annotated[int, Query(ge=1, le=_MAX_LIMIT)] = 250,
        max_age: Annotated[int | None, Query(ge=0)] = None,
    ) -> dict[str, Any]:
        bars = await client.history(
            code,
            asset_class,
            market,
            interval=interval,
            adjust=adjust,
            limit=limit,
            max_age=max_age,
        )
        return {
            "data": {
                "bars": [_bar(bar) for bar in bars],
                "interval": interval.value,
                "adjust": adjust.value,
                "source": client.source_for(
                    Capability.HISTORY, client.resolve(code, asset_class, market).id
                ),
                "fetched_at": _now(),
            }
        }

    @app.get(
        "/v1/nav",
        responses=ERROR_RESPONSES,
        summary="基金净值",
        description="场外基金只有每日净值，没有盘中报价。",
        response_model=NavResponse,
        tags=["fund"],
    )
    async def nav(
        client: Client,
        code: Code,
        asset_class: ClassParam = AssetClass.FUND,
        market: VenueParam = Market.CN,
        limit: Annotated[int, Query(ge=1, le=_MAX_LIMIT)] = 250,
        max_age: Annotated[int | None, Query(ge=0)] = None,
    ) -> dict[str, Any]:
        points = await client.nav(code, asset_class, market, limit=limit, max_age=max_age)
        latest = points[-1]
        return {
            "data": {
                "points": [_nav_point(point) for point in points],
                "latest": _nav_point(latest),
                "source": client.source_for(
                    Capability.NAV, client.resolve(code, asset_class, market).id
                ),
                "fetched_at": _now(),
            }
        }

    @app.get(
        "/v1/profile",
        responses=ERROR_RESPONSES,
        summary="基金画像",
        description="基金类型、跟踪标的、业绩基准、规模、经理。",
        response_model=ProfileResponse,
        tags=["fund"],
    )
    async def profile(
        client: Client,
        code: Code,
        asset_class: ClassParam = AssetClass.FUND,
        market: VenueParam = Market.CN,
    ) -> dict[str, Any]:
        result = await client.profile(code, asset_class, market)
        return {"data": _profile(result)}

    @app.get(
        "/v1/holdings",
        responses=ERROR_RESPONSES,
        summary="季度持仓",
        description="按季度倒序返回前十大重仓股。limit 是季度数，不是股票数。",
        response_model=HoldingsResponse,
        tags=["fund"],
    )
    async def holdings(
        client: Client,
        code: Code,
        asset_class: ClassParam = AssetClass.FUND,
        market: VenueParam = Market.CN,
        before: Annotated[str | None, Query(pattern=r"^\d{4}Q[1-4]$")] = None,
        limit: Annotated[int, Query(ge=1, le=40)] = 4,
    ) -> dict[str, Any]:
        # Ask for one more than the page so its existence answers `has_more`.
        # Comparing the page length with the page size reported a next page
        # whenever the result happened to fill the page exactly, so a client
        # following the cursor made one pointless request per fund.
        fetched = await client.holdings(code, asset_class, market, before=before, limit=limit + 1)
        has_more = len(fetched) > limit
        quarters = fetched[:limit]
        return {
            "data": {
                "quarters": [_quarter(quarter) for quarter in quarters],
                "has_more": has_more,
                "next_before": quarters[-1].quarter if has_more and quarters else None,
            }
        }

    @app.get(
        "/v1/benchmark",
        responses=ERROR_RESPONSES,
        summary="基准加权曲线",
        description="把业绩基准里的成分指数按权重加权。取不到数据的成分被剔除并报告，coverage 相应下降。",
        response_model=BenchmarkResponse,
        tags=["fund"],
    )
    async def benchmark(
        client: Client,
        code: Code,
        asset_class: ClassParam = AssetClass.FUND,
        market: VenueParam = Market.CN,
        start: Annotated[dt.date | None, Query()] = None,
        end: Annotated[dt.date | None, Query()] = None,
    ) -> dict[str, Any]:
        curve = await client.benchmark(code, asset_class, market, start=start, end=end)
        return {
            "data": {
                "effective_start": curve.effective_start.isoformat()
                if curve.effective_start
                else None,
                "components_used": [
                    CurveComponentModel(name=c.name, weight=c.weight, kind=c.kind.value)
                    for c in curve.components_used
                ],
                "components_dropped": list(curve.components_dropped),
                "coverage": curve.coverage,
                "series": [
                    BenchmarkPointModel(date=point.date.isoformat(), value=point.value)
                    for point in curve.series
                ],
            }
        }

    @app.get(
        "/v1/estimate",
        responses=ERROR_RESPONSES,
        summary="基金盘中估值",
        description="用跟踪指数或持仓推算当日涨跌。算不出来时返回 change_pct=null，不是 0——未知与零变化是两件事。",
        response_model=EstimateResponse,
        tags=["fund"],
    )
    async def estimate(
        client: Client,
        code: Code,
        asset_class: ClassParam = AssetClass.FUND,
        market: VenueParam = Market.CN,
    ) -> dict[str, Any]:
        result = await client.estimate(code, asset_class, market)
        assumption = result.benchmark_assumption
        return {
            "data": EstimateModel(
                change_pct=result.change_pct,
                basis=result.basis.value,
                coverage=result.coverage,
                as_of=result.as_of.isoformat() if result.as_of else None,
                explanation=result.explanation,
                benchmark_assumption=(
                    {
                        "equity": list(assumption.equity),
                        "non_equity": list(assumption.non_equity),
                        "unclassified": list(assumption.unclassified),
                    }
                    if assumption
                    else None
                ),
            ).model_dump()
        }

    @app.get(
        "/v1/fx",
        responses=ERROR_RESPONSES,
        summary="汇率",
        description="以 USD 为基准表做交叉换算，derived 标记该汇率是直接报价还是算出来的。",
        response_model=FxResponse,
        tags=["market"],
    )
    async def fx(
        client: Client,
        base: Annotated[str, Query(pattern=r"^[A-Za-z]{3}$")],
        quote: Annotated[str, Query(pattern=r"^[A-Za-z]{3}$")],
    ) -> dict[str, Any]:
        rate = await client.fx(base.upper(), quote.upper())
        return {
            "data": FxModel(
                base=rate.base,
                quote=rate.quote,
                rate=rate.rate,
                source=rate.source,
                as_of=rate.as_of.isoformat(),
                derived=rate.derived,
            ).model_dump()
        }

    @app.get(
        "/v1/instruments",
        responses=ERROR_RESPONSES,
        summary="市场列表",
        description="枚举一个市场的全部标的。列表只含静态元数据，不含行情。",
        response_model=ListingResponse,
        tags=["instrument"],
    )
    async def instruments(
        client: Client,
        asset_class: Annotated[AssetClass, Query()],
        market: Annotated[Market, Query()],
        listed: Annotated[bool | None, Query()] = None,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=500)] = 100,
        tradable_only: Annotated[bool, Query()] = True,
    ) -> dict[str, Any]:
        items: list[InstrumentSummaryModel] = []
        skipped = 0
        # Collect one past the page boundary: its presence is what says there is
        # another page. Stopping exactly at the boundary makes `has_more` a
        # comparison of a list with its own length, which is always false.
        target = page * page_size + 1
        async for batch in client.iter_instruments(
            asset_class,
            market,
            listed=listed,
            page_size=page_size,
            tradable_only=tradable_only,
        ):
            for summary in batch:
                if skipped < (page - 1) * page_size:
                    skipped += 1
                    continue
                items.append(_summary(summary))
            if skipped + len(items) >= target:
                break

        return {
            "data": ListingPayload(
                items=items[:page_size],
                page=page,
                page_size=page_size,
                has_more=len(items) > page_size,
                next_page=page + 1 if len(items) > page_size else None,
            ).model_dump()
        }

    @app.get(
        "/v1/healthz",
        summary="运行状态",
        description="报告各源可用性、冷却状态、缓存占用，以及当前生效的配置。",
        response_model=HealthResponse,
        tags=["ops"],
    )
    async def healthz(client: Client) -> dict[str, Any]:
        state = client.health()
        payload = HealthPayload(
            status="degraded" if state["status"] == "degraded" else "ok",
            config={"ttl": _ttl_report(app.state.config)},
            sources=dict(state["sources"]) if isinstance(state["sources"], dict) else {},
            cache=dict(state["cache"]) if isinstance(state["cache"], dict) else {},
        )
        return {"data": payload.model_dump()}


def _ttl_report(config: Config) -> dict[str, object]:
    return {
        name: ("never" if value == float("inf") else value) for name, value in config.ttl.items()
    }


def _now() -> str:
    return dt.datetime.now().astimezone().isoformat()


def _instrument(instrument: Any) -> dict[str, Any]:
    return InstrumentModel(
        id=instrument.id,
        code=instrument.code,
        asset_class=instrument.asset_class.value,
        market=instrument.market.value,
        currency=instrument.currency,
        source_name=instrument.source_name,
        confidence=instrument.confidence.value,
        aliases=dict(instrument.aliases),
        capabilities=sorted(capability.value for capability in instrument.capabilities),
    ).model_dump()


def _quote(quote: Any) -> dict[str, Any]:
    return QuoteModel(
        instrument_id=quote.instrument_id,
        price=quote.price,
        currency=quote.currency,
        change=quote.change,
        change_pct=quote.change_pct,
        source=quote.source,
        ts=quote.ts.isoformat(),
        status=quote.status.value,
        stale=quote.stale,
    ).model_dump()


def _quote_result(result: Any) -> QuoteResultModel:
    return QuoteResultModel(
        ok=result.ok,
        instrument=(
            InstrumentModel(**_instrument(result.instrument)) if result.instrument else None
        ),
        quote=QuoteModel(**_quote(result.quote)) if result.quote else None,
        error=result.error,
    )


def _bar(bar: Any) -> BarModel:
    return BarModel(
        date=bar.date.isoformat(),
        time=bar.time,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
        amount=bar.amount,
    )


def _nav_point(point: Any) -> NavPointModel:
    return NavPointModel(date=point.date.isoformat(), nav=point.nav)


def _profile(profile: Any) -> ProfileModel:
    benchmark = profile.benchmark
    return ProfileModel(
        fund_type=profile.fund_type,
        fund_class=profile.fund_class.value if profile.fund_class else None,
        tracking_index=profile.tracking_index,
        benchmark=(
            BenchmarkModel(
                text=benchmark.text,
                components=[
                    BenchmarkComponentModel(name=c.name, weight=c.weight, kind=c.kind.value)
                    for c in benchmark.components
                ],
                coverage=benchmark.coverage,
            )
            if benchmark
            else None
        ),
        company=profile.company,
        manager=profile.manager,
        custodian=profile.custodian,
        scale=profile.scale,
        inception_date=profile.inception_date.isoformat() if profile.inception_date else None,
        as_of=profile.as_of.isoformat() if profile.as_of else None,
        partial=profile.partial,
        missing=list(profile.missing),
    )


def _quarter(quarter: Any) -> QuarterModel:
    return QuarterModel(
        quarter=quarter.quarter,
        as_of=quarter.as_of.isoformat(),
        holdings=[
            HoldingModel(code=h.code, name=h.name, weight=h.weight) for h in quarter.holdings
        ],
    )


def _summary(summary: Any) -> InstrumentSummaryModel:
    return InstrumentSummaryModel(
        code=summary.code,
        name=summary.name,
        asset_class=summary.asset_class.value,
        market=summary.market.value,
        currency=summary.currency,
        listing_date=summary.listing_date.isoformat() if summary.listing_date else None,
        board=summary.board,
        industry=summary.industry,
        fund_type=summary.fund_type,
        fund_class=summary.fund_class.value if summary.fund_class else None,
    )


# Referenced by tests to keep the enum imports meaningful across refactors.
_UNUSED = (EstimateBasis, FundClass)
