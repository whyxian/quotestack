"""Eastmoney adapter.

Split across small modules because the endpoint family is large: quotes,
klines and listings each have their own payload quirks and parsing rules.
"""

from __future__ import annotations

from quotestack.sources.eastmoney.core import SOURCE_META
from quotestack.sources.eastmoney.klines import KlinesMixin
from quotestack.sources.eastmoney.listings import ListingsMixin
from quotestack.sources.eastmoney.quotes import QuotesMixin

__all__ = ["EastMoneySource"]


class EastMoneySource(KlinesMixin, ListingsMixin, QuotesMixin):
    """Realtime quotes, historical bars and market listings.

    Args:
        client: Optional shared HTTP client. When omitted the adapter owns one
            and closes it in :meth:`aclose`.
        proxy: Outbound proxy applied when the adapter owns the client.
    """

    meta = SOURCE_META
