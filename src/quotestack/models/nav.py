"""Fund net asset value points."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

__all__ = ["NavPoint"]


@dataclass(frozen=True, slots=True)
class NavPoint:
    """One published net asset value.

    ``nav`` is a decimal string for the same reason prices are: exact values
    must survive the trip through JSON and other languages.

    Args:
        date: Trading day the NAV applies to.
        nav: Net asset value per unit, as a decimal string.
    """

    date: dt.date
    nav: str
