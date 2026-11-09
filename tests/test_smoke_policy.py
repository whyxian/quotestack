"""The live probe's failure policy, tested without a network.

A probe that turns red because of where it runs is worse than no probe: people
learn to ignore it. A probe that stays green when a payload changes shape is
equally useless. This file pins the distinction.
"""

from __future__ import annotations

import pytest
from tests.test_smoke import resolve_or_skip

from quotestack.errors import (
    EmptyResponseError,
    RateLimitedError,
    SchemaChangedError,
    TimeoutError,
    UnavailableError,
)


async def _raise(error: Exception) -> None:
    raise error


@pytest.mark.parametrize(
    "error",
    [UnavailableError("down", source="x"), TimeoutError("slow"), RateLimitedError("429")],
)
async def test_transport_problems_skip(error: Exception) -> None:
    """Not being able to reach a source says nothing about the parser."""
    with pytest.raises(pytest.skip.Exception):
        await resolve_or_skip(_raise(error))


@pytest.mark.parametrize(
    "error",
    [
        SchemaChangedError(
            "moved", source="x", capability="quote", assertion="has data", sample=""
        ),
        EmptyResponseError("empty", source="x"),
    ],
)
async def test_structural_problems_fail(error: Exception) -> None:
    """A payload that no longer parses is exactly what the probe watches for."""
    with pytest.raises(type(error)):
        await resolve_or_skip(_raise(error))


async def test_success_passes_through() -> None:
    async def ok() -> str:
        return "value"

    assert await resolve_or_skip(ok()) == "value"
