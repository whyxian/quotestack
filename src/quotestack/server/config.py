"""Server configuration.

The library takes explicit arguments; only the server reads files and
environment variables. Precedence, lowest first: built-in defaults, then
``quotestack.toml``, then ``QUOTESTACK_*``.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

__all__ = ["Config", "ConfigError", "load"]


class ConfigError(ValueError):
    """A configuration value is invalid; the server must not start."""


@dataclass(frozen=True, slots=True)
class Config:
    """Runtime configuration.

    Args:
        host: Bind address.
        port: Bind port.
        log_level: Python logging level name.
        proxy: Outbound proxy for every source.
        ttl: Per-capability TTL overrides, in seconds.
    """

    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"
    proxy: str | None = None
    ttl: dict[str, float] = field(default_factory=dict)


_DEFAULTS = Config()

_ENV = {
    "host": "QUOTESTACK_SERVER_HOST",
    "port": "QUOTESTACK_SERVER_PORT",
    "log_level": "QUOTESTACK_LOG_LEVEL",
    "proxy": "QUOTESTACK_PROXY_URL",
}

_TTL_NAMES = (
    "QUOTE",
    "HISTORY",
    "NAV",
    "PROFILE",
    "HOLDINGS",
    "BENCHMARK",
    "ESTIMATE",
    "FX",
    "RESOLVE",
    "LIST",
)


def load(path: str | None = None) -> Config:
    """Read configuration from disk and the environment.

    Args:
        path: Explicit TOML path. Defaults to ``$QUOTESTACK_CONFIG`` or
            ``./quotestack.toml`` when that file exists.

    Returns:
        The merged configuration.

    Raises:
        ConfigError: A value has the wrong type or is out of range.
    """
    data = _read_file(path)
    server = data.get("server")
    values: dict[str, object] = {}

    if isinstance(server, dict):
        for name in ("host", "log_level"):
            if name in server:
                values[name] = _as_str(name, server[name])
        if "port" in server:
            values["port"] = _as_port(server["port"])

    for name, variable in _ENV.items():
        raw = os.environ.get(variable)
        if raw is None:
            continue
        values[name] = _as_port(raw) if name == "port" else raw

    proxy_section = data.get("proxy")
    if isinstance(proxy_section, dict):
        url = proxy_section.get("url")
        if isinstance(url, str) and url:
            values["proxy"] = url
    override = os.environ.get("QUOTESTACK_PROXY_URL")
    if override:
        values["proxy"] = override

    merged = {f.name: getattr(_DEFAULTS, f.name) for f in fields(_DEFAULTS)}
    merged.update(values)
    merged["ttl"] = _read_ttl(data.get("ttl"))
    return Config(**merged)


def _read_file(path: str | None) -> dict[str, object]:
    candidate = path or os.environ.get("QUOTESTACK_CONFIG")
    file = Path(candidate) if candidate else Path("quotestack.toml")
    if not file.is_file():
        if candidate:
            raise ConfigError(f"config file not found: {file}")
        return {}
    try:
        with file.open("rb") as handle:
            parsed = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {file}: {exc}") from exc
    return parsed if isinstance(parsed, dict) else {}


def _read_ttl(section: object) -> dict[str, float]:
    """Parse the ``[ttl]`` table, accepting ``never`` for permanent caching."""
    ttl: dict[str, float] = {}
    if isinstance(section, dict):
        for name, value in section.items():
            ttl[name.upper()] = _as_ttl(name, value)

    for name in _TTL_NAMES:
        raw = os.environ.get(f"QUOTESTACK_TTL_{name}")
        if raw is not None:
            ttl[name] = _as_ttl(name, raw)
    return ttl


def _as_ttl(name: str, value: object) -> float:
    if isinstance(value, str) and value.strip().lower() == "never":
        return float("inf")
    if not isinstance(value, (int, float, str)):
        raise ConfigError(f"ttl.{name} must be a number or 'never'")
    try:
        number = float(value)
    except ValueError as exc:
        raise ConfigError(f"ttl.{name} must be a number or 'never'") from exc
    if number <= 0:
        raise ConfigError(f"ttl.{name} must be positive")
    return number


def _as_str(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"server.{name} must be a string")
    return value


def _as_port(value: object) -> int:
    # bool is a subclass of int, so `port = true` would otherwise become 1.
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ConfigError("server.port must be an integer")
    try:
        port = int(value)
    except ValueError as exc:
        raise ConfigError("server.port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ConfigError("server.port must be between 1 and 65535")
    return port
