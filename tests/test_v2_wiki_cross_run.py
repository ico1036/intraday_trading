"""Phase 4-3 — cross-run wiki builders.

Covers ``cross_run/refuted_theses.md`` and ``cross_run/best_recipes.md``.
"""
from __future__ import annotations

from scripts.agent.v2.deterministic import wiki_loader as wl
from scripts.agent.v2.deterministic import wiki_cross_run as wx


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
        failure_mode="APPROVED",
        verdict_after="APPROVED",
        result={"profit_factor": 1.5, "total_trades": 120, "win_rate": 0.55},
    )
    base.update(overrides)
    return base


def _thesis(**overrides):
    base = dict(
        run_id="v1",
        thesis_id="th_000",
        fingerprint="sha256:aa",
        direction="reversal",
        features=["vpin"],
        verdict_status=None,
    )
    base.update(overrides)
    return wl.ThesisRecord(**base)


def _input(expressions, theses):
    return wl.WikiInput(expressions=list(expressions), theses=list(theses))


# ---------------------------------------------------------------------------
# refuted_theses.md
# ---------------------------------------------------------------------------


def test_refuted_theses_empty():
    page = wx.render_refuted_theses(_input([], []))
    assert "total: 0" in page
    assert "# Refuted theses" in page


def test_refuted_theses_lists_each_refuted_thesis():
    theses = [
        _thesis(thesis_id="th_000", fingerprint="sha256:aa", verdict_status="REFUTED"),
        _thesis(
            run_id="v2",
            thesis_id="th_001",
            fingerprint="sha256:bb",
            direction="momentum",
            features=["ofi"],
            verdict_status="REFUTED",
        ),
        _thesis(
            run_id="v2",
            thesis_id="th_002",
            fingerprint="sha256:cc",
            verdict_status="APPROVED",  # not refuted — exclude
        ),
    ]
    page = wx.render_refuted_theses(_input([], theses))
    assert "total: 2" in page
    assert "sha256:aa" in page
    assert "sha256:bb" in page
    assert "sha256:cc" not in page


def test_refuted_theses_deterministic():
    theses = [
        _thesis(thesis_id="th_000", fingerprint="sha256:bb", verdict_status="REFUTED"),
        _thesis(run_id="v2", thesis_id="th_001", fingerprint="sha256:aa", verdict_status="REFUTED"),
    ]
    a = wx.render_refuted_theses(_input([], theses))
    b = wx.render_refuted_theses(_input([], list(reversed(theses))))
    assert a == b


def test_refuted_theses_skips_missing_fingerprint():
    theses = [_thesis(fingerprint=None, verdict_status="REFUTED")]
    page = wx.render_refuted_theses(_input([], theses))
    assert "total: 0" in page


# ---------------------------------------------------------------------------
# best_recipes.md
# ---------------------------------------------------------------------------


def test_best_recipes_empty_when_no_approved():
    exprs = [_expression(failure_mode="SIGNAL_NOISY")]
    page = wx.render_best_recipes(_input(exprs, []))
    assert "total_approved: 0" in page
    assert "# Best recipes" in page


def test_best_recipes_groups_by_run():
    exprs = [
        _expression(run_id="v1", thesis_id="th_000", expression_id="exp_001",
                    result={"profit_factor": 1.5, "total_trades": 120, "win_rate": 0.55}),
        _expression(run_id="v1", thesis_id="th_001", expression_id="exp_001",
                    result={"profit_factor": 1.8, "total_trades": 90, "win_rate": 0.62}),
        _expression(run_id="v2", thesis_id="th_000", expression_id="exp_002",
                    features_used=["ofi"],
                    result={"profit_factor": 1.4, "total_trades": 200, "win_rate": 0.52}),
    ]
    page = wx.render_best_recipes(_input(exprs, []))
    assert "total_approved: 3" in page
    assert "runs_covered: 2" in page
    assert "## Run v1" in page
    assert "## Run v2" in page
    # PF 1.8 should surface as a top entry for v1
    assert "1.8" in page


def test_best_recipes_top_n_per_run():
    exprs = [
        _expression(
            run_id="v1",
            thesis_id=f"th_{i:03d}",
            expression_id=f"exp_{i:03d}",
            result={"profit_factor": 1.0 + i * 0.1, "total_trades": 100, "win_rate": 0.5},
        )
        for i in range(5)
    ]
    page = wx.render_best_recipes(_input(exprs, []), top_n=2)
    # Only top 2 per run should appear
    # Top 2 PF: 1.4 and 1.3 → th_004 and th_003
    assert "th_004" in page
    assert "th_003" in page
    assert "th_000" not in page


def test_best_recipes_deterministic():
    exprs = [
        _expression(run_id="v1", thesis_id="th_000", expression_id="exp_001"),
        _expression(run_id="v1", thesis_id="th_001", expression_id="exp_001"),
    ]
    a = wx.render_best_recipes(_input(exprs, []))
    b = wx.render_best_recipes(_input(list(reversed(exprs)), []))
    assert a == b
