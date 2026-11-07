"""Per-item result for batch operations."""

from __future__ import annotations

from dataclasses import dataclass

from quotestack.models.instrument import Instrument
from quotestack.models.quote import Quote

__all__ = ["QuoteResult"]


@dataclass(frozen=True, slots=True)
class QuoteResult:
    """One entry of a batch quote response.

    A batch never fails as a whole: each item either carries a quote or an
    error, and the list stays the same length and order as the request.

    Args:
        instrument: The instrument this entry refers to, or ``None`` when the
            code could not be resolved.
        quote: The quote, when ``ok`` is true.
        error: The failure description, when ``ok`` is false.
    """

    instrument: Instrument | None = None
    quote: Quote | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        """Whether this entry produced a quote."""
        return self.quote is not None
