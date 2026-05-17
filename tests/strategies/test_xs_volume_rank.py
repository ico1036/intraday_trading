"""Tests for XsVolumeRankStrategy.

The framework calls ``generate_order`` once per (symbol, bar) event.
The strategy accumulates quote_volume across calls within a date and
emits orders only at the FIRST call of the NEXT date. So every behavior
test feeds yesterday's panel then triggers a day transition via
``_emit_after_accumulating``.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from intraday.strategies.multi.xs_volume_rank_strategy import (
    ALPHA_CELL,
    SOURCE_NOTES,
    XsVolumeRankStrategy,
)
from intraday.strategy import MarketState, Side


D1 = datetime(2024, 1, 1)
D2 = datetime(2024, 1, 2)


def _state(panel: dict, positions: dict | None = None, ts: datetime = D1) -> MarketState:
    """Build a MarketState. Auto-injects ``ts`` into each panel entry's
    ``timestamp`` so the strategy's stale-data filter passes."""
    panel = {
        s: ({**v, "timestamp": ts} if "timestamp" not in v else v)
        for s, v in panel.items()
    }
    return MarketState(
        timestamp=ts,
        mid_price=0.0,
        imbalance=0.0,
        spread=0.0,
        spread_bps=0.0,
        best_bid=0.0,
        best_ask=0.0,
        best_bid_qty=0.0,
        best_ask_qty=0.0,
        panel=panel,
        positions=positions or {},
    )


def _emit_after_accumulating(strat, panel, positions=None):
    """Two-step: feed ``panel`` as yesterday's data, then trigger a day
    transition by calling with a new date. The strategy emits orders only
    on day transitions (decision once per day, based on yesterday's full
    accumulator) — intra-day calls just accumulate.

    The yesterday-feed must be on a date earlier than D1 so that D1's
    call is detected as a transition.
    """
    D0 = D1 - timedelta(days=1)
    strat.generate_order(_state(panel, positions=positions, ts=D0))
    return strat.generate_order(_state({}, positions=positions, ts=D1))


# --- ALPHA_CELL / SOURCE_NOTES contract --------------------------------------


def test_alpha_cell_has_required_keys():
    assert set(ALPHA_CELL) == {"bar", "transform", "horizon", "universe", "exit", "idea_family"}
    assert ALPHA_CELL["idea_family"] == "xs_volume_rank"


def test_source_notes_non_empty():
    assert SOURCE_NOTES and all(p.startswith("research/notes/") for p in SOURCE_NOTES)


# --- Basket composition ------------------------------------------------------


def test_ranks_top_half_long_bottom_half_short():
    syms = ["A", "B", "C", "D", "E", "F"]
    strat = XsVolumeRankStrategy(symbols=syms, max_weight=1.0)
    panel = {
        "A": {"quote_volume": 6.0},
        "B": {"quote_volume": 5.0},
        "C": {"quote_volume": 4.0},
        "D": {"quote_volume": 3.0},
        "E": {"quote_volume": 2.0},
        "F": {"quote_volume": 1.0},
    }
    po = _emit_after_accumulating(strat, panel)
    assert po is not None
    active = po.active_orders
    longs = {s for s, o in active.items() if o.side is Side.BUY}
    shorts = {s for s, o in active.items() if o.side is Side.SELL}
    assert longs == {"A", "B", "C"}
    assert shorts == {"D", "E", "F"}


def test_reverse_flips_long_short_assignment():
    syms = ["A", "B", "C", "D"]
    panel = {
        "A": {"quote_volume": 4.0},
        "B": {"quote_volume": 3.0},
        "C": {"quote_volume": 2.0},
        "D": {"quote_volume": 1.0},
    }
    fwd = _emit_after_accumulating(
        XsVolumeRankStrategy(symbols=syms, max_weight=1.0, reverse=False), panel
    )
    rev = _emit_after_accumulating(
        XsVolumeRankStrategy(symbols=syms, max_weight=1.0, reverse=True), panel
    )
    fwd_longs = {s for s, o in fwd.active_orders.items() if o.side is Side.BUY}
    rev_longs = {s for s, o in rev.active_orders.items() if o.side is Side.BUY}
    assert fwd_longs == {"A", "B"}
    assert rev_longs == {"C", "D"}


def test_odd_count_middle_symbol_excluded_from_basket():
    syms = ["A", "B", "C", "D", "E"]
    strat = XsVolumeRankStrategy(symbols=syms, max_weight=1.0)
    panel = {
        "A": {"quote_volume": 5.0},
        "B": {"quote_volume": 4.0},
        "C": {"quote_volume": 3.0},  # middle
        "D": {"quote_volume": 2.0},
        "E": {"quote_volume": 1.0},
    }
    po = _emit_after_accumulating(strat, panel)
    assert po is not None
    active = po.active_orders
    assert set(active) == {"A", "B", "D", "E"}
    assert "C" not in active


