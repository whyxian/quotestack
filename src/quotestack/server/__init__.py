"""HTTP layer.

Requires the ``server`` extra: ``uv sync --extra server``.
"""

from __future__ import annotations

from quotestack.server.app import create_app
from quotestack.server.config import Config, ConfigError, load

__all__ = ["Config", "ConfigError", "create_app", "load"]
