"""Currency conversion results."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

__all__ = ["FxRate"]


@dataclass(frozen=True, slots=True)
class FxRate:
    """One currency pair.

    Args:
        base: Currency being converted from, e.g. ``USD``.
        quote: Currency being converted to, e.g. ``CNY``.
        rate: How many ``quote`` units one ``base`` unit buys, as a string.
        source: Source that supplied the underlying pairs.
        as_of: When the rate was observed.
        derived: Whether the rate came from a cross calculation rather than a
            directly quoted pair.
    """

    base: str
    quote: str
    rate: str
    source: str
    as_of: dt.datetime
    derived: bool = False
