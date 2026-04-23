"""Phase 2-3 — thesis_gate.py contract.

Given a thesis's seen expressions (each with an expression_spec + failure_mode),
the gate emits exactly one verdict. The verdict drives orchestrator routing:

    ACTIVE             → Researcher.compose_expression (same axes OK)
    EXHAUSTED          → Researcher.compose_expression (new axes required)
    SCOPE_RESTRICTED   → Researcher.compose_expression (add filter)
    REFUTED            → Researcher.new_thesis
    APPROVED           → done, write DONE sentinel
"""
from __future__ import annotations

import pytest

from scripts.agent.v2.deterministic import thesis_gate as tg


# ---------------------------------------------------------------------------
# Builders.
# ---------------------------------------------------------------------------


def _spec(**overrides):
    base = dict(
        bar_domain="VOLUME",
        bar_granularity="medium",
        signal_form="raw",
        threshold_type="absolute",
        aggregation="instantaneous",
        regime_filter="none",
        exit_rule="time_stop",
        sizing="fixed",
        universe="single_symbol",
    )
    base.update(overrides)
    return base


def _seen(expression_id, failure_mode, **spec_overrides):
    return {
        "expression_id": expression_id,
        "failure_mode": failure_mode,
        "expression_spec": _spec(**spec_overrides),
    }


# ---------------------------------------------------------------------------
# Base cases.
# ---------------------------------------------------------------------------


def test_empty_seen_is_active():
    v = tg.decide([])
    assert v.status == "ACTIVE"
    assert v.next_action == "compose_expression"


def test_approved_short_circuits():
    seen = [
        _seen("exp_001", "SIGNAL_NOISY"),
        _seen("exp_002", "APPROVED", signal_form="z_score"),
    ]
    v = tg.decide(seen)
    assert v.status == "APPROVED"
    assert v.next_action == "stop"


def test_single_failure_is_active():
    seen = [_seen("exp_001", "SIGNAL_NOISY")]
    assert tg.decide(seen).status == "ACTIVE"


def test_two_failures_same_mode_is_still_active():
    seen = [
        _seen("exp_001", "SIGNAL_NOISY"),
        _seen("exp_002", "SIGNAL_NOISY", signal_form="z_score"),
    ]
    # Only 2 — need 3 for evidence.
    assert tg.decide(seen).status == "ACTIVE"


# ---------------------------------------------------------------------------
# REFUTED — thesis-implicating mode ≥3 times, ≥3 axes differ.
# ---------------------------------------------------------------------------


def test_refuted_on_three_orthogonal_signal_noisy():
    seen = [
        _seen("exp_001", "SIGNAL_NOISY"),
        _seen(
            "exp_002",
            "SIGNAL_NOISY",
            signal_form="z_score",
            threshold_type="adaptive_quantile",
        ),
        _seen(
            "exp_003",
            "SIGNAL_NOISY",
            signal_form="rolling_rank",
            threshold_type="regime_conditional",
            regime_filter="vol_regime",
        ),
    ]
    v = tg.decide(seen)
    assert v.status == "REFUTED"
    assert v.triggered_by == "SIGNAL_NOISY"
    assert v.next_action == "new_thesis"
    assert len(v.orthogonality_axes) >= 3
    assert set(v.expressions_evaluated) == {"exp_001", "exp_002", "exp_003"}


def test_refuted_on_three_orthogonal_thesis_inverted():
    seen = [
        _seen("exp_001", "THESIS_INVERTED"),
        _seen("exp_002", "THESIS_INVERTED", aggregation="ema", exit_rule="sl_tp"),
        _seen(
            "exp_003",
            "THESIS_INVERTED",
            signal_form="z_score",
            threshold_type="adaptive_quantile",
            aggregation="cumulative_bucket",
        ),
    ]
    assert tg.decide(seen).status == "REFUTED"


def test_not_refuted_when_orthogonality_insufficient():
    """3 expressions differing on only 1 axis — not real orthogonality."""
    seen = [
        _seen("exp_001", "SIGNAL_NOISY"),
        _seen("exp_002", "SIGNAL_NOISY", bar_granularity="fine"),
        _seen("exp_003", "SIGNAL_NOISY", bar_granularity="coarse"),
    ]
    v = tg.decide(seen)
    assert v.status == "ACTIVE"


# ---------------------------------------------------------------------------
# EXHAUSTED — expression-implicating mode ≥3 orthogonal.
# ---------------------------------------------------------------------------


def test_exhausted_on_three_orthogonal_signal_sparse():
    seen = [
        _seen("exp_001", "SIGNAL_SPARSE"),
        _seen(
            "exp_002",
            "SIGNAL_SPARSE",
            threshold_type="adaptive_quantile",
            signal_form="z_score",
        ),
        _seen(
            "exp_003",
            "SIGNAL_SPARSE",
            aggregation="ema",
            exit_rule="signal_reversal",
            regime_filter="vol_regime",
        ),
    ]
    v = tg.decide(seen)
    assert v.status == "EXHAUSTED"
    assert v.triggered_by == "SIGNAL_SPARSE"
    assert v.next_action == "compose_expression"
    assert "new_axis_required" in v.hints


def test_exhausted_on_three_orthogonal_fee_dominated():
    seen = [
        _seen("exp_001", "FEE_DOMINATED"),
        _seen(
            "exp_002",
            "FEE_DOMINATED",
            bar_granularity="coarse",
            exit_rule="sl_tp",
            aggregation="ema",
        ),
        _seen(
            "exp_003",
            "FEE_DOMINATED",
            bar_domain="TIME",
            signal_form="z_score",
            threshold_type="adaptive_quantile",
        ),
    ]
    assert tg.decide(seen).status == "EXHAUSTED"


