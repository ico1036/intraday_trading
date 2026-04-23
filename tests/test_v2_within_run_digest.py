"""Phase 2-5 — within_run_digest.py contract.

Produces ``research_map.md`` from ``expression_log.jsonl``. This is the ONLY
summary agents are allowed to read about run history — the raw log is
off-limits. Output must be deterministic given the same input.
"""
from __future__ import annotations

import json

import pytest

from scripts.agent.v2.deterministic import within_run_digest as wrd


# ---------------------------------------------------------------------------
# Fixtures.
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


def _entry(thesis_id, expression_id, failure_mode, *, verdict_after="ACTIVE", **spec_overrides):
    return {
        "thesis_id": thesis_id,
        "expression_id": expression_id,
        "failure_mode": failure_mode,
        "verdict_after": verdict_after,
        "expression_spec": _spec(**spec_overrides),
        "features_used": ["vpin"],
    }


# ---------------------------------------------------------------------------
# Base — empty / minimal.
# ---------------------------------------------------------------------------


def test_digest_empty_log():
    md = wrd.build([], run_id="r1")
    assert "# Research Map: r1" in md
    assert "no expressions" in md.lower()


def test_digest_single_expression():
    log = [_entry("th_001", "exp_001", "SIGNAL_NOISY")]
    md = wrd.build(log, run_id="r1")
    assert "th_001" in md
    assert "exp_001" in md
    assert "SIGNAL_NOISY" in md


# ---------------------------------------------------------------------------
# Per-thesis section.
# ---------------------------------------------------------------------------


def test_digest_has_per_thesis_section_with_mode_distribution():
    log = [
        _entry("th_001", "exp_001", "SIGNAL_NOISY"),
        _entry("th_001", "exp_002", "SIGNAL_NOISY", signal_form="z_score"),
        _entry("th_001", "exp_003", "SIGNAL_SPARSE", signal_form="rolling_rank"),
    ]
    md = wrd.build(log, run_id="r1")
    # Thesis header exists
    assert "## Thesis th_001" in md
    # Mode distribution rendered
    assert "SIGNAL_NOISY" in md
    assert "SIGNAL_SPARSE" in md
    # Count: 2 NOISY + 1 SPARSE
    assert "2" in md
    assert "1" in md


def test_digest_lists_multiple_theses():
    log = [
        _entry("th_001", "exp_001", "SIGNAL_NOISY"),
        _entry("th_002", "exp_002", "THESIS_INVERTED"),
    ]
    md = wrd.build(log, run_id="r1")
    assert "## Thesis th_001" in md
    assert "## Thesis th_002" in md


# ---------------------------------------------------------------------------
# Axes tried / untried.
# ---------------------------------------------------------------------------


def test_digest_shows_axes_varied_for_thesis():
    log = [
        _entry("th_001", "exp_001", "SIGNAL_NOISY"),
        _entry("th_001", "exp_002", "SIGNAL_NOISY", signal_form="z_score"),
        _entry("th_001", "exp_003", "SIGNAL_NOISY", regime_filter="vol_regime"),
    ]
    md = wrd.build(log, run_id="r1")
    # Axes with multiple distinct values must be noted as explored
    assert "signal_form" in md
    assert "regime_filter" in md


# ---------------------------------------------------------------------------
# Stagnation warning.
# ---------------------------------------------------------------------------


def test_digest_warns_on_stagnation():
    """If the last 3 expressions for a thesis touch < 2 distinct axes, warn."""
    log = [
        _entry("th_001", "exp_001", "SIGNAL_NOISY"),
        _entry("th_001", "exp_002", "SIGNAL_NOISY"),  # identical
        _entry("th_001", "exp_003", "SIGNAL_NOISY"),  # identical
    ]
    md = wrd.build(log, run_id="r1")
    assert "stagnat" in md.lower() or "STAGNATION" in md


def test_digest_does_not_warn_when_exploring():
    log = [
        _entry("th_001", "exp_001", "SIGNAL_NOISY"),
        _entry("th_001", "exp_002", "SIGNAL_NOISY", signal_form="z_score"),
        _entry(
            "th_001",
            "exp_003",
            "SIGNAL_NOISY",
            threshold_type="adaptive_quantile",
            regime_filter="vol_regime",
        ),
    ]
    md = wrd.build(log, run_id="r1")
    assert "stagnat" not in md.lower()


# ---------------------------------------------------------------------------
# APPROVED highlight.
# ---------------------------------------------------------------------------


def test_digest_flags_approved_expression():
    log = [
        _entry("th_001", "exp_001", "SIGNAL_NOISY"),
        _entry("th_001", "exp_002", "APPROVED", verdict_after="APPROVED"),
    ]
    md = wrd.build(log, run_id="r1")
    assert "APPROVED" in md


# ---------------------------------------------------------------------------
# Determinism — same input → byte-identical output.
# ---------------------------------------------------------------------------


def test_digest_is_deterministic():
    log = [
        _entry("th_001", "exp_001", "SIGNAL_NOISY"),
        _entry("th_002", "exp_002", "SIGNAL_SPARSE"),
        _entry("th_001", "exp_003", "SIGNAL_NOISY", signal_form="z_score"),
    ]
    a = wrd.build(log, run_id="r1")
    b = wrd.build(log, run_id="r1")
    assert a == b


# ---------------------------------------------------------------------------
# I/O — regenerate from JSONL file.
# ---------------------------------------------------------------------------


def test_build_from_jsonl_file(tmp_path):
    log_path = tmp_path / "expression_log.jsonl"
    log_path.write_text(
        "\n".join(
            json.dumps(_entry("th_001", f"exp_{i:03d}", "SIGNAL_NOISY"))
            for i in range(1, 4)
        )
        + "\n"
    )
    md = wrd.build_from_file(log_path, run_id="r1")
    assert "exp_001" in md
    assert "exp_003" in md


def test_build_writes_to_research_map(tmp_path):
    log_path = tmp_path / "expression_log.jsonl"
    log_path.write_text(
        json.dumps(_entry("th_001", "exp_001", "SIGNAL_NOISY")) + "\n"
    )
    out_path = tmp_path / "research_map.md"
    wrd.write_from_file(log_path, out_path, run_id="r1")
    assert out_path.read_text().startswith("# Research Map: r1")
