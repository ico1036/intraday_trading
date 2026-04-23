"""Phase 4-1 — wiki input loader contract.

Scans ``archive/*/`` and produces a :class:`WikiInput` bundle of every
expression and thesis, with verdict status and fingerprints attached.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.agent.v2.deterministic import wiki_loader as wl


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


def _write_run(
    archive: Path,
    run_id: str,
    expressions: list[dict],
    theses: dict[str, dict],
) -> Path:
    run_dir = archive / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "theses").mkdir(exist_ok=True)

    with (run_dir / "expression_log.jsonl").open("w") as f:
        for e in expressions:
            f.write(json.dumps(e) + "\n")

    for thesis_id, spec in theses.items():
        tdir = run_dir / "theses" / thesis_id
        tdir.mkdir(parents=True, exist_ok=True)
        (tdir / "thesis.md").write_text(spec["thesis_md"])
        if "verdict_md" in spec:
            (tdir / "verdict.md").write_text(spec["verdict_md"])

    return run_dir


def _expression(**overrides):
    base = dict(
        ts="2026-04-23T12:00:00+00:00",
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
        artifact_path="archive/v1/theses/th_000/expressions/exp_001/",
        result={"profit_factor": 1.0, "total_trades": 60, "win_rate": 0.5},
    )
    base.update(overrides)
    return base


def _thesis_md(thesis_id="th_000", fingerprint="sha256:aa", direction="reversal"):
    return f"""---
thesis_id: {thesis_id}
fingerprint: {fingerprint}
status: ACTIVE
direction: {direction}
features: [vpin]
trigger_schema:
  when: "x"
---

# Thesis body
"""


def _verdict_md(verdict="REFUTED"):
    return f"""---
verdict: {verdict}
next_action: new_thesis
---
# Verdict
"""


# ---------------------------------------------------------------------------
# Empty archive.
# ---------------------------------------------------------------------------


def test_load_empty_archive(tmp_path):
    result = wl.load(tmp_path)
    assert result.expressions == []
    assert result.theses == []


# ---------------------------------------------------------------------------
# Single run.
# ---------------------------------------------------------------------------


def test_load_single_run(tmp_path):
    _write_run(
        tmp_path,
        "v1",
        expressions=[_expression()],
        theses={"th_000": {"thesis_md": _thesis_md()}},
    )
    result = wl.load(tmp_path)
    assert len(result.expressions) == 1
    assert result.expressions[0]["expression_id"] == "exp_001"
    assert len(result.theses) == 1
    t = result.theses[0]
    assert t.thesis_id == "th_000"
    assert t.fingerprint == "sha256:aa"
    assert t.direction == "reversal"
    assert t.features == ["vpin"]
    assert t.verdict_status is None  # no verdict.md written


def test_load_picks_up_verdict_status(tmp_path):
    _write_run(
        tmp_path,
        "v1",
        expressions=[_expression()],
        theses={
            "th_000": {
                "thesis_md": _thesis_md(),
                "verdict_md": _verdict_md("REFUTED"),
            }
        },
    )
    result = wl.load(tmp_path)
    assert result.theses[0].verdict_status == "REFUTED"


# ---------------------------------------------------------------------------
# Multiple runs.
# ---------------------------------------------------------------------------


def test_load_multiple_runs(tmp_path):
    _write_run(
        tmp_path,
        "v1",
        expressions=[_expression(run_id="v1", thesis_id="th_000")],
        theses={"th_000": {"thesis_md": _thesis_md("th_000", "sha256:aa")}},
    )
    _write_run(
        tmp_path,
        "v2",
        expressions=[
            _expression(run_id="v2", thesis_id="th_000", expression_id="exp_001"),
            _expression(run_id="v2", thesis_id="th_000", expression_id="exp_002"),
        ],
        theses={
            "th_000": {
                "thesis_md": _thesis_md("th_000", "sha256:bb", "momentum"),
                "verdict_md": _verdict_md("REFUTED"),
            }
        },
    )
    result = wl.load(tmp_path)
    assert len(result.expressions) == 3
    assert len(result.theses) == 2
    fingerprints = {t.fingerprint for t in result.theses}
    assert fingerprints == {"sha256:aa", "sha256:bb"}


def test_load_handles_run_without_expression_log(tmp_path):
    """Scaffolded but not executed runs shouldn't crash the loader."""
    run_dir = tmp_path / "v1"
    run_dir.mkdir()
    (run_dir / "theses").mkdir()
    # Do NOT create expression_log.jsonl
    result = wl.load(tmp_path)
    assert result.expressions == []


def test_load_ignores_unrelated_dirs(tmp_path):
    (tmp_path / ".gitkeep").touch()
    (tmp_path / "README").write_text("not a run")
    # A dir without expression_log or theses is not a run.
    (tmp_path / "random_dir").mkdir()
    result = wl.load(tmp_path)
    assert result.expressions == []
    assert result.theses == []


# ---------------------------------------------------------------------------
# Convenience accessors.
# ---------------------------------------------------------------------------


def test_refuted_fingerprints_helper(tmp_path):
    _write_run(
        tmp_path,
        "v1",
        expressions=[_expression()],
        theses={
            "th_000": {
                "thesis_md": _thesis_md("th_000", "sha256:aa"),
                "verdict_md": _verdict_md("REFUTED"),
            },
            "th_001": {
                "thesis_md": _thesis_md("th_001", "sha256:bb"),
                "verdict_md": _verdict_md("APPROVED"),
            },
            "th_002": {
                "thesis_md": _thesis_md("th_002", "sha256:cc"),
                # no verdict.md — active
            },
        },
    )
    result = wl.load(tmp_path)
    refuted = wl.refuted_fingerprints(result)
    assert refuted == ["sha256:aa"]


def test_expressions_by_feature_groups_correctly(tmp_path):
    _write_run(
        tmp_path,
        "v1",
        expressions=[
            _expression(expression_id="exp_001", features_used=["vpin"]),
            _expression(expression_id="exp_002", features_used=["ofi"]),
            _expression(expression_id="exp_003", features_used=["vpin", "ofi"]),
        ],
        theses={"th_000": {"thesis_md": _thesis_md()}},
    )
    result = wl.load(tmp_path)
    by_feat = wl.expressions_by_feature(result)
    assert len(by_feat["vpin"]) == 2
    assert len(by_feat["ofi"]) == 2


def test_expressions_by_failure_mode_groups_correctly(tmp_path):
    _write_run(
        tmp_path,
        "v1",
        expressions=[
            _expression(expression_id="exp_001", failure_mode="SIGNAL_NOISY"),
            _expression(expression_id="exp_002", failure_mode="SIGNAL_NOISY"),
            _expression(expression_id="exp_003", failure_mode="APPROVED"),
        ],
        theses={"th_000": {"thesis_md": _thesis_md()}},
    )
    result = wl.load(tmp_path)
    by_mode = wl.expressions_by_failure_mode(result)
    assert len(by_mode["SIGNAL_NOISY"]) == 2
    assert len(by_mode["APPROVED"]) == 1
