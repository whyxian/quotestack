"""Error hierarchy.

Every error carries enough context to be actionable: which source failed,
which instrument was involved, and how it should be handled.

See ``docs/design/06-errors.md`` for the full taxonomy.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "AmbiguousError",
    "ClientBrokenError",
    "EmptyResponseError",
    "InvalidArgumentError",
    "MarketDataError",
    "NotFoundError",
    "SchemaChangedError",
    "TimeoutError",
    "UnauthorizedError",
    "UnsupportedError",
    "UpstreamError",
]


class MarketDataError(Exception):
    """Base class for every error raised by quotestack.

    Args:
        message: Human readable description.
        **context: Structured details merged into the error payload.
    """

    code: str = "MARKETDATA_ERROR"
    retryable: bool = False
    fallback: bool = False

    def __init__(self, message: str, **context: Any) -> None:
        super().__init__(message)
        self.message = message
        self.context: dict[str, Any] = context

    def to_dict(self) -> dict[str, Any]:
        """Serialize the error for logs or HTTP responses."""
        return {
            "code": self.code,
            "message": self.message,
            **self.context,
        }


class InvalidArgumentError(MarketDataError):
    """Caller passed an invalid argument."""

    code = "INVALID_ARGUMENT"


class NotFoundError(MarketDataError):
    """The code does not exist on any source."""

    code = "NOT_FOUND"


class AmbiguousError(MarketDataError):
    """Several candidates matched and none could be selected."""

    code = "AMBIGUOUS"


class UnsupportedError(MarketDataError):
    """The instrument exists but has no data for this capability."""

    code = "UNSUPPORTED"


class UpstreamError(MarketDataError):
    """A data source failed.

    Args:
        message: Human readable description.
        source: Name of the failing source.
        attempt: 1-based attempt counter.
    """

    code = "UPSTREAM_ERROR"
    retryable = True
    fallback = True

    def __init__(
        self,
        message: str,
        *,
        source: str | None = None,
        attempt: int = 1,
        **context: Any,
    ) -> None:
        super().__init__(message, source=source, attempt=attempt, **context)


class TimeoutError(UpstreamError):
    """The source did not respond in time."""

    code = "TIMEOUT"


class EmptyResponseError(UpstreamError):
    """The source responded correctly but has no data for this instrument.

    Not retryable: retrying the same source returns nothing again. Switch
    to the next source instead.
    """

    code = "EMPTY_RESPONSE"
    retryable = False


class SchemaChangedError(UpstreamError):
    """The source response no longer matches the expected structure.

    This means the upstream changed and the adapter needs an update.
    """

    code = "SCHEMA_CHANGED"
    retryable = False


class UnauthorizedError(UpstreamError):
    """The source rejected the request (HTTP 401/403)."""

    code = "UNAUTHORIZED"
    retryable = False


class ClientBrokenError(MarketDataError):
    """Every source returned an unexpected structure."""

    code = "CLIENT_BROKEN"
