from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd


def _write_ticks(root: Path, symbol: str, start_price: float) -> None:
    base = datetime(2025, 3, 1)
    path = root / symbol
    path.mkdir(parents=True)
    rows = []
    for i in range(180):
        rows.append(
            {
                "timestamp": base + timedelta(seconds=i),
                "symbol": symbol,
                "price": start_price * (1 + 0.0001 * i),
                "quantity": 10.0,
                "is_buyer_maker": bool(i % 2),
            }
        )
    pd.DataFrame(rows).to_parquet(path / "ticks.parquet", index=False)


def _write_bars(root: Path, symbol: str, start_price: float) -> None:
    base = datetime(2025, 3, 1)
    path = root / symbol / "2025"
    path.mkdir(parents=True)
    rows = []
    for i in range(10):
        price = start_price * (1 + 0.001 * i)
        rows.append(
            {
                "timestamp": base + timedelta(minutes=i),
                "symbol": symbol,
                "open": price,
                "high": price * 1.001,
                "low": price * 0.999,
                "close": price * 1.0005,
                "volume": 100.0,
                "quote_volume": price * 100.0,
                "trade_count": 10,
                "taker_buy_volume": 60.0,
                "taker_buy_quote_volume": price * 60.0,
            }
        )
    pd.DataFrame(rows).to_parquet(path / f"{symbol}-1m.parquet", index=False)


def _last_json(stdout: str) -> dict:
    start = stdout.find("{")
    assert start >= 0, stdout
    return json.loads(stdout[start:])


def test_backtest_cli_writes_artifacts_and_json(tmp_path):
    data_root = tmp_path / "data"
    _write_ticks(data_root, "BTCUSDT", 50000.0)
    _write_ticks(data_root, "ETHUSDT", 3000.0)
    out = tmp_path / "artifact"

    proc = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "scripts/tools/backtest.py",
            "--data-type",
            "ticks",
            "--strategy",
            "AlphaTemplateStrategy",
            "--symbols",
            "BTCUSDT",
            "ETHUSDT",
            "--data-path",
            str(data_root),
            "--start",
            "2025-03-01 00:00:00",
            "--end",
            "2025-03-01 00:03:00",
            "--bar-type",
            "TIME",
            "--bar-size",
            "60",
            "--strategy-params",
            json.dumps(
                {
                    "lookback_bars": 1,
                    "rebalance_bars": 1,
                    "entry_threshold": 0.00001,
                    "exit_threshold": 0.0,
                    "max_weight": 0.4,
                }
            ),
            "--output-dir",
            str(out),
            "--no-enforce-governance",
            "--json",
        ],
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    result = _last_json(proc.stdout)
    assert result["ok"] is True
    assert result["artifact_dir"] == str(out)
    assert result["verification"]["ok"] is True
    assert result["verification"]["weights_rows"] > 0
    assert (out / "weights.parquet").exists()
    assert (out / "metrics.json").exists()


def test_backtest_cli_accepts_bar_data(tmp_path):
    data_root = tmp_path / "bars"
    _write_bars(data_root, "BTCUSDT", 50000.0)
    _write_bars(data_root, "ETHUSDT", 3000.0)
    out = tmp_path / "bar_artifact"

    proc = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "scripts/tools/backtest.py",
            "--data-type",
            "bars",
            "--strategy",
            "AlphaTemplateStrategy",
            "--symbols",
            "BTCUSDT",
            "ETHUSDT",
            "--data-path",
            str(data_root),
            "--start",
            "2025-03-01 00:00:00",
            "--end",
            "2025-03-01 00:09:00",
            "--bar-type",
            "TIME",
            "--bar-size",
            "60",
            "--strategy-params",
            json.dumps(
                {
                    "lookback_bars": 1,
                    "rebalance_bars": 1,
                    "entry_threshold": 0.00001,
                    "exit_threshold": 0.0,
                    "max_weight": 0.4,
                }
            ),
            "--output-dir",
            str(out),
            "--no-enforce-governance",
            "--json",
        ],
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    result = _last_json(proc.stdout)
    assert result["ok"] is True
    assert result["summary"]["data_type"] == "bars"
    assert result["verification"]["ok"] is True
    assert (out / "weights.parquet").exists()


