from datetime import datetime
from intraday.strategies.multi.vol_filtered_meanrev_strategy import (
    ALPHA_CELL, SOURCE_NOTES, VolFilteredMeanrevStrategy,
)
from intraday.strategy import MarketState


def _state(panel):
    return MarketState(
        timestamp=datetime(2026, 3, 4), mid_price=0, imbalance=0, spread=0,
        spread_bps=0, best_bid=0, best_ask=0, best_bid_qty=0, best_ask_qty=0,
        panel=panel, positions={},
    )


def test_metadata():
    assert ALPHA_CELL["idea_family"] == "vol_filtered_meanrev"
    assert SOURCE_NOTES


def test_warmup_returns_none():
    s = VolFilteredMeanrevStrategy(
        ["A"], burst_bars=5, sigma_bars=10, rv_history_bars=20,
        rebalance_bars=5,
    )
    out = s.generate_order(_state({"A": {"close": 100.0}}))
    assert out is None
