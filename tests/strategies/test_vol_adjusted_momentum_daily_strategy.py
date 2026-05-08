from __future__ import annotations

from datetime import datetime

from intraday.strategies.multi.vol_adjusted_momentum_daily_strategy import (
    ALPHA_CELL,
    SOURCE_NOTES,
    VolAdjustedMomentumDailyStrategy,
)
from intraday.strategy import MarketState


def _state(panel: dict, ts: datetime | None = None) -> MarketState:
    return MarketState(
        timestamp=ts or datetime(2026, 3, 4, 0, 0),
        mid_price=0.0,
        imbalance=0.0,
        spread=0.0,
        spread_bps=0.0,
        best_bid=0.0,
        best_ask=0.0,
        best_bid_qty=0.0,
        best_ask_qty=0.0,
        panel=panel,
        positions={},
    )


def test_metadata():
    assert ALPHA_CELL["idea_family"] == "vol_adjusted_momentum"
    assert SOURCE_NOTES


def test_warmup_returns_none():
    s = VolAdjustedMomentumDailyStrategy(
        ["A", "B", "C"], lookback_bars=10, rv_bars=10, rebalance_bars=10
    )
    out = s.generate_order(_state({"A": {"close": 100}, "B": {"close": 100}, "C": {"close": 100}}))
    assert out is None


def test_strongest_momentum_goes_long():
    syms = ["A", "B", "C"]
    s = VolAdjustedMomentumDailyStrategy(
        syms, lookback_bars=20, rv_bars=20, rebalance_bars=20, top_k=1, min_score=0.0
    )
    out = None
    for t in range(60):
        panel = {
            "A": {"close": 100.0 + t * 0.5},  # uptrend
            "B": {"close": 100.0},
            "C": {"close": 100.0 - t * 0.5},  # downtrend
        }
        out = s.generate_order(_state(panel))
    assert out is not None
    assert out["A"] is not None and out["A"].side.value == "BUY"
    assert out["C"] is not None and out["C"].side.value == "SELL"
