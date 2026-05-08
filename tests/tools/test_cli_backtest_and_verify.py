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
