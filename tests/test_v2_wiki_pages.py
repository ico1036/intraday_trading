"""Phase 4-2 — feature / failure_mode / combination page builders."""
from __future__ import annotations

from scripts.agent.v2.deterministic import wiki_loader as wl
from scripts.agent.v2.deterministic import wiki_pages as wp


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _expression(**overrides):
    base = dict(
        run_id="v1",
        thesis_id="th_000",
        expression_id="exp_001",
        expression_spec={
            "bar_domain": "VOLUME",
            "bar_granularity": "medium",
            "signal_form": "raw",
            "threshold_type": "absolute",
            "aggregation": "instantaneous",
            "regime_filter": "none",
            "exit_rule": "time_stop",
            "sizing": "fixed",
            "universe": "single_symbol",
        },
        features_used=["vpin"],
        failure_mode="SIGNAL_NOISY",
        verdict_after="ACTIVE",
        result={"profit_factor": 1.0, "total_trades": 60, "win_rate": 0.5},
    )
    base.update(overrides)
    return base


def _input(expressions, theses=()):
    return wl.WikiInput(expressions=list(expressions), theses=list(theses))


# ---------------------------------------------------------------------------
# Feature pages.
# ---------------------------------------------------------------------------


def test_feature_page_one_expression_low_confidence():
    page = wp.render_feature_page(
        feature="vpin",
        wi=_input([_expression()]),
    )
    assert "feature: vpin" in page
    assert "evidence_count: 1" in page
    assert "confidence: low" in page
    assert "# vpin" in page


def test_feature_page_confidence_scales_with_evidence():
    exprs = [
        _expression(expression_id=f"exp_{i:03d}")
        for i in range(1, 6)  # 5 expressions → high
    ]
    page = wp.render_feature_page(feature="vpin", wi=_input(exprs))
    assert "evidence_count: 5" in page
    assert "confidence: high" in page


def test_feature_page_medium_confidence_at_two():
    exprs = [_expression(expression_id="exp_001"), _expression(expression_id="exp_002")]
    page = wp.render_feature_page(feature="vpin", wi=_input(exprs))
    assert "confidence: medium" in page


def test_feature_page_includes_approved_count():
    exprs = [
        _expression(expression_id="exp_001", failure_mode="SIGNAL_NOISY"),
        _expression(
            expression_id="exp_002",
            failure_mode="APPROVED",
            result={"profit_factor": 1.9, "total_trades": 120, "win_rate": 0.6},
        ),
    ]
    page = wp.render_feature_page(feature="vpin", wi=_input(exprs))
    assert "approved_count: 1" in page
    # Best observed points at the APPROVED expression
    assert "exp_002" in page


def test_feature_page_skipped_if_no_evidence():
    page = wp.render_feature_page(feature="vpin", wi=_input([]))
    assert page == ""


def test_feature_page_evidence_table_shape():
    page = wp.render_feature_page(
        feature="vpin",
        wi=_input([_expression()]),
    )
    assert "## Evidence" in page
    # Table header
    assert "| Run/Thesis/Exp" in page


# ---------------------------------------------------------------------------
# Failure mode pages.
# ---------------------------------------------------------------------------


def test_failure_mode_page_counts_and_implication():
    exprs = [
        _expression(expression_id="exp_001", failure_mode="SIGNAL_NOISY", features_used=["vpin"]),
        _expression(expression_id="exp_002", failure_mode="SIGNAL_NOISY", features_used=["ofi"]),
        _expression(expression_id="exp_003", failure_mode="SIGNAL_NOISY", features_used=["vpin"],
                    thesis_id="th_001"),
    ]
    page = wp.render_failure_mode_page(mode="SIGNAL_NOISY", wi=_input(exprs))
    assert "mode: SIGNAL_NOISY" in page
    assert "evidence_count: 3" in page
    assert "implication: thesis" in page
    assert "theses_affected: 2" in page
    # Common features should surface
    assert "vpin" in page


def test_failure_mode_page_excludes_approved_tag():
    exprs = [_expression(failure_mode="APPROVED")]
    page = wp.render_failure_mode_page(mode="APPROVED", wi=_input(exprs))
    # APPROVED is not a failure mode — the builder should return empty
    assert page == ""


def test_failure_mode_page_skipped_when_no_evidence():
    page = wp.render_failure_mode_page(mode="SIGNAL_NOISY", wi=_input([]))
    assert page == ""


# ---------------------------------------------------------------------------
# Combination pages (pairs).
# ---------------------------------------------------------------------------


def test_combination_page_pair_evidence():
    exprs = [
        _expression(expression_id="exp_001", features_used=["vpin", "ofi"]),
        _expression(expression_id="exp_002", features_used=["vpin", "ofi"]),
    ]
    page = wp.render_combination_page(
        features=("vpin", "ofi"),
        wi=_input(exprs),
    )
    assert "pair:" in page
    assert "vpin" in page and "ofi" in page
    assert "evidence_count: 2" in page


def test_combination_page_requires_both_features():
    exprs = [
        _expression(expression_id="exp_001", features_used=["vpin"]),
        _expression(expression_id="exp_002", features_used=["ofi"]),
    ]
    page = wp.render_combination_page(
        features=("vpin", "ofi"),
        wi=_input(exprs),
    )
    # Neither expression uses BOTH → no pair evidence
    assert page == ""


def test_combination_page_normalises_pair_order():
    exprs = [_expression(features_used=["vpin", "ofi"])]
    page_ab = wp.render_combination_page(features=("vpin", "ofi"), wi=_input(exprs))
    page_ba = wp.render_combination_page(features=("ofi", "vpin"), wi=_input(exprs))
    assert page_ab == page_ba


# ---------------------------------------------------------------------------
# Determinism — same input → byte-identical output.
# ---------------------------------------------------------------------------


def test_feature_page_is_deterministic():
    # Randomise-ish input by scrambling iteration order shouldn't change bytes.
    exprs = [
        _expression(expression_id="exp_003"),
        _expression(expression_id="exp_001"),
        _expression(expression_id="exp_002"),
    ]
    a = wp.render_feature_page(feature="vpin", wi=_input(exprs))
    b = wp.render_feature_page(feature="vpin", wi=_input(list(reversed(exprs))))
    assert a == b


def test_failure_mode_page_is_deterministic():
    exprs = [
        _expression(expression_id="exp_001", failure_mode="SIGNAL_NOISY"),
        _expression(expression_id="exp_002", failure_mode="SIGNAL_NOISY"),
    ]
    a = wp.render_failure_mode_page(mode="SIGNAL_NOISY", wi=_input(exprs))
    b = wp.render_failure_mode_page(
        mode="SIGNAL_NOISY", wi=_input(list(reversed(exprs)))
    )
    assert a == b
