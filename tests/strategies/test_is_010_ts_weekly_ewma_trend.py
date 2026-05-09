from __future__ import annotations

from datetime import datetime, timezone

from intraday.strategies.multi.ts_weekly_ewma_trend_strategy import (
    TsWeeklyEwmaTrendStrategy,
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
    strategy = TsWeeklyEwmaTrendStrategy(
        symbols=["BTCUSDT", "ETHUSDT"],
        fast_period_bars=2,
        slow_period_bars=4,
        rebalance_bars=1,
    )
    assert feed(strategy, [{"BTCUSDT": {"close": 100.0}, "ETHUSDT": {"close": 100.0}}]) is None


def test_long_when_fast_above_slow():
    strategy = TsWeeklyEwmaTrendStrategy(
        symbols=["BTCUSDT", "ETHUSDT"],
        fast_period_bars=2,
        slow_period_bars=4,
        rebalance_bars=1,
        entry_threshold=0.001,
        max_weight=0.4,
    )
    rows = [
        {"BTCUSDT": {"close": 100.0}, "ETHUSDT": {"close": 100.0}},
        {"BTCUSDT": {"close": 100.5}, "ETHUSDT": {"close": 100.0}},
        {"BTCUSDT": {"close": 101.0}, "ETHUSDT": {"close": 100.0}},
        {"BTCUSDT": {"close": 102.0}, "ETHUSDT": {"close": 100.0}},
        {"BTCUSDT": {"close": 105.0}, "ETHUSDT": {"close": 100.0}},
    ]
    result = feed(strategy, rows)
    assert isinstance(result, PortfolioOrder)
    btc = result["BTCUSDT"]
    assert btc is not None and btc.side == Side.BUY


def test_finite_weights():
    strategy = TsWeeklyEwmaTrendStrategy(
        symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        fast_period_bars=2,
        slow_period_bars=4,
        rebalance_bars=1,
        entry_threshold=0.001,
        max_weight=0.3,
    )
    rows = [
        {"BTCUSDT": {"close": 100.0}, "ETHUSDT": {"close": 100.0}, "SOLUSDT": {"close": 100.0}},
        {"BTCUSDT": {"close": 100.5}, "ETHUSDT": {"close": 99.5}, "SOLUSDT": {"close": 100.0}},
        {"BTCUSDT": {"close": 101.0}, "ETHUSDT": {"close": 99.0}, "SOLUSDT": {"close": 100.0}},
        {"BTCUSDT": {"close": 103.0}, "ETHUSDT": {"close": 97.0}, "SOLUSDT": {"close": 100.0}},
        {"BTCUSDT": {"close": 105.0}, "ETHUSDT": {"close": 95.0}, "SOLUSDT": {"close": 100.0}},
    ]
    result = feed(strategy, rows)
    if result is not None:
        import math as _m
        for sym, order in result.items():
            if order is not None and order.weight is not None:
                assert 0 < order.weight <= 0.3 and _m.isfinite(order.weight)


def test_single_symbol_warmup_none():
    strategy = TsWeeklyEwmaTrendStrategy(
        symbols=["BTCUSDT"],
        fast_period_bars=2,
        slow_period_bars=4,
        rebalance_bars=1,
    )
    rows = [{"BTCUSDT": {"close": 100.0}}, {"BTCUSDT": {"close": 100.5}}]
    assert feed(strategy, rows) is None
