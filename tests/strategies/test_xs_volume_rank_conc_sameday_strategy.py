"""Tests for XsVolumeRankConcSamedayStrategy.

Key contract vs XsVolumeRankConcStrategy: ``_commit_yesterday`` replaces
the rank universe with the *current day's* reporters instead of
union'ing them. Symbols absent from a day's panel drop out for the next
ranking. This file pins that behavior.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from intraday.strategies.multi.xs_volume_rank_conc_sameday_strategy import (
    ALPHA_CELL,
    SOURCE_NOTES,
    XsVolumeRankConcSamedayStrategy,
)
from intraday.strategy import MarketState, Side


D0 = datetime(2024, 1, 1)
D1 = datetime(2024, 1, 2)
D2 = datetime(2024, 1, 3)


def _state(panel: dict, ts: datetime, positions: dict | None = None) -> MarketState:
    panel = {s: ({**v, "timestamp": ts} if "timestamp" not in v else v)
             for s, v in panel.items()}
    return MarketState(
        timestamp=ts, mid_price=0.0, imbalance=0.0, spread=0.0,
        spread_bps=0.0, best_bid=0.0, best_ask=0.0, best_bid_qty=0.0,
        best_ask_qty=0.0, panel=panel, positions=positions or {},
    )


def test_alpha_cell_uniqueness():
    assert ALPHA_CELL["idea_family"] == "xs_vrev_conc_sameday"
    assert set(ALPHA_CELL) == {"bar", "transform", "horizon", "universe", "exit", "idea_family"}
    assert SOURCE_NOTES and all(p.startswith("research/notes/") for p in SOURCE_NOTES)


def test_sameday_universe_drops_missing_symbols():
    """If a symbol reported on D0 but not D1, it must not appear in the
    D2 ranking universe (the prior strategy would keep it stale).
    Min universe size = 4 is required by the strategy."""
    syms = ["A", "B", "C", "D", "E", "F"]
    strat = XsVolumeRankConcSamedayStrategy(
        symbols=syms, max_weight=1.0, concentration_pct=0.25,
    )
    # D0: all six report
    strat.generate_order(_state({s: {"quote_volume": float(i + 1)}
                                 for i, s in enumerate(syms)}, ts=D0))
    # D1: only A B C D report (E and F miss the day) — this commits D0.
    strat.generate_order(_state({
        "A": {"quote_volume": 1.0},
        "B": {"quote_volume": 2.0},
        "C": {"quote_volume": 3.0},
        "D": {"quote_volume": 4.0},
    }, ts=D1))
    # D2: commits D1's universe — must be exactly {A, B, C, D}, NOT all six.
    po = strat.generate_order(_state({}, ts=D2))
    assert po is not None
    active = po.active_orders
    # k = max(1, int(4 * 0.25)) = 1 — long lowest qv (A), short highest (D)
    long = {s for s, o in active.items() if o.side is Side.BUY and o.weight > 0}
    short = {s for s, o in active.items() if o.side is Side.SELL and o.weight > 0}
    assert long == {"A"}
    assert short == {"D"}
    # E and F must NOT be in any leg — dropped from same-day universe.
    assert "E" not in long and "E" not in short
    assert "F" not in long and "F" not in short


def test_concentration_pct_takes_top_and_bottom_q():
    """q=0.2, n=10 → k=2: long the 2 lowest qv, short the 2 highest."""
    syms = [f"S{i}" for i in range(10)]
    strat = XsVolumeRankConcSamedayStrategy(
        symbols=syms, max_weight=1.0, concentration_pct=0.2,
    )
    panel = {s: {"quote_volume": float(i + 1)} for i, s in enumerate(syms)}
    strat.generate_order(_state(panel, ts=D0))
    po = strat.generate_order(_state({}, ts=D1))
    assert po is not None
    longs = {s for s, o in po.active_orders.items() if o.side is Side.BUY and o.weight > 0}
    shorts = {s for s, o in po.active_orders.items() if o.side is Side.SELL and o.weight > 0}
    assert longs == {"S0", "S1"}  # smallest qv
    assert shorts == {"S8", "S9"}  # largest qv


def test_per_leg_weight_is_half_over_k():
    """per_leg = min(max_weight, 0.5/k). With k=2 and max_weight=1.0 → 0.25."""
    syms = [f"S{i}" for i in range(10)]
    strat = XsVolumeRankConcSamedayStrategy(
        symbols=syms, max_weight=1.0, concentration_pct=0.2,
    )
    panel = {s: {"quote_volume": float(i + 1)} for i, s in enumerate(syms)}
    strat.generate_order(_state(panel, ts=D0))
    po = strat.generate_order(_state({}, ts=D1))
    assert po is not None
    weights = [abs(o.weight) for o in po.active_orders.values() if o.weight != 0]
    assert weights and all(abs(w - 0.25) < 1e-9 for w in weights)


def test_constructor_rejects_empty_symbols():
    with pytest.raises(ValueError):
        XsVolumeRankConcSamedayStrategy(symbols=[])
