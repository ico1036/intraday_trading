from __future__ import annotations

from datetime import datetime, timezone

from intraday.strategies.multi.orderflow_rank_daily_strategy import (
    OrderflowRankDailyStrategy,
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


def test_continuation_top_long_bottom_short():
    strat = OrderflowRankDailyStrategy(
        symbols=["A", "B", "C"],
        lookback_bars=2,
        rebalance_bars=1,
        top_k=1,
        max_weight=0.5,
        direction="continuation",
    )
    rows = [
        {"A": {"volume": 10.0, "volume_imbalance": 0.9},
         "B": {"volume": 10.0, "volume_imbalance": 0.0},
         "C": {"volume": 10.0, "volume_imbalance": -0.9}}
    ] * 3
    last = None
    for r in rows:
        last = strat.generate_order(make_state(r))

    assert isinstance(last, PortfolioOrder)
    assert last["A"].side == Side.BUY
    assert last["C"].side == Side.SELL
    assert last["B"] is None or last["B"].quantity == 0.0


def test_reversion_flips_long_and_short():
    strat = OrderflowRankDailyStrategy(
        symbols=["A", "B", "C"],
        lookback_bars=2,
        rebalance_bars=1,
        top_k=1,
        max_weight=0.5,
        direction="reversion",
    )
    rows = [
        {"A": {"volume": 10.0, "volume_imbalance": 0.9},
         "B": {"volume": 10.0, "volume_imbalance": 0.0},
         "C": {"volume": 10.0, "volume_imbalance": -0.9}}
    ] * 3
    last = None
    for r in rows:
        last = strat.generate_order(make_state(r))

    assert isinstance(last, PortfolioOrder)
    assert last["A"].side == Side.SELL
    assert last["C"].side == Side.BUY


def test_rebalance_skipping():
    strat = OrderflowRankDailyStrategy(
        symbols=["A", "B"],
        lookback_bars=2,
        rebalance_bars=5,
        top_k=1,
    )
    rows = [
        {"A": {"volume": 10.0, "volume_imbalance": 0.5},
         "B": {"volume": 10.0, "volume_imbalance": -0.5}}
    ] * 3
    result = None
    for r in rows:
        result = strat.generate_order(make_state(r))
    assert result is None
