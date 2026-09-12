from __future__ import annotations

from datetime import datetime

import pandas as pd

from intraday.strategies.multi.xs_volume_rank_ftf_strategy import (
    ALPHA_CELL, SOURCE_NOTES, XsVolumeRankFtfStrategy,
)
from intraday.strategy import MarketState, Side


class _StubFilter:
    def __init__(self, block: set[str]):
        self.block = block
        self.calls: list = []

    def blocked(self, day, candidates):
        self.calls.append((day, set(candidates)))
        return {s for s in candidates if s in self.block}


def _state(ts, panel=None, positions=None):
    return MarketState(timestamp=ts, mid_price=1.0, imbalance=0.0, spread=0.0, spread_bps=0.0,
                       best_bid=1.0, best_ask=1.0, best_bid_qty=0.0, best_ask_qty=0.0,
                       panel=panel, positions=positions)


def test_metadata():
    assert ALPHA_CELL["idea_family"] == "xs_volume_rank_funding_filter"
    assert any("prereg" in n for n in SOURCE_NOTES)


def test_blocked_short_is_dropped_and_leg_renormalized():
    syms = ["A", "B", "C", "D", "E", "F"]
    flt = _StubFilter({"A"})
    s = XsVolumeRankFtfStrategy(syms, filter=flt, max_weight=0.5)
    qv = {"A": 6, "B": 5, "C": 4, "D": 3, "E": 2, "F": 1}
    d1 = datetime(2025, 1, 2)
    po = s._build_orders(_state(d1, positions={"A": {"side": "SHORT"}}), qv)
    o = {k: po[k] for k in syms}
    # reverse=True: short the top half (A,B,C), long the bottom half (D,E,F).
    assert o["A"].side == Side.BUY and o["A"].weight is None      # close the held short
    assert o["B"].side == Side.SELL and o["B"].weight == 0.25    # 0.5 / 2 remaining shorts
    assert o["C"].weight == 0.25
    for k in "DEF":
        assert o[k].side == Side.BUY and o[k].weight == 0.5 / 3
    assert flt.calls[0][0] == pd.Timestamp(d1) and flt.calls[0][1] == {"A", "B", "C"}


def test_no_block_matches_base_weights():
    syms = ["A", "B", "C", "D"]
    s = XsVolumeRankFtfStrategy(syms, filter=_StubFilter(set()))
    po = s._build_orders(_state(datetime(2025, 1, 2)), {"A": 4, "B": 3, "C": 2, "D": 1})
    assert po["A"].side == Side.SELL and po["A"].weight == 0.05
    assert po["D"].side == Side.BUY and po["D"].weight == 0.05
