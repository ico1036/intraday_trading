"""Phase 2-4 — exit_check.py contract.

At the end of each orchestrator iteration, exit_check.decide() looks at the
run's expression_log.jsonl + PLAN budgets and returns an ExitDecision. When
``should_exit`` is True, the orchestrator writes the ``DONE`` sentinel.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.agent.v2.deterministic import exit_check as ec


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _entry(
    thesis_id: str,
    expression_id: str,
    failure_mode: str,
    *,
    verdict_after: str = "ACTIVE",
) -> dict:
    return {
        "thesis_id": thesis_id,
        "expression_id": expression_id,
        "failure_mode": failure_mode,
        "verdict_after": verdict_after,
    }


def _budget(**overrides) -> dict:
    b = {
        "max_trials": 10,
        "max_expressions_per_thesis": 5,
        "max_theses_per_run": 3,
    }
    b.update(overrides)
    return b


# ---------------------------------------------------------------------------
# Base.
# ---------------------------------------------------------------------------


def test_empty_log_continues():
    decision = ec.decide([], budget=_budget())
    assert decision.should_exit is False
    assert decision.reason is None


def test_single_active_entry_continues():
    log = [_entry("th_001", "exp_001", "SIGNAL_NOISY")]
    assert ec.decide(log, budget=_budget()).should_exit is False


# ---------------------------------------------------------------------------
# TARGETS_MET — APPROVED short-circuits.
# ---------------------------------------------------------------------------


def test_approved_triggers_exit():
    log = [
        _entry("th_001", "exp_001", "SIGNAL_NOISY"),
        _entry("th_001", "exp_002", "APPROVED", verdict_after="APPROVED"),
    ]
    decision = ec.decide(log, budget=_budget())
    assert decision.should_exit is True
    assert decision.reason == "TARGETS_MET"
    assert decision.winning_expression == "exp_002"


# ---------------------------------------------------------------------------
# MAX_TRIALS — total expressions cap.
# ---------------------------------------------------------------------------


def test_max_trials_triggers_exit():
    log = [
        _entry("th_001", f"exp_{i:03d}", "SIGNAL_NOISY")
        for i in range(1, 11)
    ]
    decision = ec.decide(log, budget=_budget(max_trials=10))
    assert decision.should_exit is True
    assert decision.reason == "MAX_TRIALS"


def test_below_max_trials_continues():
    log = [
        _entry("th_001", f"exp_{i:03d}", "SIGNAL_NOISY")
        for i in range(1, 10)
    ]
    assert ec.decide(log, budget=_budget(max_trials=10)).should_exit is False


# ---------------------------------------------------------------------------
# THESES_EXHAUSTED — all budgeted theses produced a non-ACTIVE terminal verdict.
# ---------------------------------------------------------------------------


def test_theses_exhausted_when_all_refuted():
    log = [
        _entry("th_001", "exp_001", "SIGNAL_NOISY", verdict_after="REFUTED"),
        _entry("th_002", "exp_002", "SIGNAL_NOISY", verdict_after="REFUTED"),
        _entry("th_003", "exp_003", "THESIS_INVERTED", verdict_after="REFUTED"),
    ]
    decision = ec.decide(log, budget=_budget(max_theses_per_run=3))
    assert decision.should_exit is True
    assert decision.reason == "THESES_EXHAUSTED"


def test_theses_not_exhausted_while_latest_active():
    log = [
        _entry("th_001", "exp_001", "SIGNAL_NOISY", verdict_after="REFUTED"),
        _entry("th_002", "exp_002", "SIGNAL_NOISY", verdict_after="REFUTED"),
        _entry("th_003", "exp_003", "SIGNAL_NOISY", verdict_after="ACTIVE"),
    ]
    # th_003 still active; can't exit even if theses cap is hit.
    decision = ec.decide(log, budget=_budget(max_theses_per_run=3))
    assert decision.should_exit is False


def test_theses_exhausted_with_mixed_terminal_verdicts():
    log = [
        _entry("th_001", "exp_001", "SIGNAL_SPARSE", verdict_after="EXHAUSTED"),
        _entry("th_002", "exp_002", "REGIME_DEPENDENT", verdict_after="SCOPE_RESTRICTED"),
        _entry("th_003", "exp_003", "THESIS_INVERTED", verdict_after="REFUTED"),
    ]
    # EXHAUSTED and SCOPE_RESTRICTED are NOT terminal for exit purposes — they
    # route back to compose_expression. Only REFUTED is terminal here.
    decision = ec.decide(log, budget=_budget(max_theses_per_run=3))
    assert decision.should_exit is False


def test_below_max_theses_continues():
    log = [
        _entry("th_001", "exp_001", "SIGNAL_NOISY", verdict_after="REFUTED"),
        _entry("th_002", "exp_002", "SIGNAL_NOISY", verdict_after="REFUTED"),
    ]
    assert ec.decide(log, budget=_budget(max_theses_per_run=3)).should_exit is False


# ---------------------------------------------------------------------------
# Ordering — approved wins over budget exhaustion.
# ---------------------------------------------------------------------------


def test_approved_beats_max_trials():
    log = [_entry("th_001", f"exp_{i:03d}", "SIGNAL_NOISY") for i in range(1, 10)]
    log.append(_entry("th_001", "exp_010", "APPROVED", verdict_after="APPROVED"))
    decision = ec.decide(log, budget=_budget(max_trials=10))
    assert decision.should_exit is True
    assert decision.reason == "TARGETS_MET"


# ---------------------------------------------------------------------------
# Log loading.
# ---------------------------------------------------------------------------


def test_load_log(tmp_path):
    path = tmp_path / "expression_log.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(_entry("th_001", "exp_001", "SIGNAL_NOISY"))
            for _ in range(2)
        )
        + "\n"
    )
    log = ec.load_log(path)
    assert len(log) == 2


# ---------------------------------------------------------------------------
# DONE sentinel writing.
# ---------------------------------------------------------------------------


def test_write_done_creates_sentinel(tmp_path):
    decision = ec.ExitDecision(
        should_exit=True,
        reason="TARGETS_MET",
        winning_expression="exp_010",
    )
    done_path = ec.write_done(tmp_path, decision)
    assert done_path.is_file()
    content = done_path.read_text()
    assert "TARGETS_MET" in content
    assert "exp_010" in content


def test_write_done_refuses_when_not_exiting(tmp_path):
    decision = ec.ExitDecision(should_exit=False)
    with pytest.raises(ec.ExitCheckError):
        ec.write_done(tmp_path, decision)
