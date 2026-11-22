"""Which live-probe failures are environmental and which are real signal.

A *transport* failure - no route, timeout, the source refusing a datacenter IP -
says nothing about the library, so the probe skips. A *structural* failure - a
payload that no longer parses - is exactly what the probe exists to catch, so it
fails.

This lives outside the test modules so the policy can be exercised without a
network, and so two test modules can share it without importing each other.
"""

from __future__ import annotations

from typing import Any

import pytest

from quotestack.errors import (
    EmptyResponseError,
    RateLimitedError,
    SchemaChangedError,
    TimeoutError,
    UnavailableError,
)

#: Problems reaching the source at all.
TRANSPORT = (UnavailableError, TimeoutError, RateLimitedError)
#: The source answered, but not in the shape the parser expects.
STRUCTURAL = (SchemaChangedError, EmptyResponseError)

__all__ = ["STRUCTURAL", "TRANSPORT", "resolve_or_skip"]


async def resolve_or_skip(awaitable: Any) -> Any:
    """Await a live call, converting an environment problem into a skip.

    Args:
        awaitable: The coroutine of the live call.

    Returns:
        Whatever the call returned.

    Raises:
        BaseException: Whatever it raised, unless it is a transport problem.
    """
    try:
        return await awaitable
    except STRUCTURAL:
        raise
    except TRANSPORT as exc:
        pytest.skip(f"cannot reach the source from this runner: {exc.code}")
