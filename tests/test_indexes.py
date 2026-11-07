"""Tests for index name normalisation."""

from __future__ import annotations

import pytest

from quotestack.indexes import KNOWN_INDEXES, normalize_index_name


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("中证800指数收益率", "中证800"),
        ("中证A500指数收益率", "中证A500"),
        ("上证国债指数收益率", "上证国债"),
        ("沪深300指数收益率*50%", "沪深300"),
        ("中证香港300指数", "中证香港300"),
    ],
)
def test_strips_prose_and_weights(raw: str, expected: str) -> None:
    """Benchmark prose carries suffixes that index names do not have."""
    assert normalize_index_name(raw) == expected


def test_unknown_text_is_returned_unchanged() -> None:
    """A name with no known suffix must not be mangled."""
    assert normalize_index_name("一年期定期存款基准利率") == "一年期定期存款基准利率"


def test_known_table_covers_bond_indexes() -> None:
    """The search endpoint does not resolve bond indexes by name."""
    assert KNOWN_INDEXES["上证国债"] == "1.000012"
    assert KNOWN_INDEXES["中证800"] == "1.000906"
