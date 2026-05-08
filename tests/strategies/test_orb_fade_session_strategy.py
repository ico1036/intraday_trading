from __future__ import annotations

from datetime import datetime

from intraday.strategies.multi.orb_fade_session_strategy import (
    ALPHA_CELL,
    SOURCE_NOTES,
    OrbFadeSessionStrategy,
)
from intraday.strategy import MarketState


def _state(panel, ts):
    return MarketState(
        timestamp=ts,
        mid_price=0,
        imbalance=0,
        spread=0,
        spread_bps=0,
        best_bid=0,
        best_ask=0,
        best_bid_qty=0,
        best_ask_qty=0,
        panel=panel,
        positions={},
    )


def test_metadata():
    assert ALPHA_CELL["idea_family"] == "orb_fade"
    assert SOURCE_NOTES


def test_break_above_or_high_fades_short():
    syms = ["BTCUSDT"]
    s = OrbFadeSessionStrategy(syms, or_minutes=60)
    for m in range(60):
        ts = datetime(2026, 3, 4, 0, m)
        s.generate_order(_state({"BTCUSDT": {"close": 105.0, "high": 110.0, "low": 100.0}}, ts))
    out = s.generate_order(
        _state({"BTCUSDT": {"close": 115.0, "high": 116.0, "low": 114.0}},
               datetime(2026, 3, 4, 1, 5))
    )
    assert out is not None
    assert out["BTCUSDT"] is not None and out["BTCUSDT"].side.value == "SELL"


def test_break_below_or_low_fades_long():
    syms = ["BTCUSDT"]
    s = OrbFadeSessionStrategy(syms, or_minutes=60)
    for m in range(60):
        ts = datetime(2026, 3, 4, 0, m)
        s.generate_order(_state({"BTCUSDT": {"close": 105.0, "high": 110.0, "low": 100.0}}, ts))
    out = s.generate_order(
        _state({"BTCUSDT": {"close": 95.0, "high": 96.0, "low": 94.0}},
               datetime(2026, 3, 4, 1, 5))
    )
    assert out is not None
    assert out["BTCUSDT"] is not None and out["BTCUSDT"].side.value == "BUY"
