"""Phase 2-1 — classify_failure.py contract.

Client-first tests: given metrics + targets, what failure_mode do we emit?
We pin canonical cases for each enum value, plus the APPROVED path.
"""
from __future__ import annotations

import pytest

from scripts.agent.v2.deterministic.classify_failure import (
    FAILURE_MODES,
    classify,
)


# ---------------------------------------------------------------------------
# Fixtures — the "targets" shape mirrors config/targets.yaml.
# ---------------------------------------------------------------------------


@pytest.fixture
def targets():
    return {
        "primary": {
            "profit_factor": {"op": ">=", "value": 1.3},
            "max_drawdown": {"op": ">=", "value": -0.15},
            "total_return": {"op": ">=", "value": 0.05},
            "total_trades": {"op": ">=", "value": 30},
        },
        "auto_reject": {
            "win_rate": {"op": "<", "value": 0.10},
            "sharpe": {"op": "<", "value": -0.5},
            "total_trades": {"op": "<", "value": 5},
        },
    }


def metrics(**overrides):
    defaults = {
        "profit_factor": 1.5,
        "max_drawdown": -0.10,
        "total_return": 0.08,
        "total_trades": 50,
        "win_rate": 0.45,
        "sharpe": 0.8,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# APPROVED path.
# ---------------------------------------------------------------------------


def test_classify_returns_approved_when_all_primary_gates_pass(targets):
    assert classify(metrics(), targets) == "APPROVED"


def test_classify_returns_approved_on_boundary_values(targets):
    m = metrics(
        profit_factor=1.3,
        max_drawdown=-0.15,
        total_return=0.05,
        total_trades=30,
    )
    assert classify(m, targets) == "APPROVED"


# ---------------------------------------------------------------------------
# SIGNAL_SPARSE — too few trades.
# ---------------------------------------------------------------------------


def test_signal_sparse_when_trades_below_auto_reject(targets):
    m = metrics(total_trades=3)
    assert classify(m, targets) == "SIGNAL_SPARSE"


def test_signal_sparse_when_trades_below_primary_but_above_auto_reject(targets):
    # 10 trades: above auto_reject (5) but below primary (30). Too sparse
    # to conclude anything — treat as SIGNAL_SPARSE, not SIGNAL_NOISY.
    m = metrics(total_trades=10, win_rate=0.50, profit_factor=1.0)
    assert classify(m, targets) == "SIGNAL_SPARSE"


# ---------------------------------------------------------------------------
# THESIS_INVERTED — systematic losing.
# ---------------------------------------------------------------------------


def test_thesis_inverted_on_catastrophic_win_rate(targets):
    m = metrics(win_rate=0.05, total_trades=100, profit_factor=0.4)
    assert classify(m, targets) == "THESIS_INVERTED"


def test_thesis_inverted_on_deeply_negative_sharpe(targets):
    m = metrics(sharpe=-1.2, total_trades=80, win_rate=0.30)
    assert classify(m, targets) == "THESIS_INVERTED"


# ---------------------------------------------------------------------------
# SIGNAL_NOISY — enough trades, coin-flip behaviour.
# ---------------------------------------------------------------------------


def test_signal_noisy_when_profit_factor_near_one(targets):
    m = metrics(
        total_trades=100,
        profit_factor=1.02,
        win_rate=0.50,
        total_return=0.001,
    )
    assert classify(m, targets) == "SIGNAL_NOISY"


def test_signal_noisy_when_win_rate_near_half(targets):
    m = metrics(
        total_trades=80,
        profit_factor=0.98,
        win_rate=0.49,
        total_return=-0.002,
    )
    assert classify(m, targets) == "SIGNAL_NOISY"


# ---------------------------------------------------------------------------
# FEE_DOMINATED — gross positive, net negative.
# ---------------------------------------------------------------------------


def test_fee_dominated_when_gross_positive_and_net_negative(targets):
    m = metrics(
        total_trades=200,
        total_return=-0.03,
        gross_return=0.05,
        net_return=-0.03,
        profit_factor=0.9,
    )
    assert classify(m, targets) == "FEE_DOMINATED"


def test_not_fee_dominated_when_both_negative(targets):
    m = metrics(
        total_trades=200,
        gross_return=-0.02,
        net_return=-0.04,
        profit_factor=0.8,
        win_rate=0.48,
    )
    # Gross is also negative → it's the signal, not the fees.
    assert classify(m, targets) != "FEE_DOMINATED"


# ---------------------------------------------------------------------------
# OVERFIT_SYMBOL — one symbol carries, others fail.
# ---------------------------------------------------------------------------


def test_overfit_symbol_when_one_symbol_carries(targets):
    m = metrics(
        total_trades=100,
        profit_factor=1.0,
        per_symbol_return={
            "BTCUSDT": 0.15,
            "ETHUSDT": -0.04,
            "SOLUSDT": -0.05,
        },
    )
    assert classify(m, targets) == "OVERFIT_SYMBOL"


def test_not_overfit_symbol_when_single_symbol(targets):
    m = metrics(
        total_trades=100,
        profit_factor=1.0,
        per_symbol_return={"BTCUSDT": -0.02},
        win_rate=0.49,
    )
    # Single symbol universe can't be "overfit to one" — other mode applies.
    assert classify(m, targets) != "OVERFIT_SYMBOL"


# ---------------------------------------------------------------------------
# REGIME_DEPENDENT — concentrated in one regime bucket.
# ---------------------------------------------------------------------------


def test_regime_dependent_when_pnl_concentrated(targets):
    m = metrics(
        total_trades=120,
        profit_factor=1.1,
        per_regime_return={
            "high_vol": 0.14,
            "low_vol": -0.05,
            "range": -0.03,
        },
    )
    assert classify(m, targets) == "REGIME_DEPENDENT"


# ---------------------------------------------------------------------------
# LATE_ENTRY / EDGE_DECAY — require trade-level hints.
# ---------------------------------------------------------------------------


def test_late_entry_when_entry_is_past_peak(targets):
    m = metrics(
        total_trades=60,
        profit_factor=0.95,
        entry_to_peak_ratio=0.15,  # captured only 15% of move
        win_rate=0.40,
    )
    assert classify(m, targets) == "LATE_ENTRY"


def test_edge_decay_when_pnl_front_loaded_but_exit_worse(targets):
    m = metrics(
        total_trades=80,
        profit_factor=0.92,
        median_bar_to_peak=1,     # peak at bar 1
        median_bars_held=10,      # hold 10 bars
        win_rate=0.42,
    )
    assert classify(m, targets) == "EDGE_DECAY"


# ---------------------------------------------------------------------------
# OTHER — catch-all when nothing matches.
# ---------------------------------------------------------------------------


def test_other_when_no_rule_matches(targets):
    # Primary fails but not catastrophically; no extras supplied.
    m = metrics(
        total_trades=60,
        profit_factor=1.2,
        total_return=0.03,
        win_rate=0.38,
    )
    assert classify(m, targets) == "OTHER"


# ---------------------------------------------------------------------------
# Invariants.
# ---------------------------------------------------------------------------


def test_classify_output_is_always_in_enum(targets):
    """Every classify() result must be in FAILURE_MODES or "APPROVED"."""
    cases = [
        metrics(),  # approved
        metrics(total_trades=2),  # sparse
        metrics(win_rate=0.02, total_trades=100),  # inverted
        metrics(total_trades=60, profit_factor=1.0, win_rate=0.5),  # noisy
    ]
    for m in cases:
        result = classify(m, targets)
        assert result == "APPROVED" or result in FAILURE_MODES, result


def test_failure_modes_set_matches_yaml():
    """Module-level FAILURE_MODES must stay in sync with the YAML enum."""
    import yaml
    from pathlib import Path

    data = yaml.safe_load(
        (Path(__file__).parent.parent / "config/failure_modes.yaml").read_text()
    )
    assert set(FAILURE_MODES) == set(data["modes"].keys())