# --- Weight formula ---------------------------------------------------------


def test_per_leg_weight_keeps_gross_near_one():
    """per_leg = 0.5/half so gross = 2×half×per_leg = 1.0."""
    syms = [f"S{i}" for i in range(10)]
    strat = XsVolumeRankStrategy(symbols=syms, max_weight=1.0)
    panel = {s: {"quote_volume": float(i + 1)} for i, s in enumerate(syms)}
    po = _emit_after_accumulating(strat, panel)
    assert po is not None
    expected = 0.5 / 5  # half=5
    for o in po.active_orders.values():
        assert o.weight == expected


def test_max_weight_caps_per_leg():
    """max_weight binds when 0.5/half exceeds it."""
    syms = ["A", "B", "C", "D"]
    strat = XsVolumeRankStrategy(symbols=syms, max_weight=0.1)
    panel = {s: {"quote_volume": float(i + 1)} for i, s in enumerate(syms)}
    po = _emit_after_accumulating(strat, panel)
    assert po is not None
    # half=2, 0.5/2=0.25, max_weight=0.1 caps
    weights = [o.weight for o in po.active_orders.values()]
    assert weights and all(w == 0.1 for w in weights)


def test_per_leg_weight_uses_exact_formula():
    # half=5, max_weight=1.0 → per_leg = 0.5/5 = 0.1 (formula binds)
    s10 = [f"S{i}" for i in range(10)]
    po1 = _emit_after_accumulating(
        XsVolumeRankStrategy(symbols=s10, max_weight=1.0),
        {s: {"quote_volume": float(i + 1)} for i, s in enumerate(s10)},
    )
    assert all(o.weight == 0.5 / 5 for o in po1.active_orders.values())
    # half=2, max_weight=0.07 → 0.07 < 0.25, max_weight caps
    s4 = ["A", "B", "C", "D"]
    po2 = _emit_after_accumulating(
        XsVolumeRankStrategy(symbols=s4, max_weight=0.07),
        {s: {"quote_volume": float(i + 1)} for i, s in enumerate(s4)},
    )
    assert all(o.weight == 0.07 for o in po2.active_orders.values())


# --- Input handling ---------------------------------------------------------


def test_skips_symbol_with_missing_or_zero_quote_volume():
    syms = ["A", "B", "C", "D"]
    strat = XsVolumeRankStrategy(symbols=syms, max_weight=1.0)
    panel = {
        "A": {"quote_volume": 4.0},
        "B": {"quote_volume": 3.0},
        "C": {"quote_volume": None},
        "D": {"quote_volume": 0.0},
    }
    po = _emit_after_accumulating(strat, panel)
    assert po is not None
    active = po.active_orders
    longs = {s for s, o in active.items() if o.side is Side.BUY}
    shorts = {s for s, o in active.items() if o.side is Side.SELL}
    assert longs == {"A"}
    assert shorts == {"B"}


def test_returns_none_when_panel_missing():
    strat = XsVolumeRankStrategy(symbols=["A", "B"])
    state = MarketState(
        timestamp=D1,
        mid_price=0.0, imbalance=0.0, spread=0.0, spread_bps=0.0,
        best_bid=0.0, best_ask=0.0, best_bid_qty=0.0, best_ask_qty=0.0,
        panel=None, positions={},
    )
    assert strat.generate_order(state) is None


def test_returns_none_when_fewer_than_two_valid_symbols():
    strat = XsVolumeRankStrategy(symbols=["A", "B"], max_weight=1.0)
    po = _emit_after_accumulating(strat, {"A": {"quote_volume": 1.0}})
    assert po is None


def test_stale_panel_entry_is_excluded_from_ranking():
    """A symbol whose panel timestamp is from a prior date must be
    excluded — guards the framework's _latest_candles staleness."""
    syms = ["A", "B", "C"]
    strat = XsVolumeRankStrategy(symbols=syms, max_weight=1.0)
    D0 = D1 - timedelta(days=1)
    older = D0 - timedelta(days=2)
    panel = {
        "A": {"quote_volume": 5.0, "timestamp": D0},  # fresh for D0
        "B": {"quote_volume": 3.0, "timestamp": D0},  # fresh for D0
        "C": {"quote_volume": 999.0, "timestamp": older},  # stale
    }
    # Accumulate on D0 (A and B pass stale filter; C excluded), then
    # trigger transition on D1.
    strat.generate_order(_state(panel, ts=D0))
    po = strat.generate_order(_state({}, ts=D1))
    assert po is not None
    active = po.active_orders
    assert set(active) == {"A", "B"}


