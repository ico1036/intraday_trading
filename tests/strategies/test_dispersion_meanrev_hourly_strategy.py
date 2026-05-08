"""Focused tests for DispersionMeanrevHourlyStrategy (is_012)."""
from __future__ import annotations

from datetime import datetime

from intraday.strategies.multi.dispersion_meanrev_hourly_strategy import (
    ALPHA_CELL,
    SOURCE_NOTES,
    DispersionMeanrevHourlyStrategy,
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


def test_metadata_present():
    assert ALPHA_CELL["idea_family"] == "dispersion_meanrev_xs"
    assert SOURCE_NOTES and all(p.startswith("research/notes/") for p in SOURCE_NOTES)


def test_warmup_returns_none():
    syms = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    strat = DispersionMeanrevHourlyStrategy(syms, lookback_bars=10, rebalance_bars=5)
    out = strat.generate_order(
        _state({s: {"close": 100.0 + i} for i, s in enumerate(syms)})
    )
    assert out is None


def test_overshooter_is_shorted():
    syms = ["A", "B", "C"]
    strat = DispersionMeanrevHourlyStrategy(
        syms, lookback_bars=20, rebalance_bars=20, top_k=1, entry_z=0.1
    )
    out = None
    for t in range(40):
        panel = {
            "A": {"close": 100.0 + t * 0.5},
            "B": {"close": 100.0},
            "C": {"close": 100.0},
        }
        out = strat.generate_order(_state(panel))
    assert out is not None
    a_order = out["A"]
    assert a_order is not None
    assert a_order.side.value == "SELL"


def test_undershooter_is_longed():
    syms = ["A", "B", "C"]
    strat = DispersionMeanrevHourlyStrategy(
        syms, lookback_bars=20, rebalance_bars=20, top_k=1, entry_z=0.1
    )
    out = None
    for t in range(40):
        panel = {
            "A": {"close": 100.0 - t * 0.5},
            "B": {"close": 100.0},
            "C": {"close": 100.0},
        }
        out = strat.generate_order(_state(panel))
    assert out is not None
    a_order = out["A"]
    assert a_order is not None
    assert a_order.side.value == "BUY"
