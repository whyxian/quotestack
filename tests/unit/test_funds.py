"""Tests for fund classification."""

from __future__ import annotations

import pytest

from quotestack.funds import classify_fund_type
from quotestack.models import FundClass


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("股票型", FundClass.EQUITY),
        ("混合型-偏股", FundClass.EQUITY),
        ("指数型-股票", FundClass.EQUITY),
        ("指数型-海外股票", FundClass.EQUITY),
        ("QDII-普通股票", FundClass.EQUITY),
        ("混合型-灵活", FundClass.HYBRID),
        ("混合型-平衡", FundClass.HYBRID),
        ("混合型-绝对收益", FundClass.HYBRID),
        ("混合型-偏债", FundClass.BOND),
        ("债券型-长债", FundClass.BOND),
        ("指数型-固收", FundClass.BOND),
        ("QDII-纯债", FundClass.BOND),
        ("货币型-普通货币", FundClass.MONEY),
        ("FOF-稳健型", FundClass.FOF),
        ("Reits", FundClass.REITS),
        ("指数型-其他", FundClass.OTHER),
        ("", FundClass.OTHER),
        (None, FundClass.OTHER),
        ("未知分类", FundClass.OTHER),
    ],
)
def test_classification(raw: str | None, expected: FundClass) -> None:
    """Every published label folds into exactly one class."""
    assert classify_fund_type(raw) is expected


def test_prefix_order_prefers_the_specific_rule() -> None:
    """``混合型-偏债`` must not fall through to the generic hybrid rule."""
    assert classify_fund_type("混合型-偏债") is FundClass.BOND
    assert classify_fund_type("混合型-偏股") is FundClass.EQUITY


def test_reits_matching_ignores_case() -> None:
    """The source writes ``Reits``, not ``REITS``."""
    assert classify_fund_type("Reits") is FundClass.REITS
    assert classify_fund_type("REITs") is FundClass.REITS


def test_unknown_labels_are_never_guessed() -> None:
    """An unrecognised label must not silently become equity."""
    for raw in ("商品型", "另类投资", None, ""):
        assert classify_fund_type(raw) is FundClass.OTHER
