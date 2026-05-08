"""Focused tests for OpeningRangeBreakoutStrategy."""
from __future__ import annotations

from datetime import datetime, timedelta

from intraday.strategies.multi.opening_range_breakout_strategy import (
    ALPHA_CELL,
    SOURCE_NOTES,
    OpeningRangeBreakoutStrategy,
)
from intraday.strategy import MarketState


def _state(panel: dict, ts: datetime) -> MarketState:
    return MarketState(
        timestamp=ts,
        mid_price=0.0,
        imbalance=0.0,
        spread=0.0,
        spread_bps=0.0,
        best_bid=0.0,
        best_ask=0.0,
        best_bid_qty=0.0,
        best_ask_qty=0.0,
        panel=panel,
        positions={},
    )


def test_metadata():
    assert ALPHA_CELL["idea_family"] == "opening_range_breakout"
    assert SOURCE_NOTES


def test_no_orders_during_or_window():
    syms = ["BTCUSDT"]
    strat = OpeningRangeBreakoutStrategy(syms, or_minutes=60)
    base = datetime(2026, 3, 4, 0, 30)
    out = strat.generate_order(
        _state({"BTCUSDT": {"close": 100.0, "high": 101.0, "low": 99.0}}, base)
    )
    assert out is None


def test_break_above_or_high_triggers_long():
    syms = ["BTCUSDT"]
    strat = OpeningRangeBreakoutStrategy(syms, or_minutes=60)
    # Build OR over first hour: range 100-110
    for m in range(60):
        ts = datetime(2026, 3, 4, 0, m)
        strat.generate_order(
            _state({"BTCUSDT": {"close": 105.0, "high": 110.0, "low": 100.0}}, ts)
        )
    # After OR: price breaks above 110
    out = strat.generate_order(
        _state({"BTCUSDT": {"close": 115.0, "high": 116.0, "low": 114.0}},
               datetime(2026, 3, 4, 1, 5))
    )
    assert out is not None
    assert out["BTCUSDT"] is not None
    assert out["BTCUSDT"].side.value == "BUY"


def test_break_below_or_low_triggers_short():
    syms = ["BTCUSDT"]
    strat = OpeningRangeBreakoutStrategy(syms, or_minutes=60)
    for m in range(60):
        ts = datetime(2026, 3, 4, 0, m)
        strat.generate_order(
            _state({"BTCUSDT": {"close": 105.0, "high": 110.0, "low": 100.0}}, ts)
        )
    out = strat.generate_order(
        _state({"BTCUSDT": {"close": 95.0, "high": 96.0, "low": 94.0}},
               datetime(2026, 3, 4, 1, 5))
    )
    assert out is not None
    assert out["BTCUSDT"] is not None
    assert out["BTCUSDT"].side.value == "SELL"
