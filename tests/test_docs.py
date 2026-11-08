"""Contract tests that keep documentation honest about capabilities.

These do not check prose, only the tables a reader would trust at face value.
"""

from __future__ import annotations

import pathlib
import re

from quotestack.identity import resolve
from quotestack.models import AssetClass, Capability, Market
from quotestack.sources import (
    BinanceSource,
    EastMoneySource,
    FxSource,
    TencentSource,
    TiantianSource,
)

_DOC = pathlib.Path(__file__).resolve().parents[1] / "docs" / "design" / "03-sources.md"

_NAMES = {
    "东方财富": "eastmoney",
    "腾讯": "tencent",
    "天天基金": "tiantian",
    "Binance": "binance",
    "东财外汇": "eastmoney-fx",
}


def _section(start: str, end: str) -> str:
    text = _DOC.read_text(encoding="utf-8")
    return text[text.index(start) : text.index(end)]


def test_source_capability_table_matches_the_code() -> None:
    """The selection table must not drift from SourceMeta."""
    real = {
        source.meta.name: {capability.value for capability in source.meta.capabilities}
        for source in (
            EastMoneySource(),
            TencentSource(),
            TiantianSource(),
            BinanceSource(),
            FxSource(),
        )
    }
    section = _section("## 1. 选型结果", "## 1.1 能力字典")

    seen = 0
    for line in section.splitlines():
        if not line.startswith("| **"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        source = _NAMES.get(cells[0].strip("* "))
        if source is None:
            continue
        documented = set(re.findall(r"`([A-Z]+)`", cells[2]))
        assert documented == real[source], f"{source} table drifted"
        seen += 1

    assert seen == len(_NAMES), "every source needs a row"


def test_every_capability_appears_in_the_dictionary() -> None:
    """A capability with no explanation is a term the reader cannot decode."""
    section = _section("## 1.1 能力字典", "## 2. 东方财富")

    for capability in Capability:
        assert f"`{capability.value}`" in section, f"{capability.value} is undocumented"


def test_documented_instrument_capabilities_match_the_resolver() -> None:
    """The per-instrument example must be reproducible from the code."""
    section = _section("### 不同标的的能力不同", "## 2. 东方财富")

    cases = {
        "CN:STOCK:600519": ("600519", AssetClass.STOCK, Market.CN),
        "CN:FUND:510010": ("510010", AssetClass.FUND, Market.CN),
        "CN:FUND:022430": ("022430", AssetClass.FUND, Market.CN),
        "US:STOCK:AAPL": ("AAPL", AssetClass.STOCK, Market.US),
    }
    for line in section.splitlines():
        if not line.startswith("| `"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        identifier = cells[0].strip("`")
        if identifier not in cases:
            continue
        code, asset_class, market = cases[identifier]
        expected = {c.value for c in resolve(code, asset_class, market).capabilities}
        documented = set(re.findall(r"`([A-Z]+)`", cells[1]))
        assert documented == expected, f"{identifier} drifted"
