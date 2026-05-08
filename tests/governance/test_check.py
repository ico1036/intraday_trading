from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.governance.check import (
    ALLOWED_GLOBS,
    HARD_DENY,
    _compute_turnover,
    _is_alpha_strategy_path,
    _match_any,
    check_quality,
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


# ----- quality gates -----------------------------------------------------


def _write_split(
    split_dir: Path,
    *,
    total_trades: int,
    initial_capital: float = 10000.0,
    notional_total: float = 200_000.0,
    n_trades: int = 4,
) -> None:
    import pandas as pd

    split_dir.mkdir(parents=True, exist_ok=True)
    (split_dir / "metrics.json").write_text(
        json.dumps({"sharpe": 1.0, "total_trades": total_trades})
    )
    eq = pd.DataFrame({"timestamp": [pd.Timestamp("2026-01-01")], "equity": [initial_capital]})
    eq.to_parquet(split_dir / "equity_curve.parquet")
    per = float(notional_total) / max(n_trades, 1)
    rows = []
    for i in range(n_trades):
        rows.append({"timestamp": pd.Timestamp("2026-01-01"), "symbol": "BTCUSDT",
                     "action": "OPEN_LONG", "price": per, "quantity": 1.0, "fee": 0.0, "pnl": 0.0})
    pd.DataFrame(rows).to_parquet(split_dir / "trades.parquet")


def _write_run_with_gates(run_dir: Path, gates: dict, universe=None) -> None:
    payload: dict = {"quality_gates": gates}
    if universe is not None:
        payload["universe"] = universe
    (run_dir / "splits.json").parent.mkdir(parents=True, exist_ok=True)
    (run_dir / "splits.json").write_text(json.dumps(payload))


def test_compute_turnover_basic(tmp_path: Path):
    _write_split(
        tmp_path / "is",
        total_trades=4,
        initial_capital=10000.0,
        notional_total=200_000.0,
        n_trades=4,
    )
    assert _compute_turnover(tmp_path / "is") == pytest.approx(20.0)


def test_quality_pass_when_above_thresholds(tmp_path: Path):
    run = tmp_path / "run_q1"
    _write_run_with_gates(run, {"min_trades": 100, "min_turnover": 10.0})
    _write_split(run / "alphas/a1/is", total_trades=500, notional_total=500_000.0)
    res = check_quality(archive_root=tmp_path)
    assert res.violations == []
    assert any("a1/is" in p for p in res.inspected)


def test_quality_fail_min_trades(tmp_path: Path):
    run = tmp_path / "run_q2"
    _write_run_with_gates(run, {"min_trades": 100, "min_turnover": 10.0})
    _write_split(run / "alphas/a1/is", total_trades=14, notional_total=500_000.0)
    res = check_quality(archive_root=tmp_path)
    gates = [v["gate"] for v in res.violations]
    assert "min_trades" in gates


def test_quality_fail_min_turnover(tmp_path: Path):
    run = tmp_path / "run_q3"
    _write_run_with_gates(run, {"min_trades": 100, "min_turnover": 10.0})
    # 9x turnover only: 90_000 notional with capital 10_000
    _write_split(run / "alphas/a1/is", total_trades=500, notional_total=90_000.0)
    res = check_quality(archive_root=tmp_path)
    gates = [v["gate"] for v in res.violations]
    assert "min_turnover" in gates


def test_quality_skipped_when_run_has_no_gates(tmp_path: Path):
    run = tmp_path / "run_q4"
    (run / "splits.json").parent.mkdir(parents=True, exist_ok=True)
    (run / "splits.json").write_text(json.dumps({"target": {"threshold": 1.0}}))
    _write_split(run / "alphas/a1/is", total_trades=1, notional_total=0.0)
    res = check_quality(archive_root=tmp_path)
    assert res.violations == []
    assert res.inspected == []


def test_quality_target_alpha_dir(tmp_path: Path):
    run = tmp_path / "run_q5"
    _write_run_with_gates(run, {"min_trades": 100})
    _write_split(run / "alphas/a1/is", total_trades=50, notional_total=200_000.0)
    res = check_quality(target_alpha_dir=run / "alphas/a1")
    assert any(v["gate"] == "min_trades" for v in res.violations)


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
