"""Tests for the synchronous wrapper and the CLI."""

from __future__ import annotations

import json
from typing import Any

import pytest

import quotestack.cli as cli
from quotestack.models import AssetClass, Market
from quotestack.sync import SyncMarketData


def test_sync_wrapper_resolves_without_network() -> None:
    """Resolution is pure, so the wrapper works offline."""
    with SyncMarketData() as client:
        instrument = client.resolve("600519", AssetClass.STOCK, Market.CN)

    assert instrument.id == "CN:STOCK:600519"


def test_sync_wrapper_closes_cleanly() -> None:
    """Closing stops the background loop; a second close is harmless."""
    client = SyncMarketData()
    client.close()
    client.close()


class _FakeClient:
    """Stand-in for MarketData inside the CLI."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def resolve(self, code: str, asset_class: AssetClass, market: Market) -> Any:
        from quotestack.identity import resolve

        return resolve(code, asset_class, market)

    async def quote(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("not used")

    async def history(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("not used")

    def health(self) -> dict[str, object]:
        return {
            "status": "ok",
            "proxy": None,
            "sources": {"fake": {"state": "ok"}},
            "cache": {"entries": 3},
        }


def test_cli_resolve_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`quotestack resolve --json` prints a machine readable instrument."""
    monkeypatch.setattr(cli, "MarketData", _FakeClient)

    code = cli.main(["resolve", "000001", "--asset-class", "FUND", "--json"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["id"] == "CN:FUND:000001"
    assert payload["aliases"] == {"tiantian": "000001"}


def test_cli_health_reports_cache(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`quotestack health` prints source state and cache size."""
    monkeypatch.setattr(cli, "MarketData", _FakeClient)

    code = cli.main(["health"])

    assert code == 0
    out = capsys.readouterr().out
    assert "fake" in out
    assert "3 entries" in out


def test_cli_reports_error_and_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An invalid code exits non-zero and explains the error on stderr."""
    monkeypatch.setattr(cli, "MarketData", _FakeClient)

    code = cli.main(["resolve", "ABC", "--market", "CN"])

    assert code == 1
    assert "INVALID_ARGUMENT" in capsys.readouterr().err
