from datetime import datetime
from intraday.strategies.multi.vol_dispersion_xs_strategy import (
    ALPHA_CELL, SOURCE_NOTES, VolDispersionXsStrategy
)
from intraday.strategy import MarketState


def _state(panel):
    return MarketState(
        timestamp=datetime(2026, 3, 4), mid_price=0, imbalance=0, spread=0,
        spread_bps=0, best_bid=0, best_ask=0, best_bid_qty=0, best_ask_qty=0,
        panel=panel, positions={},
    )


def test_metadata():
    assert ALPHA_CELL["idea_family"] == "vol_dispersion_xs"


def test_high_vol_shorted_low_vol_longed():
    s = VolDispersionXsStrategy(
        ["A", "B", "C"], rv_bars=20, rebalance_bars=20, top_k=1
    )
    out = None
    import random
    random.seed(0)
    for t in range(60):
        out = s.generate_order(_state({
            "A": {"close": 100.0 + random.random() * 0.01},   # very low vol
            "B": {"close": 100.0 + random.random() * 0.5},    # mid vol
            "C": {"close": 100.0 + random.random() * 5.0},    # high vol
        }))
    assert out is not None
    assert out["A"] is not None and out["A"].side.value == "BUY"
    assert out["C"] is not None and out["C"].side.value == "SELL"
