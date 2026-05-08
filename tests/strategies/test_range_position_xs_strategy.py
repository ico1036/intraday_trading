from __future__ import annotations

from datetime import datetime

from intraday.strategies.multi.range_position_xs_strategy import (
    ALPHA_CELL,
    SOURCE_NOTES,
    RangePositionXsStrategy,
)
from intraday.strategy import MarketState


def _state(panel):
    return MarketState(
        timestamp=datetime(2026, 3, 4),
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
    assert ALPHA_CELL["idea_family"] == "range_position_xs"
    assert SOURCE_NOTES


def test_extreme_low_goes_long():
    syms = ["A", "B", "C"]
    s = RangePositionXsStrategy(
        syms,
        range_bars=20,
        rebalance_bars=20,
        top_k=1,
        entry_extreme=0.10,
        exit_extreme=0.05,
    )
    out = None
    # A trades within range 90-110, latest close at 91 (bottom)
    # B,C closes near 100 (mid)
    for t in range(40):
        a_close = 91.0 if t == 39 else 100.0 + ((t % 3) - 1) * 5
        panel = {
            "A": {"close": a_close, "high": 110.0, "low": 90.0},
            "B": {"close": 100.0, "high": 105.0, "low": 95.0},
            "C": {"close": 100.0, "high": 105.0, "low": 95.0},
        }
        out = s.generate_order(_state(panel))
    assert out is not None
    assert out["A"] is not None and out["A"].side.value == "BUY"
