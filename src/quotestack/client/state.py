"""Shared client state.

Declared once so the mixins do not each repeat the same annotations: they all
operate on one object, but only :class:`CoreMixin` creates the attributes.
"""

from __future__ import annotations

import asyncio

from quotestack.cache import Cache
from quotestack.models import Capability
from quotestack.resilience import Cooldown, TokenBucket

__all__ = ["ClientState"]


class ClientState:
    """Attribute declarations shared by every client mixin."""

    _cache: Cache
    _ttl: dict[Capability, float]
    _max_stale: dict[Capability, float]
    _sources: dict[str, object]
    _priority: dict[str, list[str]]
    _cooldown: Cooldown
    _bucket: TokenBucket
    _inflight: dict[str, asyncio.Task[object]]
