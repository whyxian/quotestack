"""Currency rates built from Eastmoney's FX quotes.

Eastmoney publishes a handful of pairs rather than a full matrix, so the
adapter fetches those and derives everything else through USD:

    USD/XXX = direct rate, or 1 / (XXXUSD), or USD/CNH x CNH/XXX

A cross rate is marked ``derived`` so callers can tell a quoted pair from a
computed one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import httpx

from quotestack.errors import SchemaChangedError, UnsupportedError, UpstreamError
from quotestack.models import Capability, FxRate
from quotestack.sources.base import SourceMeta
from quotestack.sources.transport import send

__all__ = ["FxSource"]

_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"

# Pairs that Eastmoney quotes directly. Keys are "BASEQUOTE".
_SECIDS: dict[str, str] = {
    "EURUSD": "119.EURUSD",
    "USDJPY": "119.USDJPY",
    "GBPUSD": "119.GBPUSD",
    "USDCNH": "133.USDCNH",
    "HKDCNH": "120.HKDCNYC",
    "EURCNH": "120.EURCNYC",
}

# The API echoes its own code (``HKDCNYC``), which differs from our key.
_BY_CODE = {secid.split(".", 1)[1]: name for name, secid in _SECIDS.items()}

# Currencies we can express against USD.
_PEG_ALIASES = {"CNY": "CNH"}

# Rates are quoted to four decimals; carrying more is false precision.
_RATE_DIGITS = 8


class FxSource:
    """Currency rates from Eastmoney."""

    meta = SourceMeta(
        name="eastmoney-fx",
        capabilities=frozenset({Capability.FX}),
        # FX has no asset class of its own; it is routed by capability.
        markets=frozenset(),
        timeout=5.0,
    )

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        proxy: str | None = None,
    ) -> None:
        """Create the adapter."""
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=self.meta.timeout, proxy=proxy)

    async def aclose(self) -> None:
        """Close the owned HTTP client."""
        if self._owns_client:
            await self._client.aclose()

    async def fx(self, base: str, quote: str) -> FxRate:
        """Convert between two currencies.

        Args:
            base: Source currency, e.g. ``USD``.
            quote: Target currency, e.g. ``CNY``.

        Returns:
            The rate, marked ``derived`` when it came from a cross.

        Raises:
            UnsupportedError: Either currency is unknown or unconvertible.
            SchemaChangedError: The quote payload lost its shape.
            UpstreamError: The request failed.
        """
        base, quote = base.upper(), quote.upper()
        if base == quote:
            return FxRate(
                base=base,
                quote=quote,
                rate="1",
                source=self.meta.name,
                as_of=datetime.now(UTC),
            )

        pairs = await self._fetch_pairs()
        table = self._usd_table(pairs)

        base_key = _PEG_ALIASES.get(base, base)
        quote_key = _PEG_ALIASES.get(quote, quote)

        if base_key not in table or quote_key not in table:
            raise UnsupportedError(
                f"no rate available for {base}/{quote}",
                base=base,
                quote=quote,
                supported=sorted({"USD", *_PEG_ALIASES.values(), *_PEG_ALIASES}),
            )

        rate = table[quote_key] / table[base_key]
        return FxRate(
            base=base,
            quote=quote,
            rate=_format_rate(rate),
            source=self.meta.name,
            as_of=datetime.now(UTC),
            derived=base_key != "USD" or quote_key != "USD",
        )

    async def _fetch_pairs(self) -> dict[str, Decimal]:
        response = await send(
            self._client,
            "GET",
            _URL,
            source=self.meta.name,
            params={"secids": ",".join(_SECIDS.values()), "fields": "f1,f2,f12,f14"},
        )
        if response.status_code >= 400:
            raise UpstreamError(
                f"eastmoney fx responded with {response.status_code}",
                source=self.meta.name,
                status_code=response.status_code,
            )

        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        rows = data.get("diff") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise SchemaChangedError(
                "eastmoney fx response has no rows",
                source=self.meta.name,
                capability="fx",
                assertion="data.diff is a list",
                sample=response.text[:400],
                url=str(response.url),
                hint="the FX payload changed shape; check tests/fixtures/eastmoney",
            )

        pairs: dict[str, Decimal] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = row.get("f12")
            raw = row.get("f2")
            scale = row.get("f1")
            if not isinstance(name, str) or not isinstance(raw, (int, float)):
                continue
            if not isinstance(scale, int):
                scale = 4
            pairs[_BY_CODE.get(name, name)] = Decimal(str(raw)).scaleb(-scale)
        return pairs

    @staticmethod
    def _usd_table(pairs: dict[str, Decimal]) -> dict[str, Decimal]:
        """Express every known currency in USD."""
        table: dict[str, Decimal] = {"USD": Decimal(1)}
        usd_cnh = pairs.get("USDCNH")

        if "EURUSD" in pairs:
            table["EUR"] = Decimal(1) / pairs["EURUSD"]
        if "GBPUSD" in pairs:
            table["GBP"] = Decimal(1) / pairs["GBPUSD"]
        if "USDJPY" in pairs:
            table["JPY"] = pairs["USDJPY"]
        if usd_cnh is not None:
            table["CNH"] = usd_cnh
            if pairs.get("HKDCNH"):
                table["HKD"] = usd_cnh / pairs["HKDCNH"]
            if pairs.get("EURCNH"):
                table["EUR"] = usd_cnh / pairs["EURCNH"]
        return table


def _format_rate(rate: Decimal) -> str:
    """Render a rate with a bounded, meaningful number of digits."""
    return str(rate.quantize(Decimal(1).scaleb(-_RATE_DIGITS)).normalize())
