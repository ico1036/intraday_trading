#!/usr/bin/env python3
"""Integrity test — verify a strategy's weight emission is path-stable.

For each alpha, run two overlapping backtest windows:

    chunk A: [IS_start, IS_start + 80% of full range]
    chunk B: [IS_start + 20% of full range, OS_end]

The two backtests overlap on [20%, 80%]. Within that overlap we
trim away each chunk's first 90 bars (warmup) and then compare the
emitted target_weight per (timestamp, symbol) between A and B.

A deterministic + warmup-converged strategy yields identical
weights at every overlapping (t, s) — match_rate close to 1.0.
A path-dependent / random / under-warmed strategy diverges.

Results land in the alpha's metrics.json under ``integrity_match_rate``.

Run:
    SEAL_OPEN=1 uv run python scripts/tools/integrity_test.py \\
        --run-id run_2026_05_xs500 --alpha-id <id>

    SEAL_OPEN=1 uv run python scripts/tools/integrity_test.py \\
        --run-id run_2026_05_xs500 --all-submittable
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd


REPO = Path(__file__).resolve().parents[2]
ARCHIVE = REPO / "archive"
WARMUP_BARS = 90  # daily bars to skip after each chunk's start


def _splits(run_id: str) -> dict:
    return json.loads((ARCHIVE / run_id / "splits.json").read_text())


def _detect_strategy_class(alpha_dir: Path) -> str | None:
    """summary.json's strategy_name is the canonical strategy class."""
    for p in (alpha_dir / "summary.json",
              alpha_dir / "is" / "summary.json",
              alpha_dir / "forward" / "summary.json"):
        if p.exists():
            try:
                v = json.loads(p.read_text()).get("strategy_name")
                if v:
                    return str(v)
            except Exception:
                pass
    return None


def _detect_strategy_params(alpha_dir: Path) -> dict:
    """Pick the most-likely params from queue.json if present (legacy)."""
    queue = alpha_dir.parent.parent / "queue.json"
    if not queue.exists():
        return {}
    try:
        data = json.loads(queue.read_text())
        for variant in data.get("variants", []):
            if variant.get("alpha_id") == alpha_dir.name:
                return variant.get("params", {}) or {}
    except Exception:
        pass
    return {}


