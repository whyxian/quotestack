"""Normalised fund classification.

Eastmoney publishes 33 fund type strings (``混合型-灵活``, ``债券型-中短债`` ...).
That is precise enough for display but too granular for logic, so it is folded
into seven classes that decide which estimation path applies.
"""

from __future__ import annotations

from quotestack.models.enums import FundClass

__all__ = ["classify_fund_type"]

# Ordered most specific first: the first prefix that matches wins.
_RULES: tuple[tuple[str, FundClass], ...] = (
    ("混合型-偏股", FundClass.EQUITY),
    ("混合型-偏债", FundClass.BOND),
    ("混合型", FundClass.HYBRID),
    ("指数型-股票", FundClass.EQUITY),
    ("指数型-海外股票", FundClass.EQUITY),
    ("指数型-固收", FundClass.BOND),
    ("指数型", FundClass.OTHER),
    ("股票型", FundClass.EQUITY),
    ("债券型", FundClass.BOND),
    ("货币型", FundClass.MONEY),
    ("QDII-普通股票", FundClass.EQUITY),
    ("QDII-混合偏股", FundClass.EQUITY),
    ("QDII-纯债", FundClass.BOND),
    ("QDII", FundClass.OTHER),
    ("FOF", FundClass.FOF),
    ("REIT", FundClass.REITS),
)


def classify_fund_type(raw: str | None) -> FundClass:
    """Fold a source fund type into a :class:`FundClass`.

    Args:
        raw: The source label, e.g. ``混合型-灵活``. ``None`` or an unknown
            label yields :attr:`FundClass.OTHER`.

    Returns:
        The normalised class. Unknown labels are never guessed into a
        specific class, because a wrong guess would produce a wrong estimate.

    Example:
        >>> classify_fund_type("混合型-偏股")
        <FundClass.EQUITY: 'EQUITY'>
    """
    if not raw:
        return FundClass.OTHER
    folded = raw.casefold()
    for prefix, fund_class in _RULES:
        if folded.startswith(prefix.casefold()):
            return fund_class
    return FundClass.OTHER
