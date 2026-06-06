#!/usr/bin/env python3
"""Run the AMIHUD gross-5 composite live forward tick.

This is a daily paper-forward orchestrator:

1. sync the run universe daily klines once,
2. refresh the five child AMIHUD forward runs,
3. combine their forward target weights at gross 5,
4. replay the composite through the standard backtester into
   ``composites/<composite_id>/forward/``.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from math import sqrt
from pathlib import Path

import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parent.parent
ARCHIVE = REPO / "archive"
BACKTEST = REPO / "scripts" / "tools" / "backtest.py"

RUN_ID = "run_2026_05_full531_rerun_backtests"
COMPOSITE_ID = "hierarchical_amihud_quality_corr095_gross5_weight_composite_v1"
CHILDREN: list[tuple[str, float, float]] = [
    ("xs_factor_amihud60d_fwd_c10", 0.10, 0.20),
    ("xs_factor_amihud60d_fwd_c20", 0.20, 0.20),
    ("xs_factor_amihud60d_fwd_c30", 0.30, 0.20),
    ("xs_factor_amihud60d_fwd_c40", 0.40, 0.20),
    ("xs_factor_amihud60d_fwd_c50", 0.50, 0.20),
]
GROSS_EPS = 1e-12


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _forward_start(splits: dict) -> str:
    os_end = splits.get("os", {}).get("end") or splits["is"]["end"]
    return (pd.Timestamp(os_end) + pd.Timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, cwd=REPO, text=True, check=False)
    if proc.returncode not in (0, 2):
        raise RuntimeError(f"command failed rc={proc.returncode}: {' '.join(cmd)}")


def _sync_data(universe: list[str], as_of: str) -> None:
    cmd = [
        sys.executable,
        "-u",
        str(REPO / "scripts" / "tools" / "download_daily_klines.py"),
        "--start",
        "2026-01-01",
        "--end",
        as_of,
        "--force",
        "--symbols",
        *universe,
    ]
    _run(cmd)


def _run_child_forward(
    run_dir: Path,
    splits: dict,
    universe: list[str],
    alpha_id: str,
    concentration_pct: float,
    as_of: str,
) -> None:
    out_dir = run_dir / "alphas" / alpha_id / "forward"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    params = json.dumps({"concentration_pct": concentration_pct, "reverse": False})
    cmd = [
        sys.executable,
        str(BACKTEST),
        "--strategy",
        "XsFactorAmihud60dFwdC10",
        "--symbols",
        *universe,
        "--data-type",
        "bars",
        "--data-path",
        "data/futures_klines_daily",
        "--bar-type",
        "TIME",
        "--bar-size",
        "86400",
        "--start",
        splits["is"]["start"],
        "--end",
        f"{as_of} 23:59" if " " not in as_of else as_of,
        "--is-end",
        splits["is"]["end"],
        "--initial-capital",
        "10000",
        "--fixed-aum-sizing",
        "--maker-fee-rate",
        "0.0002",
        "--taker-fee-rate",
        "0.0005",
        "--strategy-params",
        params,
        "--output-dir",
        str(out_dir),
        "--no-enforce-quality",
        "--no-enforce-governance",
        "--json",
    ]
    _run(cmd)
    _slice_forward_artifacts(out_dir, _forward_start(splits))


def _load_forward_panel(run_dir: Path, alpha_id: str, universe: list[str]) -> pd.DataFrame:
    path = run_dir / "alphas" / alpha_id / "forward" / "weights.parquet"
    if not path.exists():
        raise FileNotFoundError(f"child forward weights missing: {path}")
    df = pd.read_parquet(path, columns=["timestamp", "symbol", "target_weight"])
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["symbol"] = df["symbol"].astype(str).str.upper()
    df = df[df["symbol"].isin(universe)]
    if df.empty:
        return pd.DataFrame(columns=universe)
    return (
        df.pivot_table(index="timestamp", columns="symbol", values="target_weight", aggfunc="last")
        .reindex(columns=universe)
        .sort_index()
    )


def _panel_to_rebalance_rows(panel: pd.DataFrame, universe: list[str]) -> pd.DataFrame:
    rows: list[tuple[pd.Timestamp, str, float]] = []
    prev = panel[universe].shift().fillna(0.0) if not panel.empty else panel
    for ts in panel.index:
        cur = panel.loc[ts, universe]
        was = prev.loc[ts, universe]
        active_or_closing = (cur.abs() > GROSS_EPS) | (was.abs() > GROSS_EPS)
        for symbol in cur.index[active_or_closing]:
            rows.append((ts, symbol, float(cur.loc[symbol])))
    return pd.DataFrame(rows, columns=["timestamp", "symbol", "target_weight"]).sort_values(
        ["timestamp", "symbol"]
    )


def _combine_child_forwards(run_dir: Path, universe: list[str], target_gross: float) -> tuple[pd.DataFrame, dict]:
    panels: dict[str, pd.DataFrame] = {
        alpha_id: _load_forward_panel(run_dir, alpha_id, universe)
        for alpha_id, _, _ in CHILDREN
    }
    idx = pd.DatetimeIndex(sorted(set().union(*[p.index for p in panels.values() if not p.empty])))
    combined = pd.DataFrame(0.0, index=idx, columns=universe)
    for alpha_id, _, coef in CHILDREN:
        aligned = panels[alpha_id].reindex(idx).ffill().fillna(0.0)
        combined = combined.add(aligned * coef, fill_value=0.0)
    combined = combined[universe]
    raw_l1 = combined.abs().sum(axis=1)
    scale = pd.Series(target_gross, index=idx) / raw_l1.replace(0.0, np.nan)
    scale = scale.replace([np.inf, -np.inf], np.nan).fillna(1.0)
    combined = combined.mul(scale, axis=0)
    final_l1 = combined.abs().sum(axis=1)
    rows = _panel_to_rebalance_rows(combined, universe).reset_index(drop=True)
    stats = {
        "target_gross": float(target_gross),
        "max_gross": float(target_gross),
        "raw_mean_row_l1": float(raw_l1.mean()) if len(raw_l1) else 0.0,
        "raw_max_row_l1": float(raw_l1.max()) if len(raw_l1) else 0.0,
        "mean_row_l1": float(final_l1.mean()) if len(final_l1) else 0.0,
        "max_row_l1": float(final_l1.max()) if len(final_l1) else 0.0,
        "n_change_events": int(len(rows)),
    }
    return rows, stats


def _slice_forward_artifacts(out_dir: Path, forward_start: str) -> None:
    cutoff = pd.Timestamp(forward_start)
    for name in ("equity_curve.parquet", "trades.parquet", "weights.parquet"):
        path = out_dir / name
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        if "timestamp" not in df.columns:
            continue
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df[df["timestamp"] >= cutoff].reset_index(drop=True)
        df.to_parquet(path, index=False)
    _rewrite_sliced_metrics(out_dir)


def _rewrite_sliced_metrics(out_dir: Path) -> None:
    metrics_path = out_dir / "metrics.json"
    equity_path = out_dir / "equity_curve.parquet"
    trades_path = out_dir / "trades.parquet"
    if not metrics_path.exists() or not equity_path.exists():
        return

    metrics = _read_json(metrics_path)
    equity = pd.read_parquet(equity_path)
    if equity.empty or "equity" not in equity.columns:
        return

    equity = equity.copy()
    equity["equity"] = pd.to_numeric(equity["equity"], errors="coerce")
    equity = equity.dropna(subset=["equity"])
    if equity.empty:
        return

    start_equity = float(equity["equity"].iloc[0])
    end_equity = float(equity["equity"].iloc[-1])
    total_return = (end_equity / start_equity - 1.0) if start_equity else 0.0
    running_peak = equity["equity"].cummax()
    drawdowns = equity["equity"] / running_peak.replace(0.0, np.nan) - 1.0
    max_drawdown = float(drawdowns.min()) if len(drawdowns) else 0.0

    returns = equity["equity"].pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    sharpe = 0.0
    if len(returns) > 1:
        std = float(returns.std(ddof=1))
        if std > 0:
            sharpe = float(returns.mean() / std * sqrt(252.0))

    trade_count = 0
    win_rate = metrics.get("win_rate", 0.0)
    if trades_path.exists():
        trades = pd.read_parquet(trades_path)
        trade_count = int(len(trades))
        pnl_col = "pnl" if "pnl" in trades.columns else None
        if pnl_col and trade_count:
            pnl = pd.to_numeric(trades[pnl_col], errors="coerce").fillna(0.0)
            win_rate = float((pnl > 0).mean())

    metrics.update(
        {
            "initial_capital": start_equity,
            "final_capital": end_equity,
            "total_return": total_return,
            "sharpe": sharpe,
            "sharpe_daily_annualized": sharpe,
            "max_drawdown": max_drawdown,
            "total_trades": trade_count,
            "win_rate": win_rate,
        }
    )
    metrics_path.write_text(json.dumps(metrics, indent=2, default=str))


def _run_composite_forward(
    *,
    run_dir: Path,
    splits: dict,
    universe: list[str],
    as_of: str,
    target_gross: float,
) -> dict:
    comp_forward = run_dir / "composites" / COMPOSITE_ID / "forward"
    if comp_forward.exists():
        shutil.rmtree(comp_forward)
    comp_forward.mkdir(parents=True, exist_ok=True)

    weights, stats = _combine_child_forwards(run_dir, universe, target_gross)
    weights_path = comp_forward / "composite_input_weights.parquet"
    weights.to_parquet(weights_path, index=False)

    cmd = [
        sys.executable,
        str(BACKTEST),
        "--strategy",
        "PrecomputedWeightsStrategy",
        "--symbols",
        *universe,
        "--data-type",
        "bars",
        "--data-path",
        "data/futures_klines_daily",
        "--bar-type",
        "TIME",
        "--bar-size",
        "86400",
        "--start",
        splits["is"]["start"],
        "--end",
        f"{as_of} 23:59" if " " not in as_of else as_of,
        "--is-end",
        splits["is"]["end"],
        "--initial-capital",
        "10000",
        "--fixed-aum-sizing",
        "--max-portfolio-weight",
        str(target_gross),
        "--maker-fee-rate",
        "0.0002",
        "--taker-fee-rate",
        "0.0005",
        "--strategy-params",
        json.dumps({"weights_path": str(weights_path), "alpha_id": COMPOSITE_ID}),
        "--output-dir",
        str(comp_forward),
        "--no-enforce-quality",
        "--no-enforce-governance",
        "--json",
    ]
    _run(cmd)
    _slice_forward_artifacts(comp_forward, _forward_start(splits))

    manifest = {
        "composite_id": COMPOSITE_ID,
        "run_id": RUN_ID,
        "run_type": "forward",
        "source": "child_forward_weights",
        "children": [
            {"alpha_id": alpha_id, "concentration_pct": cp, "coefficient": coef}
            for alpha_id, cp, coef in CHILDREN
        ],
        "as_of": as_of,
        **stats,
    }
    (comp_forward / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--run-id", default=RUN_ID)
    parser.add_argument("--target-gross", type=float, default=5.0)
    parser.add_argument("--sync-data", action="store_true")
    args = parser.parse_args(argv)

    run_dir = ARCHIVE / args.run_id
    splits = _read_json(run_dir / "splits.json")
    requested = [s.upper() for s in splits["universe"]]
    universe = [s for s in requested if (REPO / "data" / "futures_klines_daily" / s).exists()]
    if args.sync_data:
        _sync_data(universe, args.as_of)

    for alpha_id, concentration_pct, _ in CHILDREN:
        _run_child_forward(run_dir, splits, universe, alpha_id, concentration_pct, args.as_of)

    manifest = _run_composite_forward(
        run_dir=run_dir,
        splits=splits,
        universe=universe,
        as_of=args.as_of,
        target_gross=float(args.target_gross),
    )
    print(json.dumps({"ok": True, "manifest": manifest}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
