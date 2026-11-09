"""Map transport failures onto the library's error model.

Every adapter used to call ``httpx`` directly, so a refused connection escaped
as ``httpx.ConnectError``. Callers could not catch ``MarketDataError`` and be
done, the HTTP layer answered 500 instead of 502, and the live probe crashed
instead of reporting that it could not reach the source.

One boundary, one mapping: everything that fails below HTTP becomes a
``MarketDataError`` here.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from quotestack.errors import TimeoutError, UpstreamError
from quotestack.logging import event

log = logging.getLogger("quotestack")

__all__ = ["send"]


async def send(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    source: str,
    **kwargs: Any,
) -> httpx.Response:
    """Perform one request, translating transport failures.

    Args:
        client: The shared HTTP client.
        method: HTTP method.
        url: Absolute URL.
        source: Adapter name, for the error context.
        **kwargs: Passed through to ``httpx``.

    Returns:
        The response, whatever its status code. Status handling stays with the
        caller, because only it knows which codes mean what.

    Raises:
        TimeoutError: The request timed out.
        UpstreamError: Any other transport failure.
    """
    event(log, logging.DEBUG, "upstream_request", source=source, method=method, url=url)
    try:
        return await client.request(method, url, **kwargs)
    except httpx.TimeoutException as exc:
        raise TimeoutError(
            f"{source} timed out after {client.timeout.read}s",
            source=source,
            url=url,
        ) from exc
    except httpx.RequestError as exc:
        raise UpstreamError(
            f"{source} request failed: {type(exc).__name__}",
            source=source,
            url=url,
        ) from exc
