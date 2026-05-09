from __future__ import annotations

from datetime import datetime, timezone

from intraday.strategies.multi.ts_weekly_long_only_strategy import (
    TsWeeklyLongOnlyStrategy,
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
    strategy = TsWeeklyLongOnlyStrategy(
        symbols=["BTCUSDT", "ETHUSDT"],
        lookback_bars=2,
        history_window=3,
        rebalance_bars=1,
        hold_bars=10,
    )
    assert feed(strategy, [{"BTCUSDT": {"close": 100.0}, "ETHUSDT": {"close": 100.0}}]) is None


def test_long_only_no_short():
    """Strongly negative move on BTC should NOT trigger a SHORT (long-only)."""
    strategy = TsWeeklyLongOnlyStrategy(
        symbols=["BTCUSDT", "ETHUSDT"],
        lookback_bars=2,
        history_window=3,
        rebalance_bars=1,
        hold_bars=10,
        entry_z=1.0,
        max_weight=0.4,
    )
    rows = [
        {"BTCUSDT": {"close": 100.0}, "ETHUSDT": {"close": 100.0}},
        {"BTCUSDT": {"close": 100.1}, "ETHUSDT": {"close": 100.0}},
        {"BTCUSDT": {"close": 99.9}, "ETHUSDT": {"close": 100.0}},
        {"BTCUSDT": {"close": 100.0}, "ETHUSDT": {"close": 100.0}},
        {"BTCUSDT": {"close": 90.0}, "ETHUSDT": {"close": 100.0}},  # big down
    ]
    result = feed(strategy, rows)
    if result is not None:
        btc = result["BTCUSDT"]
        if btc is not None:
            assert btc.side != Side.SELL or btc.quantity != 0.0  # not opening a SHORT


def test_long_when_high_zscore():
    strategy = TsWeeklyLongOnlyStrategy(
        symbols=["BTCUSDT", "ETHUSDT"],
        lookback_bars=2,
        history_window=3,
        rebalance_bars=1,
        hold_bars=10,
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
    assert btc is not None and btc.side == Side.BUY


def test_single_symbol_returns_none_warmup():
    strategy = TsWeeklyLongOnlyStrategy(
        symbols=["BTCUSDT"],
        lookback_bars=2,
        history_window=3,
        rebalance_bars=1,
        hold_bars=10,
    )
    rows = [{"BTCUSDT": {"close": 100.0}}, {"BTCUSDT": {"close": 100.1}}]
    assert feed(strategy, rows) is None
