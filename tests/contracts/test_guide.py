"""Guards on the user-facing guide."""

from __future__ import annotations

import re

from tests.support import ROOT

from quotestack.models import Capability
from quotestack.sources import (
    BinanceSource,
    EastMoneySource,
    FxSource,
    TencentSource,
    TiantianSource,
)

ROOT_DIR = ROOT


def test_guide_status_table_matches_the_spec() -> None:
    """The status codes the guide lists must be the ones the API can return."""
    import yaml

    root = ROOT
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


def test_guide_capability_matrix_matches_the_sources() -> None:
    """The matrix in the reference must be what each adapter declares.

    Rows are capabilities, columns are sources.
    """

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

    root = ROOT
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


def test_guide_crypto_capabilities_match_the_sources() -> None:
    """The concepts guide crypto row must reflect the capabilities Binance serves."""
    root = ROOT
    concepts = (root / "guide/02-concepts.md").read_text(encoding="utf-8")

    crypto_rows = [line for line in concepts.splitlines() if "CRYPTO:" in line]
    assert crypto_rows
    assert any("报价、K 线" in line for line in crypto_rows)


def test_guide_rate_limit_matches_the_configured_bucket() -> None:
    """A claim about throughput has to agree with the limiter we ship."""
    from quotestack.resilience import TokenBucket

    bucket = TokenBucket()
    root = ROOT
    universe = (root / "guide/06-universe.md").read_text(encoding="utf-8")

    assert f"{bucket._rate:g} 次/秒" in universe, (
        f"guide states a rate that is not the bucket's {bucket._rate:g}/s"
    )


def test_guide_ttl_table_does_not_claim_an_uncached_capability_is_cached() -> None:
    root = ROOT
    guide = (root / "guide/12-reference.md").read_text(encoding="utf-8")
    section = guide[guide.index("| 能力 | 默认 TTL |") :]
    section = section[: section.index("\n\n")]

    for capability in ("BENCHMARK", "LIST"):
        rows = [line for line in section.splitlines() if f"`{capability}`" in line]
        assert rows, f"guide has no row for {capability}"
        assert "不缓存" in rows[0]


def test_guide_fund_classes_match_the_enum() -> None:
    """The guide lists the seven fund classes readers will see."""
    from quotestack.models import FundClass

    root = ROOT
    guide = (root / "guide/04-funds.md").read_text(encoding="utf-8")
    section = guide[guide.index("| `fund_class` | 涵盖 | 含义 |") :]
    section = section[: section.index("**未知标签一律归")]

    documented = set(re.findall(r"^\| `([A-Z]+)` \|", section, re.M))
    real = {member.value for member in FundClass}

    assert documented == real, f"guide {sorted(documented)} vs enum {sorted(real)}"


def test_guide_batch_request_count_is_not_a_single_request() -> None:
    """Batching is per market and per 50 instruments, not one request.

    The guide said one network request for any batch, which the implementation
    contradicts as soon as a batch spans two markets or exceeds 50 instruments.
    """
    from quotestack.sources.eastmoney.quotes import MAX_BATCH

    quotes = (ROOT / "guide/03-quotes.md").read_text(encoding="utf-8")
    assert f"{MAX_BATCH} 只一批" in quotes, "the batch size must be stated, and match the code"

    for relative in ("guide/03-quotes.md", "guide/09-recipes.md", "guide/10-sync.md"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "一次网络请求" not in text.replace("一次请求拿一批", ""), relative


def test_guide_error_codes_exist_in_the_library() -> None:
    """Every code the troubleshooting guide names must be a real error code."""
    import quotestack.errors as errors
    from quotestack.errors import MarketDataError

    real = {
        value.code
        for value in vars(errors).values()
        if isinstance(value, type) and issubclass(value, MarketDataError)
    }

    text = (ROOT_DIR / "guide/11-troubleshooting.md").read_text(encoding="utf-8")
    section = text[text.index("| `code` | 含义 | 怎么办 |") :]
    section = section[: section.index("**场外基金查报价")]
    documented = set(re.findall(r"^\| `([A-Z_]+)` \|", section, re.M))

    assert documented, "no codes parsed"
    assert documented <= real, f"guide names codes that do not exist: {documented - real}"