# --- Position-aware emission ------------------------------------------------


def test_reissues_each_day_to_maintain_target_weight():
    """Variable per_leg = 0.5/half maintains gross=1.0. Framework's delta
    execution naturally skips zero-delta cases, but the strategy always
    emits target weights each day so per_leg drift is captured."""
    syms = ["A", "B"]
    strat = XsVolumeRankStrategy(symbols=syms, max_weight=1.0)
    panel = {"A": {"quote_volume": 2.0}, "B": {"quote_volume": 1.0}}
    positions = {"A": {"side": "LONG"}, "B": {"side": "SHORT"}}
    po = _emit_after_accumulating(strat, panel, positions=positions)
    assert po is not None
    # Strategy emits target weights every day (variable per_leg approach).
    active = po.active_orders
    assert active["A"].side is Side.BUY  # A in long basket
    assert active["A"].weight == 0.5     # per_leg = 0.5/1 = 0.5
    assert active["B"].side is Side.SELL
    assert active["B"].weight == 0.5


def test_unranked_held_long_position_is_closed():
    syms = ["A", "B", "C", "D", "E"]
    strat = XsVolumeRankStrategy(symbols=syms, max_weight=1.0)
    panel = {
        "A": {"quote_volume": 5.0},
        "B": {"quote_volume": 4.0},
        "C": {"quote_volume": 3.0},
        "D": {"quote_volume": 2.0},
        "E": {"quote_volume": 1.0},
    }
    positions = {"C": {"side": "LONG"}}
    po = _emit_after_accumulating(strat, panel, positions=positions)
    assert po is not None
    assert "C" in po.active_orders
    assert po.active_orders["C"].side is Side.SELL  # close-long is SELL


def test_long_to_short_direction_reversal_emits_sell_with_weight():
    syms = ["A", "B"]
    strat = XsVolumeRankStrategy(symbols=syms, max_weight=1.0)
    panel = {"A": {"quote_volume": 1.0}, "B": {"quote_volume": 2.0}}
    positions = {"A": {"side": "LONG"}, "B": {"side": "SHORT"}}
    po = _emit_after_accumulating(strat, panel, positions=positions)
    assert po is not None
    active = po.active_orders
    # A flips LONG → SHORT (new rank puts A in bottom). per_leg = 0.5/1 = 0.5.
    assert active["A"].side is Side.SELL
    assert active["A"].weight == 0.5
    assert active["B"].side is Side.BUY
    assert active["B"].weight == 0.5


# --- Day-transition / accumulator semantics ---------------------------------


def test_emits_only_on_day_transition_not_same_day():
    """Intra-day calls accumulate without emitting. Emission happens at
    the next-day's first call, using yesterday's complete accumulator."""
    syms = ["A", "B"]
    strat = XsVolumeRankStrategy(symbols=syms, max_weight=1.0)
    panel = {"A": {"quote_volume": 2.0}, "B": {"quote_volume": 1.0}}
    # Multiple same-day calls on D1 — none emit, just accumulate.
    for _ in range(5):
        assert strat.generate_order(_state(panel, ts=D1)) is None
    # Day transition D1 → D2 with empty panel triggers emission using
    # the D1 accumulator.
    po = strat.generate_order(_state({}, ts=D2))
    assert po is not None


def test_first_call_ever_does_not_emit():
    """No prior accumulator → first ever call cannot trigger transition."""
    strat = XsVolumeRankStrategy(symbols=["A", "B"], max_weight=1.0)
    panel = {"A": {"quote_volume": 2.0}, "B": {"quote_volume": 1.0}}
    assert strat.generate_order(_state(panel, ts=D1)) is None


def test_rebalance_bars_throttles_day_transitions():
    """rebalance_bars=2 → emit on every 2nd day transition."""
    syms = ["A", "B"]
    strat = XsVolumeRankStrategy(symbols=syms, max_weight=1.0, rebalance_bars=2)
    panel = {"A": {"quote_volume": 2.0}, "B": {"quote_volume": 1.0}}
    days = [D1, D2, D2 + timedelta(days=1), D2 + timedelta(days=2)]
    emissions = [strat.generate_order(_state(panel, ts=d)) for d in days]
    # day_count increments per transition: 1 (D1→D2), 2 (D2→D3), 3 (D3→D4).
    # rebalance_bars=2 → emit when count % 2 == 0: only count 2 (D2→D3).
    statuses = [e is not None for e in emissions]
    assert statuses == [False, False, True, False]


# --- Constructor validation -------------------------------------------------


def test_constructor_rejects_empty_symbols():
    with pytest.raises(ValueError):
        XsVolumeRankStrategy(symbols=[])