def _run_backtest_chunk(class_name: str, strategy_params: dict,
                       run_id: str, universe: list[str],
                       start: str, end: str,
                       output_dir: Path,
                       bar_size: float, initial_capital: float) -> int:
    """Spawn a single backtest into output_dir. Returns subprocess rc."""
    cmd = [
        sys.executable, "-u",
        str(REPO / "scripts" / "tools" / "backtest.py"),
        "--strategy", class_name,
        "--symbols", *universe,
        "--data-type", "bars",
        "--data-path", "data/futures_klines_daily",
        "--start", start,
        "--end", end,
        "--bar-type", "TIME",
        "--bar-size", str(bar_size),
        "--initial-capital", str(initial_capital),
        "--fixed-aum-sizing",
        "--no-enforce-quality",
        "--no-enforce-governance",
        "--output-dir", str(output_dir),
        "--json",
    ]
    if strategy_params:
        cmd.extend(["--strategy-params", json.dumps(strategy_params)])
    return subprocess.run(cmd, cwd=REPO,
                          stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode


def _match_rate(weights_a: pd.DataFrame, weights_b: pd.DataFrame,
                overlap_start: pd.Timestamp, overlap_end: pd.Timestamp,
                tol: float = 1e-6) -> dict:
    """Return overlap match rate + sample stats between two chunks."""
    if weights_a.empty or weights_b.empty:
        return {"match_rate": None, "compared_rows": 0,
                "reason": "empty weights"}
    for w in (weights_a, weights_b):
        w["timestamp"] = pd.to_datetime(w["timestamp"])
        w["symbol"] = w["symbol"].astype(str).str.upper()
    a = weights_a[(weights_a["timestamp"] >= overlap_start) &
                  (weights_a["timestamp"] <= overlap_end)]
    b = weights_b[(weights_b["timestamp"] >= overlap_start) &
                  (weights_b["timestamp"] <= overlap_end)]
    a = a[["timestamp", "symbol", "target_weight"]].rename(
        columns={"target_weight": "w_a"})
    b = b[["timestamp", "symbol", "target_weight"]].rename(
        columns={"target_weight": "w_b"})
    j = a.merge(b, on=["timestamp", "symbol"], how="inner")
    if j.empty:
        return {"match_rate": None, "compared_rows": 0,
                "reason": "no overlap rows"}
    matched = ((j["w_a"] - j["w_b"]).abs() < tol).sum()
    return {
        "match_rate": float(matched / len(j)),
        "compared_rows": int(len(j)),
        "mean_abs_diff": float((j["w_a"] - j["w_b"]).abs().mean()),
        "max_abs_diff": float((j["w_a"] - j["w_b"]).abs().max()),
    }


def integrity_test_alpha(run_id: str, alpha_id: str) -> dict:
    splits = _splits(run_id)
    universe = splits["universe"]
    is_start = pd.Timestamp(splits["is"]["start"])
    os_end = pd.Timestamp(splits["os"]["end"])
    full_span = os_end - is_start

    # 2 chunks with 60% overlap on [20%, 80%] of the full span
    a_start = is_start
    a_end = is_start + 0.80 * full_span
    b_start = is_start + 0.20 * full_span
    b_end = os_end
    overlap_start = b_start + pd.Timedelta(days=WARMUP_BARS)
    overlap_end = a_end

    alpha_dir = ARCHIVE / run_id / "alphas" / alpha_id
    class_name = _detect_strategy_class(alpha_dir)
    if not class_name:
        return {"alpha_id": alpha_id, "match_rate": None,
                "reason": "no strategy_name in summary.json"}
    strategy_params = _detect_strategy_params(alpha_dir)

    with tempfile.TemporaryDirectory(prefix=f"int_{alpha_id}_") as tmp:
        tmp_path = Path(tmp)
        out_a = tmp_path / "A"
        out_b = tmp_path / "B"

        # bar_size from summary.json — default daily
        bs_file = next((p for p in (alpha_dir / "summary.json",
                                     alpha_dir / "is" / "summary.json")
                        if p.exists()), None)
        bar_size = 86400.0
        if bs_file is not None:
            try:
                bar_size = float(json.loads(bs_file.read_text()).get("bar_size") or 86400.0)
            except Exception:
                pass

        rc_a = _run_backtest_chunk(
            class_name, strategy_params, run_id, universe,
            str(a_start), str(a_end), out_a, bar_size, 10000.0)
        rc_b = _run_backtest_chunk(
            class_name, strategy_params, run_id, universe,
            str(b_start), str(b_end), out_b, bar_size, 10000.0)
        if rc_a not in (0, 2) or rc_b not in (0, 2):
            return {"alpha_id": alpha_id, "match_rate": None,
                    "reason": f"backtest rc a={rc_a} b={rc_b}"}
        wa_path = out_a / "weights.parquet"
        wb_path = out_b / "weights.parquet"
        if not (wa_path.exists() and wb_path.exists()):
            return {"alpha_id": alpha_id, "match_rate": None,
                    "reason": "missing weights.parquet"}
        wa = pd.read_parquet(wa_path)
        wb = pd.read_parquet(wb_path)

    stats = _match_rate(wa, wb, overlap_start, overlap_end)
    stats["alpha_id"] = alpha_id
    stats["run_id"] = run_id
    stats["class_name"] = class_name
    stats["overlap_start"] = str(overlap_start)
    stats["overlap_end"] = str(overlap_end)
    return stats


def write_integrity_to_metrics(run_id: str, alpha_id: str, stats: dict) -> None:
    alpha_dir = ARCHIVE / run_id / "alphas" / alpha_id
    for cand in (alpha_dir / "metrics.json",
                 alpha_dir / "is" / "metrics.json",
                 alpha_dir / "forward" / "metrics.json"):
        if cand.exists():
            try:
                payload = json.loads(cand.read_text())
            except Exception:
                continue
            payload["integrity_match_rate"] = stats.get("match_rate")
            payload["integrity_compared_rows"] = stats.get("compared_rows")
            payload["integrity_mean_abs_diff"] = stats.get("mean_abs_diff")
            cand.write_text(json.dumps(payload, indent=2, default=str))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-id", default="run_2026_05_xs500")
    ap.add_argument("--alpha-id", default=None)
    ap.add_argument("--all-submittable", action="store_true")
    args = ap.parse_args()

    targets: list[tuple[str, str]] = []
    if args.alpha_id:
        targets.append((args.run_id, args.alpha_id))
    elif args.all_submittable:
        sys.path.insert(0, str(REPO / "scripts" / "tools"))
        from alpha_dashboard import load_index  # type: ignore
        df = load_index(ARCHIVE)
        sub = df[(df["category"] == "SUBMITTABLE") & (df["bar_label"] == "1d")]
        for _, row in sub.iterrows():
            targets.append((row["run_id"], row["alpha_id"]))

    if not targets:
        print("no targets", file=sys.stderr)
        return 1
    print(f"[integrity] {len(targets)} alphas to test", flush=True)
    import time
    t0 = time.time()
    for i, (run_id, alpha_id) in enumerate(targets, 1):
        stats = integrity_test_alpha(run_id, alpha_id)
        write_integrity_to_metrics(run_id, alpha_id, stats)
        mr = stats.get("match_rate")
        rows = stats.get("compared_rows", 0)
        elapsed = time.time() - t0
        eta = elapsed * (len(targets) - i) / max(i, 1)
        mr_str = f"{mr:.3f}" if mr is not None else "NA"
        print(f"  [{i}/{len(targets)}] {alpha_id:60s} "
              f"match={mr_str} rows={rows}  "
              f"elapsed={elapsed:.0f}s eta={eta:.0f}s",
              flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
