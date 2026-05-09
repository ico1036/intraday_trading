from __future__ import annotations

from datetime import datetime, timezone

from intraday.strategies.multi.xs_return_momentum1h_strategy import (
    XsReturnMomentum1hStrategy,
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
    strategy = XsReturnMomentum1hStrategy(
        symbols=["BTCUSDT", "ETHUSDT"],
        lookback_bars=4,
        rebalance_bars=1,
    )
    rows = [
        {"BTCUSDT": {"close": 100.0}, "ETHUSDT": {"close": 100.0}},
        {"BTCUSDT": {"close": 100.5}, "ETHUSDT": {"close": 99.5}},
    ]
    assert feed(strategy, rows) is None


def test_long_top_short_bottom_after_warmup():
    strategy = XsReturnMomentum1hStrategy(
        symbols=["BTCUSDT", "ETHUSDT"],
        lookback_bars=2,
        rebalance_bars=1,
        entry_z=0.5,
        exit_z=0.1,
        max_weight=0.4,
    )
    rows = [
        {"BTCUSDT": {"close": 100.0}, "ETHUSDT": {"close": 100.0}},
        {"BTCUSDT": {"close": 101.0}, "ETHUSDT": {"close": 99.0}},
        {"BTCUSDT": {"close": 102.0}, "ETHUSDT": {"close": 98.0}},
    ]
    result = feed(strategy, rows)
    assert isinstance(result, PortfolioOrder)
    btc, eth = result["BTCUSDT"], result["ETHUSDT"]
    assert btc is not None and eth is not None
    assert btc.side == Side.BUY
    assert eth.side == Side.SELL
    assert 0 < btc.weight <= 0.4
    assert btc.weight == eth.weight


def test_finite_weights_only():
    strategy = XsReturnMomentum1hStrategy(
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
    for sym, order in result.items():
        if order is not None and order.weight is not None:
            assert 0 < order.weight <= 0.5
            import math as _m
            assert _m.isfinite(order.weight)


def test_single_symbol_returns_none():
    strategy = XsReturnMomentum1hStrategy(
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


def test_neutral_z_closes_existing_position():
    """When a held symbol's z drops below exit_z it must be closed flat."""
    strategy = XsReturnMomentum1hStrategy(
        symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"],
        lookback_bars=2,
        rebalance_bars=1,
        entry_z=2.0,
        exit_z=0.7,
    )
    # 3 symbols flat, 1 moves: zero-return symbols sit at z = -1/sqrt(3) ~= -0.577
    # which is below exit_z=0.7 → strategy should issue close on a held flat one.
    rows = [
        {"BTCUSDT": {"close": 100.0}, "ETHUSDT": {"close": 100.0},
         "SOLUSDT": {"close": 100.0}, "BNBUSDT": {"close": 100.0}},
        {"BTCUSDT": {"close": 100.0}, "ETHUSDT": {"close": 100.0},
         "SOLUSDT": {"close": 100.0}, "BNBUSDT": {"close": 101.0}},
    ]
    for r in rows:
        strategy.generate_order(make_state(r))
    result = strategy.generate_order(
        make_state(
            {"BTCUSDT": {"close": 100.0}, "ETHUSDT": {"close": 100.0},
             "SOLUSDT": {"close": 100.0}, "BNBUSDT": {"close": 101.0}},
            positions={"BTCUSDT": {"side": "LONG", "qty": 1.0, "entry_price": 100.0}},
        )
    )
    assert isinstance(result, PortfolioOrder)
    btc = result["BTCUSDT"]
    assert btc is not None
    assert btc.side == Side.SELL
    assert btc.quantity == 0.0
    assert btc.weight is None
