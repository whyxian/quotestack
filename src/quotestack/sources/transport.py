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
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from quotestack.errors import (
    NotFoundError,
    RateLimitedError,
    TimeoutError,
    UnauthorizedError,
    UpstreamError,
)
from quotestack.logging import event

log = logging.getLogger("quotestack")

__all__ = ["check_status", "send"]

# A source answers 429 or 514 when it wants you to slow down. Treating those as
# plain upstream errors marks them retryable, which is the opposite of what the
# source asked for.
_RATE_LIMIT_STATUSES = frozenset({429, 514})


def _retry_after(response: httpx.Response) -> float | None:
    """Read ``Retry-After``, in either of the forms the header allows.

    The design called for honouring the source's own backoff request; without
    this the cooldown used its fixed default and could retry long before the
    source said it was ready.
    """
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    raw = raw.strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        return None
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


def check_status(
    response: httpx.Response,
    *,
    source: str,
    what: str,
    instrument: str | None = None,
    not_found: str | None = None,
) -> None:
    """Raise the right error for a failed response, or return quietly.

    Status handling was copy-pasted at every call site, and the copies drifted:
    only one adapter recognised the throttle status, so everywhere else a
    request to slow down was reported as retryable.

    Args:
        response: The response to inspect.
        source: Adapter name, for the error context.
        what: Human description of the endpoint, e.g. ``"eastmoney profile"``.
        instrument: Instrument id, when the call was about one.
        not_found: Message to use for a 404, when a 404 means "absent" rather
            than "something is wrong".

    Raises:
        NotFoundError: ``not_found`` was given and the status is 404.
        RateLimitedError: The status asks for backoff.
        UnauthorizedError: The status asks for credentials.
        UpstreamError: Any other failure status.
    """
    status = response.status_code
    if status < 400:
        return

    context: dict[str, Any] = {"status_code": status}
    if instrument is not None:
        context["instrument"] = instrument
    # Any status may carry Retry-After; it is the source saying when to return.
    retry_after = _retry_after(response)
    if retry_after is not None:
        context["retry_after"] = retry_after

    if status == 404 and not_found is not None:
        raise NotFoundError(not_found, source=source, **context)
    if status in _RATE_LIMIT_STATUSES:
        raise RateLimitedError(
            f"{what} answered {status}, which asks for backoff",
            source=source,
            hint="lower the request rate; the source is throttling",
            **context,
        )
    if status in {401, 403}:
        raise UnauthorizedError(f"{what} answered {status}", source=source, **context)
    raise UpstreamError(f"{what} responded with {status}", source=source, **context)


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
