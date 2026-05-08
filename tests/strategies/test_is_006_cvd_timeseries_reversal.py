from __future__ import annotations

from datetime import datetime, timezone

from intraday.strategies.multi.cvd_timeseries_reversal_strategy import (
    CvdTimeseriesReversalStrategy,
)
from intraday.strategy import MarketState, PortfolioOrder, Side


def make_state(panel, positions=None):
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


def _step(strat, panel):
    return strat.generate_order(make_state(panel))


def _feed(strat, rows):
    last = None
    for r in rows:
        last = _step(strat, r)
    return last


def test_warmup_returns_none():
    strat = CvdTimeseriesReversalStrategy(
        symbols=["A", "B"],
        fast_window=2,
        slow_window=10,
        rebalance_bars=1,
    )
    rows = [
        {"A": {"volume": 10.0, "volume_imbalance": 0.5},
         "B": {"volume": 10.0, "volume_imbalance": -0.5}}
    ] * 3
    assert _feed(strat, rows) is None


def test_extreme_recent_buy_aggression_goes_short():
    strat = CvdTimeseriesReversalStrategy(
        symbols=["A", "B"],
        fast_window=2,
        slow_window=8,
        rebalance_bars=1,
        top_k=1,
        entry_z=0.1,
        exit_z=0.05,
        max_weight=0.5,
    )
    base = {"A": {"volume": 10.0, "volume_imbalance": 0.0},
            "B": {"volume": 10.0, "volume_imbalance": 0.0}}
    rows = [base] * 8 + [
        {"A": {"volume": 10.0, "volume_imbalance": 0.95},
         "B": {"volume": 10.0, "volume_imbalance": -0.95}}
    ] * 2
    last = _feed(strat, rows)
    assert isinstance(last, PortfolioOrder)
    assert last["A"].side == Side.SELL  # spike up → reversal short
    assert last["B"].side == Side.BUY   # spike down → reversal long


def test_rebalance_bars_skip_intermediate():
    strat = CvdTimeseriesReversalStrategy(
        symbols=["A", "B"],
        fast_window=2,
        slow_window=8,
        rebalance_bars=4,
        entry_z=0.1,
    )
    rows = [
        {"A": {"volume": 10.0, "volume_imbalance": 0.5},
         "B": {"volume": 10.0, "volume_imbalance": -0.5}}
    ] * 3
    assert _feed(strat, rows) is None
