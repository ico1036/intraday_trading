from __future__ import annotations

import json
import subprocess
from pathlib import Path


def _write_artifact_metrics(path: Path, metrics: dict) -> None:
    path.mkdir(parents=True)
    (path / "metrics.json").write_text(json.dumps(metrics))
    (path / "manifest.json").write_text(
        json.dumps({"alpha_id": "UnitAlpha", "strategy_name": "UnitAlpha"})
    )


def test_validate_is_os_writes_warning_label(tmp_path):
    alpha_dir = tmp_path / "alphas" / "UnitAlpha"
    _write_artifact_metrics(
        alpha_dir / "is",
        {
            "profit_factor": 2.0,
            "total_return": 0.10,
            "max_drawdown": -0.02,
            "total_trades": 100,
            "win_rate": 0.60,
            "sharpe": 1.50,
        },
    )
    _write_artifact_metrics(
        alpha_dir / "os",
        {
            "profit_factor": 0.7,
            "total_return": 0.01,
            "max_drawdown": -0.06,
            "total_trades": 3,
            "win_rate": 0.35,
            "sharpe": -0.20,
        },
    )

    proc = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "scripts/tools/validate_is_os.py",
            "--alpha-dir",
            str(alpha_dir),
            "--json",
        ],
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    result = json.loads(proc.stdout)
    assert result["status"] == "WARNING"
    assert result["alpha_id"] == "UnitAlpha"
    assert "RETURN_COLLAPSE" in result["flags"]
    assert "SHARPE_SIGN_FLIP" in result["flags"]
    assert "OS_TRADE_COUNT_TOO_LOW" in result["flags"]
    saved = json.loads((alpha_dir / "validation.json").read_text())
    assert saved["flags"] == result["flags"]


def test_validate_is_os_passes_without_warnings(tmp_path):
    alpha_dir = tmp_path / "alphas" / "StableAlpha"
    metrics = {
        "profit_factor": 1.2,
        "total_return": 0.04,
        "max_drawdown": -0.03,
        "total_trades": 50,
        "win_rate": 0.52,
        "sharpe": 0.80,
    }
    _write_artifact_metrics(alpha_dir / "is", metrics)
    _write_artifact_metrics(alpha_dir / "os", metrics | {"total_return": 0.035, "sharpe": 0.75})

    proc = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "scripts/tools/validate_is_os.py",
            "--alpha-dir",
            str(alpha_dir),
            "--json",
        ],
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    result = json.loads(proc.stdout)
    assert result["status"] == "PASS"
    assert result["flags"] == []


def test_validate_is_os_errors_on_missing_metrics(tmp_path):
    proc = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "scripts/tools/validate_is_os.py",
            "--alpha-dir",
            str(tmp_path / "missing"),
            "--json",
        ],
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert proc.returncode == 2
    result = json.loads(proc.stdout)
    assert result["status"] == "ERROR"
    assert "missing file" in result["error"]
