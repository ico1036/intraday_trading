from datetime import datetime
from intraday.strategies.multi.ts_burst_revert_strategy import (
    ALPHA_CELL, SOURCE_NOTES, TsBurstRevertStrategy
)
from intraday.strategy import MarketState


def _state(panel):
    return MarketState(
        timestamp=datetime(2026, 3, 4), mid_price=0, imbalance=0, spread=0,
        spread_bps=0, best_bid=0, best_ask=0, best_bid_qty=0, best_ask_qty=0,
        panel=panel, positions={},
    )


def test_metadata():
    assert ALPHA_CELL["idea_family"] == "ts_burst_revert"


def test_burst_up_shorts_symbol():
    s = TsBurstRevertStrategy(
        ["A"], burst_bars=5, sigma_bars=20, hold_bars=10,
        rebalance_bars=1, entry_z=0.5,
    )
    out = None
    for t in range(30):
        out = s.generate_order(_state({"A": {"close": 100.0 + t * 0.01}}))
    for t in range(10):
        out = s.generate_order(_state({"A": {"close": 110.0 + t}}))
    assert out is not None
    assert out["A"] is not None and out["A"].side.value == "SELL"
