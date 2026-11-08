"""Index name resolution.

Benchmarks name their components in prose (``中证800指数收益率``) while history
endpoints need a numeric secid. The search endpoint resolves most of them; a
small table covers the ones it does not index by name, such as bond indexes.
"""

from __future__ import annotations

import re

__all__ = ["KNOWN_INDEXES", "candidate_names", "normalize_index_name"]

# Prefixes that identify the publisher rather than the index.
_PREFIXES = ("上证", "中证", "深证", "国证", "沪深", "中华")

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
    "上证180公司治理": "1.000021",
    "180治理": "1.000021",
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


def candidate_names(raw: str) -> list[str]:
    """Suggest lookup names from most to least specific.

    The search endpoint indexes some indexes only under a shortened name, so a
    failed exact lookup falls back to dropping the publisher prefix.

    Args:
        raw: Component text, e.g. ``上证180公司治理指数``.

    Returns:
        Names to try in order, without duplicates.

    Example:
        >>> candidate_names("上证180公司治理指数")
        ['上证180公司治理', '180公司治理']
    """
    primary = normalize_index_name(raw)
    candidates = [primary]
    for prefix in _PREFIXES:
        if primary.startswith(prefix) and len(primary) > len(prefix):
            candidates.append(primary[len(prefix) :])
            break
    return list(dict.fromkeys(candidates))