def _run_backtest_cli(*, run_root: Path, data_root: Path, output_dir: Path,
                       enforce: bool = True, strategy_params: dict | None = None) -> subprocess.CompletedProcess:
    sp = strategy_params or {
        "lookback_bars": 1,
        "rebalance_bars": 1,
        "entry_threshold": 0.00001,
        "exit_threshold": 0.0,
        "max_weight": 0.4,
    }
    # AlphaTemplateStrategy carries the template-placeholder ALPHA_CELL,
    # which the pre-flight guard rejects. Tests in this file exercise quality
    # / verify paths and bypass governance enforcement explicitly.
    cmd = [
        "uv", "run", "python", "scripts/tools/backtest.py",
        "--data-type", "bars",
        "--strategy", "AlphaTemplateStrategy",
        "--symbols", "BTCUSDT", "ETHUSDT",
        "--data-path", str(data_root),
        "--start", "2025-03-01 00:00:00",
        "--end", "2025-03-01 00:09:00",
        "--bar-type", "TIME", "--bar-size", "60",
        "--strategy-params", json.dumps(sp),
        "--output-dir", str(output_dir),
        "--no-enforce-governance",
        "--json",
    ]
    if not enforce:
        cmd.append("--no-enforce-quality")
    return subprocess.run(
        cmd,
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _setup_run(tmp_path: Path, gates: dict | None) -> tuple[Path, Path, Path]:
    """Build archive/<run>/alphas/<a>/is layout and return (data_root, run_dir, output_dir)."""
    data_root = tmp_path / "bars"
    _write_bars(data_root, "BTCUSDT", 50000.0)
    _write_bars(data_root, "ETHUSDT", 3000.0)
    archive = tmp_path / "archive"
    run_dir = archive / "test_run"
    run_dir.mkdir(parents=True)
    splits: dict = {}
    if gates is not None:
        splits["quality_gates"] = gates
    (run_dir / "splits.json").write_text(json.dumps(splits))
    output_dir = run_dir / "alphas" / "alpha_x" / "is"
    return data_root, run_dir, output_dir


def test_backtest_deletes_artifact_when_min_trades_fails(tmp_path):
    data_root, run_dir, out = _setup_run(tmp_path, {"min_trades": 1_000_000})
    proc = _run_backtest_cli(run_root=run_dir, data_root=data_root, output_dir=out)
    result = _last_json(proc.stdout)
    assert result["quality"]["ok"] is False
    assert any(v["gate"] == "min_trades" for v in result["quality"]["violations"])
    assert result["artifact_kept"] is False
    assert result["ok"] is False
    assert not out.exists()
    assert proc.returncode != 0


def test_backtest_keeps_artifact_when_gates_pass(tmp_path):
    data_root, run_dir, out = _setup_run(tmp_path, {"min_trades": 0, "min_turnover": 0.0})
    proc = _run_backtest_cli(run_root=run_dir, data_root=data_root, output_dir=out)
    result = _last_json(proc.stdout)
    assert result["quality"]["ok"] is True
    assert result["artifact_kept"] is True
    assert (out / "weights.parquet").exists()
    assert proc.returncode == 0


def test_no_enforce_quality_keeps_failing_artifact(tmp_path):
    data_root, run_dir, out = _setup_run(tmp_path, {"min_trades": 1_000_000})
    proc = _run_backtest_cli(run_root=run_dir, data_root=data_root, output_dir=out, enforce=False)
    result = _last_json(proc.stdout)
    assert result["quality"]["ok"] is False
    assert result["artifact_kept"] is True
    assert out.exists()


def test_run_without_quality_gates_block_does_not_enforce(tmp_path):
    data_root, run_dir, out = _setup_run(tmp_path, gates=None)
    proc = _run_backtest_cli(run_root=run_dir, data_root=data_root, output_dir=out)
    result = _last_json(proc.stdout)
    assert result["quality"]["ok"] is True
    assert result["artifact_kept"] is True
    assert (out / "weights.parquet").exists()


def test_backtest_preflight_blocks_template_placeholder(tmp_path):
    """The default AlphaTemplateStrategy has ALPHA_CELL.idea_family set to the
    template placeholder; the pre-flight must refuse when enforcement is on.
    """
    data_root, run_dir, out = _setup_run(tmp_path, {"min_trades": 0, "min_turnover": 0.0})
    cmd = [
        "uv", "run", "python", "scripts/tools/backtest.py",
        "--data-type", "bars",
        "--strategy", "AlphaTemplateStrategy",
        "--symbols", "BTCUSDT", "ETHUSDT",
        "--data-path", str(data_root),
        "--start", "2025-03-01 00:00:00",
        "--end", "2025-03-01 00:09:00",
        "--bar-type", "TIME", "--bar-size", "60",
        "--strategy-params", json.dumps({
            "lookback_bars": 1, "rebalance_bars": 1, "entry_threshold": 0.00001,
            "exit_threshold": 0.0, "max_weight": 0.4,
        }),
        "--output-dir", str(out),
        "--json",
    ]
    proc = subprocess.run(
        cmd, cwd=Path(__file__).resolve().parents[2],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    result = _last_json(proc.stdout)
    assert result["ok"] is False
    assert "preflight" in result
    issues = result["preflight"]["issues"]
    assert any("template placeholder" in i for i in issues)
    assert not (out / "weights.parquet").exists()


def test_backtest_preflight_passes_with_disabled_enforcement(tmp_path):
    data_root, run_dir, out = _setup_run(tmp_path, {"min_trades": 0, "min_turnover": 0.0})
    cmd = [
        "uv", "run", "python", "scripts/tools/backtest.py",
        "--data-type", "bars",
        "--strategy", "AlphaTemplateStrategy",
        "--symbols", "BTCUSDT", "ETHUSDT",
        "--data-path", str(data_root),
        "--start", "2025-03-01 00:00:00",
        "--end", "2025-03-01 00:09:00",
        "--bar-type", "TIME", "--bar-size", "60",
        "--strategy-params", json.dumps({
            "lookback_bars": 1, "rebalance_bars": 1, "entry_threshold": 0.00001,
            "exit_threshold": 0.0, "max_weight": 0.4,
        }),
        "--output-dir", str(out),
        "--no-enforce-governance",
        "--json",
    ]
    proc = subprocess.run(
        cmd, cwd=Path(__file__).resolve().parents[2],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    result = _last_json(proc.stdout)
    # quality_gates loose, preflight bypassed → should succeed
    assert result["ok"] is True
    assert (out / "weights.parquet").exists()


def test_verify_artifact_cli_rejects_missing_artifact(tmp_path):
    proc = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "scripts/tools/verify_artifact.py",
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
    assert result["ok"] is False
    assert "artifact_dir not found" in result["errors"][0]
