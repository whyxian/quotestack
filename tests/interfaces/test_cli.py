"""CLI tests covering the command surface end to end."""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import pytest

import quotestack.cli as cli
from quotestack.models import (
    AssetClass,
    Bar,
    Estimate,
    EstimateBasis,
    Market,
    Quote,
    QuoteStatus,
)

_TS = dt.datetime(2026, 11, 6, 15, 0, tzinfo=dt.timezone(dt.timedelta(hours=8)))


class _FakeClient:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def resolve(self, code: str, asset_class: Any = None, market: Any = None) -> Any:
        from quotestack.identity import resolve

        return resolve(code, asset_class or AssetClass.STOCK, market or Market.CN)

    async def quote(self, code: str, *args: Any, **kwargs: Any) -> Quote:
        return Quote(
            instrument_id="CN:STOCK:600519",
            price="1453.00",
            currency="CNY",
            source="eastmoney",
            ts=_TS,
            change="1.00",
            change_pct=0.07,
            status=QuoteStatus.REALTIME,
        )

    async def history(self, *args: Any, **kwargs: Any) -> list[Bar]:
        return [
            Bar(
                date=dt.date(2026, 11, 6),
                open="1450.00",
                high="1457.72",
                low="1436.00",
                close="1453.00",
                volume="42848",
            )
        ]

    async def estimate(self, *args: Any, **kwargs: Any) -> Estimate:
        return Estimate(
            change_pct=None,
            basis=EstimateBasis.NONE,
            explanation="输入不可用",
        )

    def health(self) -> dict[str, object]:
        return {
            "status": "ok",
            "proxy": None,
            "sources": {"eastmoney": {"state": "ok"}},
            "cache": {"entries": 2},
        }


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "MarketData", _FakeClient)


def test_quote_prints_a_table(fake: None, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["quote", "600519"]) == 0
    out = capsys.readouterr().out
    assert "1453.00" in out
    assert "eastmoney" in out


def test_quote_json_keeps_price_a_string(fake: None, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["quote", "600519", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["price"] == "1453.00"


def test_history_prints_bars(fake: None, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["history", "600519", "--limit", "1"]) == 0
    assert "1453.00" in capsys.readouterr().out


def test_estimate_shows_unknown_as_words(fake: None, capsys: pytest.CaptureFixture[str]) -> None:
    """Null must not be rendered as a number."""
    assert cli.main(["estimate", "022430"]) == 0
    out = capsys.readouterr().out
    assert "算不出来" in out
    assert "none" in out


def test_estimate_json_keeps_null(fake: None, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["estimate", "022430", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["change_pct"] is None


def test_health_lists_sources(fake: None, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["health"]) == 0
    assert "eastmoney" in capsys.readouterr().out


def test_unknown_command_is_rejected() -> None:
    with pytest.raises(SystemExit):
        cli.main(["nope"])
