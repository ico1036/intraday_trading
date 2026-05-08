from datetime import datetime
from intraday.strategies.multi.orb_fade_signal_flip_strategy import (
    ALPHA_CELL, SOURCE_NOTES, OrbFadeSignalFlipStrategy
)
from intraday.strategy import MarketState


def _state(panel, ts):
    return MarketState(
        timestamp=ts, mid_price=0, imbalance=0, spread=0, spread_bps=0,
        best_bid=0, best_ask=0, best_bid_qty=0, best_ask_qty=0,
        panel=panel, positions={},
    )


def test_metadata():
    assert ALPHA_CELL["exit"] == "signal_flip"
    assert ALPHA_CELL["idea_family"] == "orb_fade"
