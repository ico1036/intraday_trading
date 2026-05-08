from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.governance.check import (
    ALLOWED_GLOBS,
    HARD_DENY,
    _is_alpha_strategy_path,
    _match_any,
    check_universe,
)


# ----- editable surface unit checks --------------------------------------


def test_alpha_strategy_path_accepted():
    assert _is_alpha_strategy_path("src/intraday/strategies/multi/my_alpha.py")


def test_alpha_template_rejected():
    assert not _is_alpha_strategy_path("src/intraday/strategies/multi/_alpha_template.py")


def test_strategy_init_rejected():
    assert not _is_alpha_strategy_path("src/intraday/strategies/multi/__init__.py")


def test_non_python_in_strategies_rejected():
    assert not _is_alpha_strategy_path("src/intraday/strategies/multi/notes.md")


def test_match_any_archive_glob():
    assert _match_any("archive/run/alphas/a/is/manifest.json", ALLOWED_GLOBS)


def test_match_any_test_glob():
    assert _match_any("tests/strategies/test_my_alpha.py", ALLOWED_GLOBS)


def test_framework_path_not_in_allowed():
    assert not _match_any("src/intraday/backtest/multi_tick_runner.py", ALLOWED_GLOBS)


def test_data_path_not_in_allowed():
    assert not _match_any("data/futures_klines/BTCUSDT/2026/x.parquet", ALLOWED_GLOBS)


def test_pyproject_not_in_allowed():
    assert not _match_any("pyproject.toml", ALLOWED_GLOBS)


def test_hard_deny_constants_listed():
    assert "src/intraday/strategies/multi/_alpha_template.py" in HARD_DENY


# ----- universe consistency integration ---------------------------------


def _write_manifest(path: Path, symbols: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "artifact_version": 1,
                "alpha_id": path.parent.parent.name,
                "strategy_name": "Test",
                "symbols": symbols,
            }
        )
    )


def _write_splits(path: Path, universe: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"universe": universe}))


def test_universe_match(tmp_path: Path):
    run = tmp_path / "run_a"
    _write_splits(run / "splits.json", ["BTCUSDT", "ETHUSDT"])
    _write_manifest(run / "alphas/alpha_1/is/manifest.json", ["BTCUSDT", "ETHUSDT"])
    res = check_universe(archive_root=tmp_path)
    assert res.violations == []
    assert any("alpha_1/is/manifest.json" in p for p in res.inspected)


def test_universe_mismatch_flagged(tmp_path: Path):
    run = tmp_path / "run_b"
    _write_splits(run / "splits.json", ["BTCUSDT", "ETHUSDT"])
    _write_manifest(run / "alphas/alpha_1/is/manifest.json", ["BTCUSDT"])
    res = check_universe(archive_root=tmp_path)
    assert len(res.violations) == 1
    v = res.violations[0]
    assert v["reason"] == "symbols != run universe"
    assert v["manifest_symbols"] == ["BTCUSDT"]
    assert v["run_universe"] == ["BTCUSDT", "ETHUSDT"]


def test_universe_missing_universe_skipped(tmp_path: Path):
    run = tmp_path / "run_c"
    (run / "splits.json").parent.mkdir(parents=True, exist_ok=True)
    (run / "splits.json").write_text(json.dumps({"warmup": {}, "is": {}, "os": {}}))
    _write_manifest(run / "alphas/alpha_1/is/manifest.json", ["BTCUSDT"])
    res = check_universe(archive_root=tmp_path)
    assert res.violations == []  # no declared universe → skip


def test_universe_case_insensitive(tmp_path: Path):
    run = tmp_path / "run_d"
    _write_splits(run / "splits.json", ["btcusdt", "ETHUSDT"])
    _write_manifest(run / "alphas/alpha_1/os/manifest.json", ["BTCUSDT", "ethusdt"])
    res = check_universe(archive_root=tmp_path)
    assert res.violations == []


def test_universe_invalid_manifest_flagged(tmp_path: Path):
    run = tmp_path / "run_e"
    _write_splits(run / "splits.json", ["BTCUSDT"])
    bad = run / "alphas/alpha_1/is/manifest.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("{not json")
    res = check_universe(archive_root=tmp_path)
    assert len(res.violations) == 1
    assert res.violations[0]["reason"] == "invalid manifest.json"


# ----- end-to-end CLI ----------------------------------------------------


def test_cli_runs_and_emits_json():
    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "scripts/governance/check.py",
            "--only",
            "universe",
            "--json",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode in (0, 1), result.stderr
    payload = json.loads(result.stdout)
    assert "checks" in payload
    assert "universe" in payload["checks"]
