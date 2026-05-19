"""Tests for XsMaxLotteryStrategy.

Pattern mirrors test_xs_volume_rank: feed daily panels across multiple
dates, then assert basket composition / weights when emission happens
at a day transition.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from intraday.strategies.multi.xs_max_lottery_strategy import (
    ALPHA_CELL,
    SOURCE_NOTES,
    XsMaxLotteryStrategy,
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


def _feed_days(strat, prices_by_day, *, positions=None):
    """Feed N daily closes, then trigger one more day transition with
    an empty panel so the strategy ranks and emits on yesterday's
    accumulator.

    ``prices_by_day`` is ``{date: {symbol: close}}`` in chronological
    order. Returns the PortfolioOrder from the trailing emission call.
    """
    days = sorted(prices_by_day.keys())
    for d in days:
        panel = {s: {"close": c} for s, c in prices_by_day[d].items()}
        strat.generate_order(_state(panel, ts=d, positions=positions))
    # Trigger transition after the last seeded day.
    trigger_day = days[-1] + timedelta(days=1)
    return strat.generate_order(_state({}, ts=trigger_day, positions=positions))


# --- ALPHA_CELL / SOURCE_NOTES contract --------------------------------------


def test_alpha_cell_has_required_keys():
    assert set(ALPHA_CELL) == {"bar", "transform", "horizon", "universe", "exit", "idea_family"}
    assert ALPHA_CELL["idea_family"] == "lottery_max"
    assert ALPHA_CELL["bar"] == "TIME"


def test_source_notes_non_empty():
    assert SOURCE_NOTES and all(p.startswith("research/notes/") for p in SOURCE_NOTES)


# --- MAX computation + lottery direction ------------------------------------


def test_short_top_max_long_bottom_max():
    """Lottery anomaly: short the coin with the biggest single-day spike,
    long the flattest one. We construct prices so the MAX-return ranking
    is unambiguous."""
    syms = ["SPIKY", "BORING"]
    strat = XsMaxLotteryStrategy(symbols=syms, lookback=3, max_weight=1.0)
    # 4 closes needed (lookback+1=4) so we can compute 3 daily returns.
    base = datetime(2024, 1, 1)
    days = [base + timedelta(days=i) for i in range(4)]
    prices = {
        # SPIKY: flat 100, 100, 100, then 200 — one giant +100% day.
        # BORING: 100, 101, 102, 103 — three ~1% days.
        days[0]: {"SPIKY": 100.0, "BORING": 100.0},
        days[1]: {"SPIKY": 100.0, "BORING": 101.0},
        days[2]: {"SPIKY": 100.0, "BORING": 102.0},
        days[3]: {"SPIKY": 200.0, "BORING": 103.0},
    }
    po = _feed_days(strat, prices)
    assert po is not None
    active = po.active_orders
    # SPIKY has MAX = 1.0 (top), BORING has MAX ≈ 0.0099 (bottom).
    # Lottery direction: SHORT the spiky, LONG the boring.
    assert active["SPIKY"].side is Side.SELL
    assert active["BORING"].side is Side.BUY


def test_reverse_flips_lottery_direction():
    syms = ["A", "B"]
    base = datetime(2024, 1, 1)
    days = [base + timedelta(days=i) for i in range(4)]
    prices = {
        days[0]: {"A": 100.0, "B": 100.0},
        days[1]: {"A": 100.0, "B": 101.0},
        days[2]: {"A": 100.0, "B": 102.0},
        days[3]: {"A": 200.0, "B": 103.0},  # A spikes
    }
    fwd = _feed_days(
        XsMaxLotteryStrategy(symbols=syms, lookback=3, max_weight=1.0, reverse=False),
        prices,
    )
    rev = _feed_days(
        XsMaxLotteryStrategy(symbols=syms, lookback=3, max_weight=1.0, reverse=True),
        prices,
    )
    # Forward: short A (high MAX), long B.
    assert fwd.active_orders["A"].side is Side.SELL
    # Reversed: long A, short B.
    assert rev.active_orders["A"].side is Side.BUY


# --- History requirement / silence before ready ------------------------------


def test_no_emission_until_lookback_plus_one_closes_collected():
    """With lookback=5 we need 6 closes before any symbol becomes eligible.
    Feeding only 3 days plus a trigger should return None — not enough
    history for MAX computation yet."""
    syms = ["A", "B"]
    strat = XsMaxLotteryStrategy(symbols=syms, lookback=5, max_weight=1.0)
    base = datetime(2024, 1, 1)
    prices = {
        base + timedelta(days=i): {"A": 100.0 + i, "B": 200.0 - i}
        for i in range(3)
    }
    po = _feed_days(strat, prices)
    assert po is None  # only 3 closes → 2 returns → still short of lookback


def test_emits_once_history_reaches_threshold():
    syms = ["A", "B"]
    strat = XsMaxLotteryStrategy(symbols=syms, lookback=3, max_weight=1.0)
    base = datetime(2024, 1, 1)
    # lookback=3 → need 4 closes; seed exactly 4.
    prices = {
        base + timedelta(days=i): {"A": 100.0 + i, "B": 200.0 - i}
        for i in range(4)
    }
    po = _feed_days(strat, prices)
    assert po is not None


# --- Weight formula ---------------------------------------------------------


def test_per_leg_weight_keeps_gross_near_one():
    """Same per_leg = 0.5/half rule as xs_volume_rank — gross ≈ 1.0."""
    syms = [f"S{i}" for i in range(10)]
    strat = XsMaxLotteryStrategy(symbols=syms, lookback=2, max_weight=1.0)
    base = datetime(2024, 1, 1)
    # Distinct spike days so the ranking is total.
    days = [base + timedelta(days=i) for i in range(3)]
    prices = {
        days[0]: {s: 100.0 for s in syms},
        days[1]: {s: 100.0 for s in syms},
        days[2]: {s: 100.0 + i for i, s in enumerate(syms)},
    }
    po = _feed_days(strat, prices)
    assert po is not None
    expected = 0.5 / 5  # half = 5
    for o in po.active_orders.values():
        assert o.weight == expected


def test_max_weight_caps_per_leg():
    syms = ["A", "B", "C", "D"]
    strat = XsMaxLotteryStrategy(symbols=syms, lookback=2, max_weight=0.1)
    base = datetime(2024, 1, 1)
    days = [base + timedelta(days=i) for i in range(3)]
    prices = {
        days[0]: {s: 100.0 for s in syms},
        days[1]: {s: 100.0 for s in syms},
        days[2]: {s: 100.0 + i for i, s in enumerate(syms)},
    }
    po = _feed_days(strat, prices)
    assert po is not None
    weights = [o.weight for o in po.active_orders.values()]
    assert weights and all(w == 0.1 for w in weights)  # 0.5/2=0.25 > cap 0.1


# --- Robustness -------------------------------------------------------------


def test_returns_none_when_panel_missing():
    strat = XsMaxLotteryStrategy(symbols=["A", "B"])
    state = MarketState(
        timestamp=datetime(2024, 1, 1),
        mid_price=0.0, imbalance=0.0, spread=0.0, spread_bps=0.0,
        best_bid=0.0, best_ask=0.0, best_bid_qty=0.0, best_ask_qty=0.0,
        panel=None, positions={},
    )
    assert strat.generate_order(state) is None


def test_skips_symbol_with_invalid_close():
    """A symbol whose recorded close is missing/zero/None must be
    excluded from history accumulation and from ranking."""
    syms = ["A", "B", "C", "D"]
    strat = XsMaxLotteryStrategy(symbols=syms, lookback=2, max_weight=1.0)
    base = datetime(2024, 1, 1)
    days = [base + timedelta(days=i) for i in range(3)]
    # C is None every day; D zero on the final day.
    prices = {
        days[0]: {"A": 100.0, "B": 100.0, "C": None, "D": 100.0},
        days[1]: {"A": 100.0, "B": 100.0, "C": None, "D": 100.0},
        days[2]: {"A": 110.0, "B": 105.0, "C": None, "D": 0.0},
    }
    po = _feed_days(strat, prices)
    assert po is not None
    # C never seeded → excluded; D's 0-close skipped on day 3 (only 2 closes,
    # below the lookback+1=3 floor) → excluded. Only A,B rank.
    assert set(po.active_orders) <= {"A", "B"}


def test_constructor_rejects_empty_symbols():
    with pytest.raises(ValueError):
        XsMaxLotteryStrategy(symbols=[])


def test_day_transition_required_for_emission():
    """Same-day repeated calls accumulate, never emit. Emission only on
    the first call of a new date."""
    syms = ["A", "B"]
    strat = XsMaxLotteryStrategy(symbols=syms, lookback=2, max_weight=1.0)
    base = datetime(2024, 1, 1)
    panel = {"A": {"close": 100.0}, "B": {"close": 100.0}}
    for _ in range(5):
        assert strat.generate_order(_state(panel, ts=base)) is None
