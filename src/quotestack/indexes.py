"""Index name resolution.

Benchmarks name their components in prose (``中证800指数收益率``) while history
endpoints need a numeric secid. The search endpoint resolves most of them; a
small table covers the ones it does not index by name, such as bond indexes.
"""

from __future__ import annotations

import re

__all__ = ["KNOWN_INDEXES", "normalize_index_name"]

# Suffixes that appear in benchmark prose but not in index names.
_NOISE = re.compile(r"(指数)?(收益率|涨跌幅|全收益|价格指数)$")
_WEIGHT = re.compile(r"[*×xX]\s*\d+(?:\.\d+)?\s*%$")

# Names the search endpoint does not resolve, mapped to their Eastmoney secid.
KNOWN_INDEXES: dict[str, str] = {
    "上证国债": "1.000012",
    "上证国债指数": "1.000012",
    "上证企债": "1.000013",
    "中证全债": "1.H11001",
    "中证国债": "1.H11006",
    "中证企业债": "2.H11006",
    "沪深300": "1.000300",
    "中证500": "1.000905",
    "中证800": "1.000906",
    "中证1000": "1.000852",
    "中证A500": "1.000510",
    "上证50": "1.000016",
    "创业板指": "0.399006",
    "科创50": "1.000688",
}


def normalize_index_name(raw: str) -> str:
    """Strip weighting and prose suffixes so a name can be looked up.

    Args:
        raw: Component text, e.g. ``中证800指数收益率``.

    Returns:
        The cleaned name, e.g. ``中证800``. If stripping would leave an empty
        string, the original text is returned.

    Example:
        >>> normalize_index_name("中证800指数收益率")
        '中证800'
    """
    cleaned = _WEIGHT.sub("", raw.strip())
    cleaned = _NOISE.sub("", cleaned).strip()
    for suffix in ("收益率", "指数"):
        if cleaned.endswith(suffix) and len(cleaned) > len(suffix):
            cleaned = cleaned[: -len(suffix)]
    return cleaned or raw.strip()
