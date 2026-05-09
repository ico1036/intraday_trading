from __future__ import annotations

from datetime import datetime, timezone

from intraday.strategies.multi.ts_daily_momentum_strategy import (
    TsDailyMomentumStrategy,
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
    strategy = TsDailyMomentumStrategy(
        symbols=["BTCUSDT", "ETHUSDT"],
        lookback_bars=2,
        history_window=3,
        rebalance_bars=1,
    )
    rows = [
        {"BTCUSDT": {"close": 100.0}, "ETHUSDT": {"close": 100.0}},
        {"BTCUSDT": {"close": 100.5}, "ETHUSDT": {"close": 99.5}},
    ]
    assert feed(strategy, rows) is None


def test_long_when_zscore_high():
    """After warmup, an outsized 24h move triggers a directional position per-symbol."""
    strategy = TsDailyMomentumStrategy(
        symbols=["BTCUSDT", "ETHUSDT"],
        lookback_bars=2,
        history_window=3,
        rebalance_bars=1,
        entry_z=1.0,
        max_weight=0.4,
    )
    # Build small history then a big move on BTC only
    rows = [
        {"BTCUSDT": {"close": 100.0}, "ETHUSDT": {"close": 100.0}},
        {"BTCUSDT": {"close": 100.1}, "ETHUSDT": {"close": 100.0}},
        {"BTCUSDT": {"close": 100.2}, "ETHUSDT": {"close": 100.0}},
        {"BTCUSDT": {"close": 100.1}, "ETHUSDT": {"close": 100.0}},
        {"BTCUSDT": {"close": 105.0}, "ETHUSDT": {"close": 100.0}},  # big move
    ]
    result = feed(strategy, rows)
    assert isinstance(result, PortfolioOrder)
    btc = result["BTCUSDT"]
    assert btc is not None
    assert btc.side == Side.BUY
    assert 0 < btc.weight <= 0.4


def test_single_symbol_ok():
    """basket_full universe means the strategy works on a single symbol too."""
    strategy = TsDailyMomentumStrategy(
        symbols=["BTCUSDT"],
        lookback_bars=2,
        history_window=3,
        rebalance_bars=1,
    )
    rows = [
        {"BTCUSDT": {"close": 100.0}},
        {"BTCUSDT": {"close": 100.1}},
        {"BTCUSDT": {"close": 100.0}},
        {"BTCUSDT": {"close": 100.1}},
    ]
    # warmup returns None
    assert feed(strategy, rows) is None


def test_finite_weights():
    strategy = TsDailyMomentumStrategy(
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
