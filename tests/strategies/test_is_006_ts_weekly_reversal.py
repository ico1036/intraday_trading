from __future__ import annotations

from datetime import datetime, timezone

from intraday.strategies.multi.ts_weekly_reversal_strategy import (
    TsWeeklyReversalStrategy,
)
from intraday.strategy import MarketState, PortfolioOrder, Side


def make_state(panel, positions=None) -> MarketState:
    return MarketState(
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        mid_price=0.0,
        imbalance=0.0,
        spread=0.0,
        spread_bps=0.0,
        best_bid=0.0,
        best_ask=0.0,
        best_bid_qty=0.0,
        best_ask_qty=0.0,
        panel=panel,
        positions=positions,
    )


def feed(strategy, rows):
    last = None
    for panel in rows:
        last = strategy.generate_order(make_state(panel))
    return last


def test_warmup_returns_none():
    strategy = TsWeeklyReversalStrategy(
        symbols=["BTCUSDT", "ETHUSDT"],
        lookback_bars=2,
        history_window=3,
        rebalance_bars=1,
    )
    assert feed(strategy, [{"BTCUSDT": {"close": 100.0}, "ETHUSDT": {"close": 100.0}}]) is None


def test_short_when_strongly_up():
    """Reversal: a big positive move triggers a SHORT (mean-revert)."""
    strategy = TsWeeklyReversalStrategy(
        symbols=["BTCUSDT", "ETHUSDT"],
        lookback_bars=2,
        history_window=3,
        rebalance_bars=1,
        entry_z=1.0,
        max_weight=0.4,
    )
    rows = [
        {"BTCUSDT": {"close": 100.0}, "ETHUSDT": {"close": 100.0}},
        {"BTCUSDT": {"close": 100.1}, "ETHUSDT": {"close": 100.0}},
        {"BTCUSDT": {"close": 100.2}, "ETHUSDT": {"close": 100.0}},
        {"BTCUSDT": {"close": 100.1}, "ETHUSDT": {"close": 100.0}},
        {"BTCUSDT": {"close": 105.0}, "ETHUSDT": {"close": 100.0}},
    ]
    result = feed(strategy, rows)
    assert isinstance(result, PortfolioOrder)
    btc = result["BTCUSDT"]
    assert btc is not None and btc.side == Side.SELL


def test_finite_weights():
    strategy = TsWeeklyReversalStrategy(
        symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        lookback_bars=2,
        history_window=3,
        rebalance_bars=1,
        entry_z=0.5,
        max_weight=0.3,
    )
    rows = [
        {"BTCUSDT": {"close": 100.0}, "ETHUSDT": {"close": 100.0}, "SOLUSDT": {"close": 100.0}},
        {"BTCUSDT": {"close": 100.5}, "ETHUSDT": {"close": 99.7}, "SOLUSDT": {"close": 99.5}},
        {"BTCUSDT": {"close": 101.0}, "ETHUSDT": {"close": 99.5}, "SOLUSDT": {"close": 99.0}},
        {"BTCUSDT": {"close": 102.0}, "ETHUSDT": {"close": 98.5}, "SOLUSDT": {"close": 98.5}},
        {"BTCUSDT": {"close": 105.0}, "ETHUSDT": {"close": 96.0}, "SOLUSDT": {"close": 97.0}},
    ]
    result = feed(strategy, rows)
    if result is not None:
        import math as _m
        for sym, order in result.items():
            if order is not None and order.weight is not None:
                assert 0 < order.weight <= 0.3 and _m.isfinite(order.weight)


def test_single_symbol_returns_none_during_warmup():
    strategy = TsWeeklyReversalStrategy(
        symbols=["BTCUSDT"],
        lookback_bars=2,
        history_window=3,
        rebalance_bars=1,
    )
    rows = [{"BTCUSDT": {"close": 100.0}}, {"BTCUSDT": {"close": 100.1}}]
    assert feed(strategy, rows) is None
