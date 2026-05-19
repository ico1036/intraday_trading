"""Tests for XsAmihudIlliqStrategy.

Pattern: feed 3 consecutive days so the strategy has prev_prev_close,
prev_close, and prev_qv populated when the 4th day's first call triggers
ranking + emission.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from intraday.strategies.multi.xs_amihud_illiq_strategy import (
    ALPHA_CELL,
    SOURCE_NOTES,
    XsAmihudIlliqStrategy,
)
from intraday.strategy import MarketState, Side


def _state(panel: dict, *, ts: datetime, positions: dict | None = None) -> MarketState:
    panel = {
        s: ({**v, "timestamp": ts} if "timestamp" not in v else v)
        for s, v in panel.items()
    }
    return MarketState(
        timestamp=ts,
        mid_price=0.0, imbalance=0.0, spread=0.0, spread_bps=0.0,
        best_bid=0.0, best_ask=0.0, best_bid_qty=0.0, best_ask_qty=0.0,
        panel=panel, positions=positions or {},
    )


def _feed_days(strat, days_data, *, positions=None):
    days = sorted(days_data.keys())
    for d in days:
        strat.generate_order(_state(days_data[d], ts=d, positions=positions))
    trigger = days[-1] + timedelta(days=1)
    return strat.generate_order(_state({}, ts=trigger, positions=positions))


# --- ALPHA_CELL / SOURCE_NOTES contract --------------------------------------


def test_alpha_cell_keys():
    assert set(ALPHA_CELL) == {"bar", "transform", "horizon", "universe", "exit", "idea_family"}
    assert ALPHA_CELL["idea_family"] == "amihud_illiq"


def test_source_notes_non_empty():
    assert SOURCE_NOTES and all(p.startswith("research/notes/") for p in SOURCE_NOTES)


# --- Short top ILLIQ, long bottom -------------------------------------------


def test_short_high_illiq_long_low_illiq():
    """Symbol A: 10% move on $100 volume → ILLIQ huge. Symbol B: 1% move on
    $10000 volume → ILLIQ tiny. Lottery anomaly direction: short A, long B."""
    syms = ["FRAGILE", "DEEP"]
    strat = XsAmihudIlliqStrategy(symbols=syms, max_weight=1.0)
    base = datetime(2024, 1, 1)
    days = [base + timedelta(days=i) for i in range(3)]
    # Day 0: seed close (return undefined).
    # Day 1: FRAGILE 100→110 (+10%) on qv=100 → ILLIQ=0.001;
    #        DEEP    100→101 (+1%)  on qv=10000 → ILLIQ=1e-6.
    # Day 2: anything — only used to roll prev/prev_prev forward.
    data = {
        days[0]: {"FRAGILE": {"close": 100.0, "quote_volume": 100.0},
                  "DEEP":    {"close": 100.0, "quote_volume": 10000.0}},
        days[1]: {"FRAGILE": {"close": 110.0, "quote_volume": 100.0},
                  "DEEP":    {"close": 101.0, "quote_volume": 10000.0}},
        days[2]: {"FRAGILE": {"close": 110.0, "quote_volume": 100.0},
                  "DEEP":    {"close": 101.0, "quote_volume": 10000.0}},
    }
    po = _feed_days(strat, data)
    assert po is not None
    active = po.active_orders
    assert active["FRAGILE"].side is Side.SELL  # high ILLIQ → short
    assert active["DEEP"].side is Side.BUY      # low ILLIQ → long


def test_reverse_flips_direction():
    syms = ["FRAGILE", "DEEP"]
    base = datetime(2024, 1, 1)
    days = [base + timedelta(days=i) for i in range(3)]
    data = {
        days[0]: {"FRAGILE": {"close": 100.0, "quote_volume": 100.0},
                  "DEEP":    {"close": 100.0, "quote_volume": 10000.0}},
        days[1]: {"FRAGILE": {"close": 110.0, "quote_volume": 100.0},
                  "DEEP":    {"close": 101.0, "quote_volume": 10000.0}},
        days[2]: {"FRAGILE": {"close": 110.0, "quote_volume": 100.0},
                  "DEEP":    {"close": 101.0, "quote_volume": 10000.0}},
    }
    rev = _feed_days(
        XsAmihudIlliqStrategy(symbols=syms, max_weight=1.0, reverse=True), data
    )
    assert rev.active_orders["FRAGILE"].side is Side.BUY
    assert rev.active_orders["DEEP"].side is Side.SELL


# --- History requirement -----------------------------------------------------


def test_returns_none_without_two_prior_closes():
    """Need two prior closes plus prior qv to score a symbol."""
    syms = ["A", "B"]
    strat = XsAmihudIlliqStrategy(symbols=syms, max_weight=1.0)
    base = datetime(2024, 1, 1)
    # Only 1 day of data, no return computable.
    data = {
        base: {"A": {"close": 100.0, "quote_volume": 100.0},
               "B": {"close": 100.0, "quote_volume": 100.0}},
    }
    assert _feed_days(strat, data) is None


# --- Weight formula ---------------------------------------------------------


def test_per_leg_weight_uses_half_basket_formula():
    syms = [f"S{i}" for i in range(10)]
    base = datetime(2024, 1, 1)
    days = [base + timedelta(days=i) for i in range(3)]
    data = {}
    for d_idx, d in enumerate(days):
        data[d] = {
            s: {"close": 100.0 + i + d_idx, "quote_volume": 100.0 * (i + 1)}
            for i, s in enumerate(syms)
        }
    strat = XsAmihudIlliqStrategy(symbols=syms, max_weight=1.0)
    po = _feed_days(strat, data)
    assert po is not None
    expected = 0.5 / 5  # half=5
    for o in po.active_orders.values():
        assert o.weight == expected


def test_max_weight_caps_per_leg():
    syms = ["A", "B", "C", "D"]
    base = datetime(2024, 1, 1)
    days = [base + timedelta(days=i) for i in range(3)]
    data = {}
    for d_idx, d in enumerate(days):
        data[d] = {
            s: {"close": 100.0 + i + d_idx, "quote_volume": 100.0 * (i + 1)}
            for i, s in enumerate(syms)
        }
    strat = XsAmihudIlliqStrategy(symbols=syms, max_weight=0.1)
    po = _feed_days(strat, data)
    assert po is not None
    weights = [o.weight for o in po.active_orders.values()]
    assert weights and all(w == 0.1 for w in weights)  # 0.5/2=0.25 capped


# --- Input robustness -------------------------------------------------------


def test_returns_none_when_panel_missing():
    strat = XsAmihudIlliqStrategy(symbols=["A", "B"])
    state = MarketState(
        timestamp=datetime(2024, 1, 1),
        mid_price=0.0, imbalance=0.0, spread=0.0, spread_bps=0.0,
        best_bid=0.0, best_ask=0.0, best_bid_qty=0.0, best_ask_qty=0.0,
        panel=None, positions={},
    )
    assert strat.generate_order(state) is None


def test_skips_symbol_with_missing_qv():
    """Symbols whose prior qv is None get excluded from ranking."""
    syms = ["A", "B", "C"]
    strat = XsAmihudIlliqStrategy(symbols=syms, max_weight=1.0)
    base = datetime(2024, 1, 1)
    days = [base + timedelta(days=i) for i in range(3)]
    data = {
        days[0]: {"A": {"close": 100.0, "quote_volume": 100.0},
                  "B": {"close": 100.0, "quote_volume": 100.0},
                  "C": {"close": 100.0, "quote_volume": None}},
        days[1]: {"A": {"close": 110.0, "quote_volume": 100.0},
                  "B": {"close": 101.0, "quote_volume": 10000.0},
                  "C": {"close": 100.0, "quote_volume": None}},
        days[2]: {"A": {"close": 110.0, "quote_volume": 100.0},
                  "B": {"close": 101.0, "quote_volume": 10000.0},
                  "C": {"close": 100.0, "quote_volume": None}},
    }
    po = _feed_days(strat, data)
    assert po is not None
    assert set(po.active_orders) <= {"A", "B"}


def test_constructor_rejects_empty_symbols():
    with pytest.raises(ValueError):
        XsAmihudIlliqStrategy(symbols=[])
