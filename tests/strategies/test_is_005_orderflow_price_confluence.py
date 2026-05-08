from __future__ import annotations

from datetime import datetime, timezone

from intraday.strategies.multi.orderflow_price_confluence_strategy import (
    OrderflowPriceConfluenceStrategy,
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


def test_agreement_continuation_picks_extremes():
    strat = OrderflowPriceConfluenceStrategy(
        symbols=["A", "B", "C"],
        lookback_bars=2,
        rebalance_bars=1,
        top_k=1,
        max_weight=0.5,
        direction="continuation",
        require_agreement=True,
    )
    rows = [
        {"A": {"close": 100, "volume": 10.0, "volume_imbalance": 0.9},
         "B": {"close": 100, "volume": 10.0, "volume_imbalance": 0.0},
         "C": {"close": 100, "volume": 10.0, "volume_imbalance": -0.9}},
        {"A": {"close": 102, "volume": 10.0, "volume_imbalance": 0.9},
         "B": {"close": 100, "volume": 10.0, "volume_imbalance": 0.0},
         "C": {"close": 98, "volume": 10.0, "volume_imbalance": -0.9}},
        {"A": {"close": 104, "volume": 10.0, "volume_imbalance": 0.9},
         "B": {"close": 100, "volume": 10.0, "volume_imbalance": 0.0},
         "C": {"close": 96, "volume": 10.0, "volume_imbalance": -0.9}},
    ]
    last = None
    for r in rows:
        last = _step(strat, r)

    assert isinstance(last, PortfolioOrder)
    assert last["A"].side == Side.BUY
    assert last["C"].side == Side.SELL


def test_disagreement_skips_signal():
    strat = OrderflowPriceConfluenceStrategy(
        symbols=["A", "B", "C"],
        lookback_bars=2,
        rebalance_bars=1,
        top_k=1,
        max_weight=0.5,
        direction="continuation",
        require_agreement=True,
    )
    rows = [
        {"A": {"close": 100, "volume": 10.0, "volume_imbalance": -0.9},
         "B": {"close": 100, "volume": 10.0, "volume_imbalance": 0.0},
         "C": {"close": 100, "volume": 10.0, "volume_imbalance": 0.9}},
        {"A": {"close": 102, "volume": 10.0, "volume_imbalance": -0.9},
         "B": {"close": 100, "volume": 10.0, "volume_imbalance": 0.0},
         "C": {"close": 98, "volume": 10.0, "volume_imbalance": 0.9}},
        {"A": {"close": 104, "volume": 10.0, "volume_imbalance": -0.9},
         "B": {"close": 100, "volume": 10.0, "volume_imbalance": 0.0},
         "C": {"close": 96, "volume": 10.0, "volume_imbalance": 0.9}},
    ]
    last = None
    for r in rows:
        last = _step(strat, r)
    assert last is None


def test_warmup_returns_none():
    strat = OrderflowPriceConfluenceStrategy(
        symbols=["A", "B"],
        lookback_bars=4,
        rebalance_bars=1,
    )
    result = _step(
        strat,
        {"A": {"close": 100, "volume": 10.0, "volume_imbalance": 0.5},
         "B": {"close": 100, "volume": 10.0, "volume_imbalance": -0.5}},
    )
    assert result is None
