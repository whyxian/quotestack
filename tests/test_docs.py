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


def test_sources_declare_list_when_they_implement_it() -> None:
    """A source that can enumerate a market must say so.

    The capability list is what routing and health reporting read, so a source
    that implements ``list_instruments`` but hides the capability looks, from
    the outside, like it cannot list anything.
    """
    for source in (
        EastMoneySource(),
        TencentSource(),
        TiantianSource(),
        BinanceSource(),
        FxSource(),
    ):
        implements = hasattr(source, "list_instruments")
        declares = Capability.LIST in source.meta.capabilities
        assert implements == declares, f"{source.meta.name} disagrees with itself"


def test_guide_status_table_matches_the_spec() -> None:
    """The status codes the guide lists must be the ones the API can return."""
    import yaml

    root = pathlib.Path(__file__).resolve().parents[1]
    spec = yaml.safe_load((root / "docs/api/openapi.yaml").read_text(encoding="utf-8"))
    documented = set()
    for operations in spec["paths"].values():
        for operation in operations.values():
            documented.update(
                int(code)
                for code in operation.get("responses", {})
                if code.isdigit() and int(code) >= 400
            )

    guide = (root / "guide/07-service.md").read_text(encoding="utf-8")
    table = guide[guide.index("| 状态 | 错误码") : guide.index("> **不要只看")]
    listed = {int(code) for code in re.findall(r"^\| (\d{3}) \|", table, re.M)}

    # The guide table is an error table, so success codes are out of scope.
    assert listed == documented, f"guide lists {sorted(listed)}, spec declares {sorted(documented)}"


def test_generated_doc_blocks_are_current() -> None:
    """The numbers in the docs must be the ones the code produces.

    Regenerating and comparing is the only way to keep hand-typed counts from
    drifting; four different error counts once lived in this repository.
    """
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "scripts/sync_docs.py", "--check"],
        cwd=pathlib.Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (
        f"docs are stale:\n{result.stdout}\nrun: uv run python scripts/sync_docs.py"
    )


def test_index_status_matches_each_page() -> None:
    """The index table must not claim a status its page contradicts."""
    root = pathlib.Path(__file__).resolve().parents[1]
    design = root / "docs" / "design"
    index = (design / "README.md").read_text(encoding="utf-8")

    for match in re.finditer(r"^\| \[\d+\]\(([^)]+\.md)\) \| \*\*.+?\*\* \| (.+?) \|", index, re.M):
        target, shown = match.group(1), match.group(2).strip()
        page = (design / target).read_text(encoding="utf-8")
        declared = re.search(r"^> \*\*实现状态\*\*：(.+)$", page, re.M)
        if declared is None:
            continue
        assert shown == declared.group(1).strip(), f"{target} status drifted"


def test_error_status_table_matches_the_server() -> None:
    """The HTTP mapping documented in 06-errors must be the one the server uses."""
    from quotestack.server.errors import STATUS_BY_CODE

    root = pathlib.Path(__file__).resolve().parents[1]
    text = (root / "docs/design/06-errors.md").read_text(encoding="utf-8")

    documented: dict[str, int] = {}
    for line in text.splitlines():
        match = re.match(r"^\| `([A-Za-z]+)` \| .*? \| (\d{3}) \|$", line)
        if match:
            documented[match.group(1)] = int(match.group(2))

    actual = {cls.__name__.removesuffix("Error"): status for cls, status in STATUS_BY_CODE.items()}

    assert documented, "no mapping rows parsed from 06-errors"
    for name, status in documented.items():
        assert actual.get(name) == status, (
            f"{name}: doc says {status}, server says {actual.get(name)}"
        )
    assert set(documented) == set(actual) | {"Delisted"}, (
        f"documented {sorted(documented)} vs server {sorted(actual)}"
    )


def test_sources_listed_in_the_docs_match_the_code() -> None:
    """A source named in the docs must exist; a removed one must not linger."""
    from quotestack.sources import (
        BinanceSource,
        EastMoneySource,
        FxSource,
        TencentSource,
        TiantianSource,
    )

    real = {
        source.meta.name
        for source in (
            EastMoneySource(),
            TencentSource(),
            TiantianSource(),
            BinanceSource(),
            FxSource(),
        )
    }
    root = pathlib.Path(__file__).resolve().parents[1]
    index = (root / "docs/design/README.md").read_text(encoding="utf-8")

    assert "OKX+CoinGecko" not in index, "removed sources still listed as active"
    for name in real:
        assert f"`{name}`" in index
