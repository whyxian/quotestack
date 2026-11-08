"""Response models for the HTTP layer.

These mirror the library dataclasses but exist separately because HTTP has two
extra jobs: it must declare the envelope, and it must give FastAPI enough type
information to emit an accurate OpenAPI document.
"""

from __future__ import annotations

from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "Bar",
    "BarsPayload",
    "BarsResponse",
    "BatchPayload",
    "BatchRequest",
    "BatchRequestItem",
    "BatchResponse",
    "BenchmarkComponentModel",
    "BenchmarkModel",
    "BenchmarkPayload",
    "BenchmarkPointModel",
    "BenchmarkResponse",
    "CurveComponentModel",
    "ErrorBody",
    "ErrorResponse",
    "EstimateModel",
    "EstimateResponse",
    "FxModel",
    "FxResponse",
    "HealthPayload",
    "HealthResponse",
    "HoldingModel",
    "HoldingsPayload",
    "HoldingsResponse",
    "InstrumentModel",
    "InstrumentResponse",
    "InstrumentSummaryModel",
    "ListingPayload",
    "ListingResponse",
    "NavPayload",
    "NavPointModel",
    "NavResponse",
    "ProfileModel",
    "ProfileResponse",
    "QuarterModel",
    "QuoteModel",
    "QuoteResponse",
    "QuoteResultModel",
]

T = TypeVar("T")


class _Model(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class ErrorBody(_Model):
    """A failure a caller can branch on."""

    code: str = Field(description="Stable error code, safe to switch on")
    message: str
    detail: dict[str, object] = Field(default_factory=dict)


class ErrorResponse(_Model):
    data: None = None
    error: ErrorBody


class _Envelope(_Model, Generic[T]):
    """Shared success shape: data present, error explicitly null."""

    data: T
    error: None = None


class InstrumentModel(_Model):
    id: str
    code: str
    asset_class: Literal["STOCK", "FUND", "CRYPTO"]
    market: Literal["CN", "US", "CRYPTO"]
    currency: str
    source_name: str | None = None
    confidence: Literal["exact", "inferred", "partial"]
    aliases: dict[str, str] = Field(default_factory=dict)
    capabilities: list[str] = Field(default_factory=list)


class QuoteModel(_Model):
    instrument_id: str
    price: str = Field(description="十进制字符串，不是数字。金额不能有浮点误差")
    currency: str
    change: str | None = None
    change_pct: float | None = Field(
        default=None, description="涨跌幅百分数值，-1.76 表示 -1.76%"
    )
    source: str
    ts: str = Field(description="RFC3339 带时区偏移的观测时刻")
    status: Literal["REALTIME", "HISTORICAL", "UNAVAILABLE"]
    stale: bool = False


class BarModel(_Model):
    date: str
    time: str | None = None
    open: str
    high: str
    low: str
    close: str
    volume: str = Field(description="成交量，十进制字符串")
    amount: str | None = None


class NavPointModel(_Model):
    date: str
    nav: str


class BenchmarkComponentModel(_Model):
    name: str
    weight: float
    kind: Literal["EQUITY", "NON_EQUITY", "UNKNOWN"]


class BenchmarkModel(_Model):
    text: str
    components: list[BenchmarkComponentModel]
    coverage: float = Field(description="权重合计 / 100，小于 1 说明权重不全")


class ProfileModel(_Model):
    fund_type: str | None = None
    fund_class: Literal["EQUITY", "HYBRID", "BOND", "MONEY", "FOF", "REITS", "OTHER"] | None = None
    tracking_index: str | None = None
    benchmark: BenchmarkModel | None = None
    company: str | None = None
    manager: str | None = None
    custodian: str | None = None
    scale: str | None = None
    inception_date: str | None = None
    as_of: str | None = None
    partial: bool = False
    missing: list[str] = Field(default_factory=list)


class HoldingModel(_Model):
    code: str
    name: str
    weight: float


class QuarterModel(_Model):
    quarter: str
    as_of: str
    holdings: list[HoldingModel]


class CurveComponentModel(_Model):
    name: str
    weight: float
    kind: str


class BenchmarkPointModel(_Model):
    date: str
    value: float


class EstimateModel(_Model):
    change_pct: float | None = Field(
        default=None,
        description="Null when the estimate cannot be computed; zero means truly unchanged",
    )
    basis: Literal["index", "holdings", "none"]
    coverage: float | None = None
    as_of: str | None = None
    explanation: str = ""
    benchmark_assumption: dict[str, list[str]] | None = None


class FxModel(_Model):
    base: str
    quote: str
    rate: str = Field(description="汇率，十进制字符串")
    source: str
    as_of: str
    derived: bool


class InstrumentSummaryModel(_Model):
    code: str
    name: str
    asset_class: Literal["STOCK", "FUND", "CRYPTO"]
    market: Literal["CN", "US", "CRYPTO"]
    currency: str
    listing_date: str | None = None
    board: str | None = None
    industry: str | None = None
    fund_type: str | None = None
    fund_class: str | None = None


class QuoteResultModel(_Model):
    ok: bool
    instrument: InstrumentModel | None = None
    quote: QuoteModel | None = None
    error: str | None = None


# --- per-endpoint envelopes -------------------------------------------------


class InstrumentResponse(_Envelope[InstrumentModel]): ...


class QuoteResponse(_Envelope[QuoteModel]): ...


class BarsPayload(_Model):
    bars: list[BarModel]
    interval: str
    adjust: str
    source: str
    fetched_at: str


class BarsResponse(_Envelope[BarsPayload]): ...


class NavPayload(_Model):
    points: list[NavPointModel]
    latest: NavPointModel
    source: str
    fetched_at: str


class NavResponse(_Envelope[NavPayload]): ...


class ProfileResponse(_Envelope[ProfileModel]): ...


class HoldingsPayload(_Model):
    quarters: list[QuarterModel]
    has_more: bool
    next_before: str | None = None


class HoldingsResponse(_Envelope[HoldingsPayload]): ...


class BenchmarkPayload(_Model):
    effective_start: str | None = None
    components_used: list[CurveComponentModel]
    components_dropped: list[str]
    coverage: float
    series: list[BenchmarkPointModel]


class BenchmarkResponse(_Envelope[BenchmarkPayload]): ...


class EstimateResponse(_Envelope[EstimateModel]): ...


class FxResponse(_Envelope[FxModel]): ...


class BatchRequestItem(_Model):
    code: str
    asset_class: Literal["STOCK", "FUND", "CRYPTO"] = "STOCK"
    market: Literal["CN", "US", "CRYPTO"] = "CN"


class BatchRequest(_Model):
    items: Annotated[list[BatchRequestItem], Field(min_length=1, max_length=200)]


class BatchPayload(_Model):
    results: list[QuoteResultModel]
    fetched_at: str


class BatchResponse(_Envelope[BatchPayload]): ...


class ListingPayload(_Model):
    items: list[InstrumentSummaryModel]
    page: int
    page_size: int
    has_more: bool
    next_page: int | None = None


class ListingResponse(_Envelope[ListingPayload]): ...


class HealthPayload(_Model):
    status: Literal["ok", "degraded"]
    config: dict[str, object]
    sources: dict[str, object]
    cache: dict[str, int]
    recent_schema_changes: list[str] = Field(default_factory=list)


class HealthResponse(_Envelope[HealthPayload]): ...


Bar = BarModel