# ---------------------------------------------------------------------------
# SCOPE_RESTRICTED — scope-implicating mode ≥3 orthogonal.
# ---------------------------------------------------------------------------


def test_scope_restricted_on_regime_dependent():
    seen = [
        _seen("exp_001", "REGIME_DEPENDENT"),
        _seen(
            "exp_002",
            "REGIME_DEPENDENT",
            signal_form="z_score",
            threshold_type="adaptive_quantile",
            aggregation="ema",
        ),
        _seen(
            "exp_003",
            "REGIME_DEPENDENT",
            bar_granularity="coarse",
            exit_rule="sl_tp",
            sizing="vol_targeted",
        ),
    ]
    v = tg.decide(seen)
    assert v.status == "SCOPE_RESTRICTED"
    assert v.next_action == "compose_expression"
    assert "add_scope_filter" in v.hints


def test_scope_restricted_on_overfit_symbol():
    seen = [
        _seen("exp_001", "OVERFIT_SYMBOL"),
        _seen(
            "exp_002",
            "OVERFIT_SYMBOL",
            bar_domain="TIME",
            signal_form="z_score",
            exit_rule="trailing",
        ),
        _seen(
            "exp_003",
            "OVERFIT_SYMBOL",
            threshold_type="adaptive_quantile",
            aggregation="ema",
            regime_filter="vol_regime",
        ),
    ]
    assert tg.decide(seen).status == "SCOPE_RESTRICTED"


# ---------------------------------------------------------------------------
# Mixed failures — no single mode dominates → ACTIVE.
# ---------------------------------------------------------------------------


def test_mixed_failure_modes_stay_active():
    seen = [
        _seen("exp_001", "SIGNAL_SPARSE"),
        _seen("exp_002", "SIGNAL_NOISY", signal_form="z_score"),
        _seen("exp_003", "LATE_ENTRY", bar_domain="TIME"),
    ]
    v = tg.decide(seen)
    assert v.status == "ACTIVE"


# ---------------------------------------------------------------------------
# Configurability.
# ---------------------------------------------------------------------------


def test_config_can_raise_min_evidence():
    seen = [
        _seen("exp_001", "SIGNAL_NOISY"),
        _seen("exp_002", "SIGNAL_NOISY", signal_form="z_score", bar_domain="TIME"),
        _seen(
            "exp_003",
            "SIGNAL_NOISY",
            signal_form="rolling_rank",
            bar_domain="TIME",
            exit_rule="sl_tp",
            regime_filter="vol_regime",
        ),
    ]
    # Default min_evidence=3 → REFUTED
    assert tg.decide(seen).status == "REFUTED"
    # Raised to 5 → ACTIVE
    assert tg.decide(seen, min_evidence=5).status == "ACTIVE"


def test_config_can_raise_min_orthogonal_axes():
    seen = [
        _seen("exp_001", "SIGNAL_NOISY"),
        _seen("exp_002", "SIGNAL_NOISY", signal_form="z_score"),
        _seen(
            "exp_003",
            "SIGNAL_NOISY",
            signal_form="rolling_rank",
            threshold_type="adaptive_quantile",
            regime_filter="vol_regime",
        ),
    ]
    # Default min_axes=3 → REFUTED (3 axes differ)
    assert tg.decide(seen).status == "REFUTED"
    # Raised to 5 → ACTIVE (not enough spread)
    assert tg.decide(seen, min_orthogonal_axes=5).status == "ACTIVE"


# ---------------------------------------------------------------------------
# Rendering.
# ---------------------------------------------------------------------------


def test_render_verdict_markdown_includes_frontmatter():
    seen = [
        _seen("exp_001", "SIGNAL_NOISY"),
        _seen("exp_002", "SIGNAL_NOISY", signal_form="z_score"),
        _seen(
            "exp_003",
            "SIGNAL_NOISY",
            signal_form="rolling_rank",
            threshold_type="adaptive_quantile",
            regime_filter="vol_regime",
        ),
    ]
    v = tg.decide(seen)
    md = tg.render_markdown(v, thesis_id="th_001")
    assert md.startswith("---\n")
    assert "verdict: REFUTED" in md
    assert "thesis_id: th_001" in md
    assert "triggered_by" in md
    assert "SIGNAL_NOISY" in md
    assert "exp_001" in md and "exp_003" in md


# ---------------------------------------------------------------------------
# I/O — reading seen_failure_modes.jsonl.
# ---------------------------------------------------------------------------


def test_load_seen_from_jsonl(tmp_path):
    jsonl = tmp_path / "seen.jsonl"
    jsonl.write_text(
        '{"expression_id":"exp_001","failure_mode":"SIGNAL_NOISY","expression_spec":'
        + '{"bar_domain":"VOLUME","signal_form":"raw"}}\n'
        '{"expression_id":"exp_002","failure_mode":"SIGNAL_NOISY","expression_spec":'
        + '{"bar_domain":"VOLUME","signal_form":"z_score"}}\n'
    )
    seen = tg.load_seen(jsonl)
    assert len(seen) == 2
    assert seen[0]["expression_id"] == "exp_001"
    assert seen[0]["expression_spec"]["signal_form"] == "raw"
