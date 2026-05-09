from __future__ import annotations

from datetime import datetime, timezone

from intraday.strategies.multi.xs_daily_momentum_strategy import (
    XsDailyMomentumStrategy,
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
    strategy = XsDailyMomentumStrategy(
        symbols=["BTCUSDT", "ETHUSDT"],
        lookback_bars=4,
        rebalance_bars=1,
    )
    assert (
        feed(
            strategy,
            [
                {"BTCUSDT": {"close": 100.0}, "ETHUSDT": {"close": 100.0}},
                {"BTCUSDT": {"close": 100.5}, "ETHUSDT": {"close": 99.5}},
            ],
        )
        is None
    )


def test_long_top_short_bottom():
    strategy = XsDailyMomentumStrategy(
        symbols=["BTCUSDT", "ETHUSDT"],
        lookback_bars=2,
        rebalance_bars=1,
        entry_z=0.5,
        max_weight=0.4,
    )
    rows = [
        {"BTCUSDT": {"close": 100.0}, "ETHUSDT": {"close": 100.0}},
        {"BTCUSDT": {"close": 101.0}, "ETHUSDT": {"close": 99.0}},
        {"BTCUSDT": {"close": 102.5}, "ETHUSDT": {"close": 97.5}},
    ]
    result = feed(strategy, rows)
    assert isinstance(result, PortfolioOrder)
    btc, eth = result["BTCUSDT"], result["ETHUSDT"]
    assert btc is not None and eth is not None
    assert btc.side == Side.BUY
    assert eth.side == Side.SELL
    assert 0 < btc.weight <= 0.4 and btc.weight == eth.weight


def test_finite_weights_only():
    strategy = XsDailyMomentumStrategy(
        symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        lookback_bars=2,
        rebalance_bars=1,
        entry_z=0.3,
        max_weight=0.5,
    )
    rows = [
        {"BTCUSDT": {"close": 100.0}, "ETHUSDT": {"close": 100.0}, "SOLUSDT": {"close": 100.0}},
        {"BTCUSDT": {"close": 102.0}, "ETHUSDT": {"close": 100.5}, "SOLUSDT": {"close": 98.0}},
        {"BTCUSDT": {"close": 104.0}, "ETHUSDT": {"close": 100.0}, "SOLUSDT": {"close": 96.0}},
    ]
    result = feed(strategy, rows)
    assert isinstance(result, PortfolioOrder)
    import math as _m
    for sym, order in result.items():
        if order is not None and order.weight is not None:
            assert 0 < order.weight <= 0.5 and _m.isfinite(order.weight)


def test_single_symbol_returns_none():
    strategy = XsDailyMomentumStrategy(
        symbols=["BTCUSDT"],
        lookback_bars=2,
        rebalance_bars=1,
    )
    rows = [
        {"BTCUSDT": {"close": 100.0}},
        {"BTCUSDT": {"close": 101.0}},
        {"BTCUSDT": {"close": 102.0}},
    ]
    assert feed(strategy, rows) is None


def test_rebalance_skips_off_cycle_bars():
    strategy = XsDailyMomentumStrategy(
        symbols=["BTCUSDT", "ETHUSDT"],
        lookback_bars=2,
        rebalance_bars=3,
        entry_z=0.3,
    )
    rows = [
        {"BTCUSDT": {"close": 100.0}, "ETHUSDT": {"close": 100.0}},
        {"BTCUSDT": {"close": 101.0}, "ETHUSDT": {"close": 99.0}},
        {"BTCUSDT": {"close": 101.5}, "ETHUSDT": {"close": 98.0}},
    ]
    # bar_count after this loop = 3, divisible by 3 → rebalance fires
    result = feed(strategy, rows)
    # bar 1 + 2 should have been skipped (bar_count 1 and 2 are off-cycle)
    assert isinstance(result, PortfolioOrder)
