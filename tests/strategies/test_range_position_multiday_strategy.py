from datetime import datetime
from intraday.strategies.multi.range_position_multiday_strategy import (
    ALPHA_CELL, SOURCE_NOTES, RangePositionMultidayStrategy
)
from intraday.strategy import MarketState


def _state(panel):
    return MarketState(
        timestamp=datetime(2026, 3, 4), mid_price=0, imbalance=0, spread=0,
        spread_bps=0, best_bid=0, best_ask=0, best_bid_qty=0, best_ask_qty=0,
        panel=panel, positions={},
    )


def test_metadata():
    assert ALPHA_CELL["idea_family"] == "range_position_xs"
    assert ALPHA_CELL["horizon"] == "multi_day"
