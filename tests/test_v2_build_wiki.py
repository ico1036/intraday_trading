"""Phase 4-4 — top-level build_wiki.py integration.

Key invariants:
    - Deleting ``wiki/`` and rerunning build produces byte-identical output.
    - Stale pages from a prior build are removed before the new build.
    - ``.gitkeep`` at ``wiki/`` level is preserved.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.agent.v2.deterministic import build_wiki


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


def _seed_run(archive: Path, run_id: str, expressions, theses):
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


def _basic_thesis(thesis_id="th_000", fingerprint="sha256:aa"):
    return f"""---
thesis_id: {thesis_id}
fingerprint: {fingerprint}
status: ACTIVE
direction: reversal
features: [vpin]
trigger_schema:
  when: "x"
---

# Thesis
"""


def _verdict(status):
    return f"""---
verdict: {status}
---
# Verdict
"""


# ---------------------------------------------------------------------------
# Empty archive.
# ---------------------------------------------------------------------------


def test_build_empty_archive(tmp_path):
    archive = tmp_path / "archive"
    archive.mkdir()
    wiki = tmp_path / "wiki"
    report = build_wiki.build(archive, wiki)
    assert report.features_written == 0
    assert report.modes_written == 0
    # cross_run files always materialised
    assert (wiki / "cross_run" / "refuted_theses.md").is_file()
    assert (wiki / "cross_run" / "best_recipes.md").is_file()


# ---------------------------------------------------------------------------
# Populated archive.
# ---------------------------------------------------------------------------


def test_build_populated_archive_writes_expected_pages(tmp_path):
    archive = tmp_path / "archive"
    wiki = tmp_path / "wiki"
    _seed_run(
        archive,
        "v1",
        expressions=[
            _expression(expression_id="exp_001", features_used=["vpin"]),
            _expression(
                expression_id="exp_002",
                features_used=["vpin", "ofi"],
                failure_mode="APPROVED",
                verdict_after="APPROVED",
                result={"profit_factor": 1.6, "total_trades": 120, "win_rate": 0.58},
            ),
        ],
        theses={
            "th_000": {
                "thesis_md": _basic_thesis(),
                "verdict_md": _verdict("REFUTED"),
            }
        },
    )

    report = build_wiki.build(archive, wiki)
    assert (wiki / "facts" / "features" / "vpin.md").is_file()
    assert (wiki / "facts" / "features" / "ofi.md").is_file()
    assert (wiki / "facts" / "combinations" / "ofi_x_vpin.md").is_file()
    assert (wiki / "facts" / "failure_modes" / "SIGNAL_NOISY.md").is_file()
    assert (wiki / "cross_run" / "refuted_theses.md").is_file()
    assert (wiki / "cross_run" / "best_recipes.md").is_file()

    refuted = (wiki / "cross_run" / "refuted_theses.md").read_text()
    assert "sha256:aa" in refuted


# ---------------------------------------------------------------------------
# Idempotence.
# ---------------------------------------------------------------------------


def test_build_is_byte_identical_across_rebuilds(tmp_path):
    archive = tmp_path / "archive"
    wiki = tmp_path / "wiki"
    _seed_run(
        archive,
        "v1",
        expressions=[_expression(expression_id="exp_001")],
        theses={"th_000": {"thesis_md": _basic_thesis()}},
    )

    build_wiki.build(archive, wiki)
    snapshot1 = _snapshot(wiki)

    build_wiki.build(archive, wiki)
    snapshot2 = _snapshot(wiki)

    assert snapshot1 == snapshot2


def _snapshot(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = p.read_text()
    return out


# ---------------------------------------------------------------------------
# Stale cleanup.
# ---------------------------------------------------------------------------


def test_build_removes_stale_files_on_rebuild(tmp_path):
    archive = tmp_path / "archive"
    wiki = tmp_path / "wiki"

    # Pre-seed wiki with stale content that should be wiped
    (wiki / "facts" / "features").mkdir(parents=True)
    (wiki / "facts" / "features" / "stale_feature.md").write_text("# stale\n")
    (wiki / "cross_run").mkdir(parents=True)
    (wiki / "cross_run" / "stale.md").write_text("# stale\n")

    _seed_run(
        archive,
        "v1",
        expressions=[_expression(expression_id="exp_001")],
        theses={"th_000": {"thesis_md": _basic_thesis()}},
    )

    build_wiki.build(archive, wiki)
    assert not (wiki / "facts" / "features" / "stale_feature.md").exists()
    assert not (wiki / "cross_run" / "stale.md").exists()


# ---------------------------------------------------------------------------
# Preserve .gitkeep.
# ---------------------------------------------------------------------------


def test_build_preserves_gitkeep_at_wiki_root(tmp_path):
    archive = tmp_path / "archive"
    archive.mkdir()
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / ".gitkeep").write_text("")

    build_wiki.build(archive, wiki)
    assert (wiki / ".gitkeep").is_file()


# ---------------------------------------------------------------------------
# Cardinality bound (smoke — 15 features × C(15,2)=105 + 9 modes).
# ---------------------------------------------------------------------------


def test_build_bounded_cardinality(tmp_path):
    archive = tmp_path / "archive"
    wiki = tmp_path / "wiki"
    # Seed every feature touched → upper bound of feature + combination pages
    _seed_run(
        archive,
        "v1",
        expressions=[
            _expression(
                expression_id=f"exp_{i:03d}",
                features_used=["vpin", "ofi"],
                failure_mode="SIGNAL_NOISY",
            )
            for i in range(1, 4)
        ],
        theses={"th_000": {"thesis_md": _basic_thesis()}},
    )
    build_wiki.build(archive, wiki)

    feature_pages = list((wiki / "facts" / "features").glob("*.md"))
    combination_pages = list((wiki / "facts" / "combinations").glob("*.md"))
    mode_pages = list((wiki / "facts" / "failure_modes").glob("*.md"))

    # Only features / modes with actual evidence should be written
    assert len(feature_pages) == 2
    assert len(combination_pages) == 1
    assert len(mode_pages) == 1
