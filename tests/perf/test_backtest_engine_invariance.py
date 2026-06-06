"""Golden-output regression test for the backtest engine.

Locks in the byte-equivalence (or numeric-equivalence) of the backtest
output for a fixed strategy + universe + window. Any change to the
engine — including memory-efficiency rewrites — MUST keep these
golden outputs unchanged.

How to use:
    # 1. Generate the baseline (only when engine is intentionally changed)
    BACKTEST_GOLDEN_REGEN=1 pytest tests/perf/test_backtest_engine_invariance.py

    # 2. After any engine edit, run this test to confirm output unchanged
    pytest tests/perf/test_backtest_engine_invariance.py

The baseline is checked in at ``tests/perf/golden/`` so CI catches
regressions automatically.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest


REPO = Path(__file__).resolve().parents[2]
GOLDEN_DIR = Path(__file__).parent / "golden"


_FIXED_CMD = [
    sys.executable, "-u",
    str(REPO / "scripts" / "tools" / "backtest.py"),
    "--strategy", "XsVolumeRankStrategy",
    "--strategy-params", '{"reverse": true}',
    "--symbols", "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "--data-type", "bars",
    "--data-path", "data/futures_klines_daily",
    "--start", "2024-01-01 00:00:00",
    "--end", "2024-03-31 23:59:00",
    "--bar-type", "TIME",
    "--bar-size", "86400",
    "--initial-capital", "10000",
    "--fixed-aum-sizing",
    "--maker-fee-rate", "0.0002",
    "--taker-fee-rate", "0.0005",
    "--no-enforce-quality",
    "--no-enforce-governance",
    "--json",
]

ARTIFACTS = ("metrics.json", "equity_curve.parquet", "trades.parquet",
             "weights.parquet")


def _run_backtest(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "SEAL_OPEN": "1"}
    cmd = _FIXED_CMD + ["--output-dir", str(out_dir)]
    res = subprocess.run(cmd, cwd=REPO, env=env,
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    assert res.returncode in (0, 2), f"backtest exit {res.returncode}"
    for a in ARTIFACTS:
        assert (out_dir / a).exists(), f"missing artifact {a}"


def _df_signature(df: pd.DataFrame) -> str:
    """Pandas DataFrame → stable hash that ignores column order but
    preserves row order and numeric values."""
    df = df.reindex(sorted(df.columns), axis=1)
    rows = []
    for col in df.columns:
        s = df[col]
        if pd.api.types.is_datetime64_any_dtype(s):
            rows.append((col, s.astype("int64").to_list()))
        elif pd.api.types.is_numeric_dtype(s):
            rows.append((col, [float(v) if pd.notna(v) else None for v in s]))
        else:
            rows.append((col, s.astype(str).to_list()))
    return hashlib.sha256(repr(rows).encode()).hexdigest()


def _metric_signature(path: Path) -> str:
    """metrics.json → hash of numeric core fields (ignores Python float
    repr drift)."""
    m = json.loads(path.read_text())
    core = {
        k: (round(float(v), 8) if isinstance(v, (int, float)) else v)
        for k, v in m.items()
        if k in ("initial_equity", "final_equity", "total_return",
                 "max_drawdown", "sharpe", "calmar", "total_trades",
                 "win_rate", "profit_factor")
    }
    return hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()


def _all_signatures(d: Path) -> dict[str, str]:
    sigs = {"metrics.json": _metric_signature(d / "metrics.json")}
    for a in ("equity_curve.parquet", "trades.parquet", "weights.parquet"):
        df = pd.read_parquet(d / a)
        sigs[a] = _df_signature(df)
    return sigs


def test_backtest_golden_output(tmp_path):
    if os.environ.get("BACKTEST_GOLDEN_REGEN") == "1":
        # Regenerate baseline (run when engine intentionally changed)
        if GOLDEN_DIR.exists():
            shutil.rmtree(GOLDEN_DIR)
        _run_backtest(GOLDEN_DIR)
        sigs = _all_signatures(GOLDEN_DIR)
        (GOLDEN_DIR / "signatures.json").write_text(json.dumps(sigs, indent=2))
        pytest.skip("baseline regenerated; rerun without BACKTEST_GOLDEN_REGEN=1")

    # Normal path: compare new run to baseline
    assert (GOLDEN_DIR / "signatures.json").exists(), (
        "golden baseline missing — generate first with BACKTEST_GOLDEN_REGEN=1"
    )
    expected = {
        k: v
        for k, v in json.loads((GOLDEN_DIR / "signatures.json").read_text()).items()
        if k in ARTIFACTS
    }

    _run_backtest(tmp_path)
    actual = _all_signatures(tmp_path)

    mismatches = [k for k in expected if expected[k] != actual.get(k)]
    if mismatches:
        msg_lines = ["Backtest output diverged from golden baseline:"]
        for k in mismatches:
            msg_lines.append(f"  {k}: expected {expected[k]} got {actual.get(k)}")
        pytest.fail("\n".join(msg_lines))
