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


def test_harness_documents_are_reachable_from_the_entry_point() -> None:
    """AGENTS.md is an index; every harness file must be reachable from it."""
    root = pathlib.Path(__file__).resolve().parents[1]
    entry = (root / "AGENTS.md").read_text(encoding="utf-8")
    harness = sorted((root / "docs/harness").glob("*.md"))

    assert harness, "no harness documents"
    for path in harness:
        if path.name == "README.md":
            continue
        assert f"harness/{path.stem}" in entry, f"{path.name} is not linked from AGENTS.md"


def test_harness_does_not_hold_human_only_documents() -> None:
    """harness is AI context; a human code guide belongs elsewhere."""
    root = pathlib.Path(__file__).resolve().parents[1]
    names = {path.name for path in (root / "docs/harness").glob("*.md")}

    assert "CODE_MAP_ZH.md" not in names, "the Chinese code map is human-facing"
    assert (root / "docs/CODE_MAP_ZH.md").exists()


def test_entry_point_stays_an_index() -> None:
    """AGENTS.md should point at rules, not restate them."""
    root = pathlib.Path(__file__).resolve().parents[1]
    lines = len((root / "AGENTS.md").read_text(encoding="utf-8").splitlines())

    assert lines < 130, f"AGENTS.md grew to {lines} lines; move detail into harness/"


def test_sync_wrapper_covers_every_public_method() -> None:
    """The sync facade must not silently expose a subset of the async client.

    It shipped with five of eleven methods: no nav, no profile, no estimate.
    Someone not using asyncio would have concluded the library could not do
    those things.
    """
    import inspect

    from quotestack import MarketData
    from quotestack.sync import SyncMarketData

    def public(cls: type) -> set[str]:
        return {
            name
            for name, value in inspect.getmembers(cls, predicate=inspect.isfunction)
            if not name.startswith("_")
            and name not in {"aclose", "close", "cache_stats", "health", "source_for"}
        }

    missing = public(MarketData) - public(SyncMarketData)
    assert not missing, f"SyncMarketData is missing {sorted(missing)}"


def test_guide_capability_matrix_matches_the_sources() -> None:
    """The matrix in the reference must be what each adapter declares.

    Rows are capabilities, columns are sources.
    """
    from quotestack.models import Capability
    from quotestack.sources import (
        BinanceSource,
        EastMoneySource,
        FxSource,
        TencentSource,
        TiantianSource,
    )

    real = {
        source().meta.name: {c.value for c in source().meta.capabilities}
        for source in (EastMoneySource, TencentSource, TiantianSource, BinanceSource, FxSource)
    }
    labels = {
        "东财": "eastmoney",
        "腾讯": "tencent",
        "天天基金": "tiantian",
        "Binance": "binance",
        "东财外汇": "eastmoney-fx",
    }

    root = pathlib.Path(__file__).resolve().parents[1]
    text = (root / "guide/12-reference.md").read_text(encoding="utf-8")
    section = text[text.index("| 能力 | 东财") :]
    section = section[: section.index("\n\n")]

    header: list[str] = []
    checked = 0
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if not header:
            header = cells
            continue
        name = cells[0].strip("`")
        if name not in {c.value for c in Capability}:
            continue
        for label, cell in zip(header[1:], cells[1:], strict=False):
            source = labels[label]
            documented = cell == "✅"
            declared = name in real[source]
            assert documented == declared, (
                f"{source}/{name}: guide says {cell}, source declares {'YES' if declared else 'NO'}"
            )
            checked += 1

    assert checked >= 40, f"only {checked} cells parsed; table shape changed"


def test_documentation_fragments_and_links() -> None:
    """Links must resolve and Python blocks must parse.

    Both fail silently: a broken link only matters when a reader clicks it, and
    a block that does not parse only matters when someone copies it. Neither
    shows up in review, which is why they are checked here.
    """
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "scripts/check_docs.py"],
        cwd=pathlib.Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"documentation checks failed:\n{result.stdout}"
