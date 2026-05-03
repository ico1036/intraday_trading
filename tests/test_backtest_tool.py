from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "agent" / "tools"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def test_discovers_only_multi_strategy_surface():
    from backtest_tool import _discover_strategies, _get_all_strategies

    multi = _discover_strategies("multi")
    assert "ATRVolumeRiskMomentumStrategy" in multi
    assert _discover_strategies("tick") == {}
    assert _discover_strategies("orderbook") == {}

    all_strategies = _get_all_strategies()
    assert set(all_strategies) == set(multi)
    assert {info["data_type"] for info in all_strategies.values()} == {"tick"}


@pytest.mark.asyncio
async def test_available_strategies_text_is_portfolio_only():
    from backtest_tool import _get_available_strategies_impl

    result = await _get_available_strategies_impl({})
    text = result["content"][0]["text"]

    assert "# Available Portfolio Strategies" in text
    assert "ATRVolumeRiskMomentumStrategy" in text
    assert "Orderbook Strategies" not in text
    assert "Tick Strategies" not in text


@pytest.mark.asyncio
async def test_run_backtest_rejects_non_tick_data_type():
    from backtest_tool import _run_backtest_impl

    result = await _run_backtest_impl(
        {
            "strategy": "ATRVolumeRiskMomentumStrategy",
            "data_type": "orderbook",
            "data_path": "./data/futures_ticks",
        }
    )

    assert result.get("is_error") is True
    assert "Must be 'tick'" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_run_backtest_uses_portfolio_runner(tmp_path, monkeypatch):
    from backtest_tool import _run_backtest_impl

    (tmp_path / "BTCUSDT").mkdir()
    (tmp_path / "ETHUSDT").mkdir()
    calls = {"portfolio": 0}

    class DummyStrategy:
        def __init__(self, symbols):
            self.symbols = symbols

    class DummyReport:
        initial_capital = 10000.0
        final_capital = 11000.0
        total_return = 0.1
        sharpe_ratio = 0.0
        max_drawdown = 0.0
        total_trades = 0
        win_rate = 0.0
        profit_factor = 0.0
        tick_counts = {}
        bar_counts = {}

        def get_symbol_breakdown(self):
            return {}

    class DummyRunner:
        def save_report(self, *_args, **_kwargs):
            return "./dummy"

    def fake_strategies():
        return {"DummyStrategy": {"class": DummyStrategy, "data_type": "tick"}}

    def fake_portfolio(*_args, **_kwargs):
        calls["portfolio"] += 1
        return DummyReport(), DummyRunner()

    monkeypatch.setattr("backtest_tool._get_all_strategies", fake_strategies)
    monkeypatch.setattr(
        "backtest_tool._run_portfolio_like_tick_backtest",
        fake_portfolio,
    )

    result = await _run_backtest_impl(
        {
            "strategy": "DummyStrategy",
            "data_type": "tick",
            "data_path": str(tmp_path),
            "bar_type": "VOLUME",
            "bar_size": 10,
        }
    )

    assert result.get("is_error") is not True
    assert calls["portfolio"] == 1
    assert "Portfolio Backtest Results" in result["content"][0]["text"]
