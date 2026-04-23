"""Phase 0 tests — v2 scaffold + config YAML invariants.

Client-first TDD: these tests express the contract that scaffold_run and the
config YAMLs satisfy, seen from the caller's perspective.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts.agent.v2 import scaffold


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"


# ---------------------------------------------------------------------------
# YAML invariants — these guard the "bounded cardinality" promise.
# ---------------------------------------------------------------------------


def test_failure_modes_yaml_has_expected_enum():
    data = yaml.safe_load((CONFIG_DIR / "failure_modes.yaml").read_text())
    assert data["version"] == 1
    expected = {
        "SIGNAL_SPARSE",
        "SIGNAL_NOISY",
        "LATE_ENTRY",
        "EDGE_DECAY",
        "REGIME_DEPENDENT",
        "FEE_DOMINATED",
        "OVERFIT_SYMBOL",
        "THESIS_INVERTED",
        "OTHER",
    }
    assert set(data["modes"].keys()) == expected
    for key, spec in data["modes"].items():
        assert "description" in spec, f"{key} missing description"
        assert "implication" in spec, f"{key} missing implication"


def test_feature_vocab_is_bounded():
    data = yaml.safe_load((CONFIG_DIR / "feature_vocab.yaml").read_text())
    assert data["version"] == 1
    features = data["features"]
    assert 1 <= len(features) <= 15, (
        "feature vocab must stay ≤ 15 to keep wiki cardinality bounded"
    )
    for name, spec in features.items():
        assert name.islower(), f"feature {name!r} must be lowercase snake_case"
        assert "description" in spec
        assert "source" in spec


def test_expression_axes_enum_shape():
    data = yaml.safe_load((CONFIG_DIR / "expression_axes.yaml").read_text())
    assert data["version"] == 1
    axes = data["axes"]
    assert len(axes) >= 6, "need enough axes to meaningfully differ expressions"
    for axis_name, spec in axes.items():
        assert "values" in spec, f"axis {axis_name!r} missing values"
        assert isinstance(spec["values"], list)
        assert len(spec["values"]) >= 2, (
            f"axis {axis_name!r} needs ≥2 values to be a real choice"
        )


def test_targets_yaml_has_required_sections():
    data = yaml.safe_load((CONFIG_DIR / "targets.yaml").read_text())
    assert data["version"] == 1
    d = data["defaults"]
    for section in ("primary", "secondary", "auto_reject", "budget"):
        assert section in d, f"targets.yaml missing {section!r}"
    assert d["budget"]["max_expressions_per_thesis"] > 0
    assert d["budget"]["max_theses_per_run"] > 0


# ---------------------------------------------------------------------------
# scaffold_run — contract from the caller's POV.
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_archive(monkeypatch, tmp_path):
    """Redirect ARCHIVE_ROOT to a temp dir so tests never touch real runs."""
    monkeypatch.setattr(scaffold, "ARCHIVE_ROOT", tmp_path)
    return tmp_path


def test_scaffold_creates_expected_skeleton(tmp_archive):
    result = scaffold.scaffold_run("my_run")

    assert result.run_id == "my_run"
    assert result.created is True
    assert (tmp_archive / "my_run").is_dir()
    assert (tmp_archive / "my_run" / "theses").is_dir()
    assert (tmp_archive / "my_run" / "expression_log.jsonl").is_file()
    assert (tmp_archive / "my_run" / "research_map.md").is_file()
    assert result.plan_path.is_file()


def test_scaffold_plan_template_is_rendered_with_run_id(tmp_archive):
    result = scaffold.scaffold_run("v1_accrual_probe")
    plan = result.plan_path.read_text()
    assert "v1_accrual_probe" in plan
    assert "## Targets" in plan
    assert "## Strategy request" in plan


def test_scaffold_resume_preserves_existing_plan(tmp_archive):
    first = scaffold.scaffold_run("my_run")
    first.plan_path.write_text("# user-edited plan\n")

    second = scaffold.scaffold_run("my_run")

    assert second.path == first.path
    assert second.plan_path.read_text() == "# user-edited plan\n"


def test_scaffold_force_overwrites_plan(tmp_archive):
    scaffold.scaffold_run("my_run").plan_path.write_text("# mine\n")

    second = scaffold.scaffold_run("my_run", force=True)

    assert second.plan_path.read_text() != "# mine\n"
    assert "my_run" in second.plan_path.read_text()


def test_scaffold_refuses_resume_when_done(tmp_archive):
    scaffold.scaffold_run("my_run")
    (tmp_archive / "my_run" / "DONE").touch()

    with pytest.raises(scaffold.RunScaffoldError):
        scaffold.scaffold_run("my_run")


def test_scaffold_force_clears_done(tmp_archive):
    scaffold.scaffold_run("my_run")
    (tmp_archive / "my_run" / "DONE").touch()

    result = scaffold.scaffold_run("my_run", force=True)

    assert not (result.path / "DONE").exists()


@pytest.mark.parametrize(
    "bad_id",
    ["", " ", "-leading", "has space", "has/slash", "a" * 65, "weird$char"],
)
def test_scaffold_rejects_invalid_run_ids(tmp_archive, bad_id):
    with pytest.raises(scaffold.RunScaffoldError):
        scaffold.scaffold_run(bad_id)


@pytest.mark.parametrize(
    "good_id",
    ["a", "v1", "v1_vpin_reversal", "run-01", "A1_b2_c3"],
)
def test_scaffold_accepts_valid_run_ids(tmp_archive, good_id):
    scaffold.scaffold_run(good_id)  # no raise


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def test_is_done_reflects_sentinel(tmp_archive):
    scaffold.scaffold_run("my_run")
    assert scaffold.is_done("my_run") is False
    (tmp_archive / "my_run" / "DONE").touch()
    assert scaffold.is_done("my_run") is True


def test_run_path_is_relative_to_archive_root(tmp_archive):
    assert scaffold.run_path("foo") == tmp_archive / "foo"
