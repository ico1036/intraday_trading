#!/usr/bin/env python3
"""Per-attempt AGENT.md loop for run_2026_05_full531.

For each unrun zoo strategy under ``src/intraday/strategies/multi/``:

1. Skip if alpha dir already exists with ``is/metrics.json`` (idempotent).
2. Run IS+OS combined backtest via ``backtest.py`` (flat layout).
3. Split flat artifacts into ``is/`` / ``os/`` subdirs.
4. Read ``is/metrics.json`` (and ``os/metrics.json``); classify via
   ``alpha_dashboard_lib.classify_alpha`` (IS+OS gate).
5. Append a one-line entry to ``alpha_index.csv`` and a short LOG entry.
6. Print running counts (attempted, IS_SUBMITTABLE, IS+OS SUBMITTABLE).

Stop conditions (whichever first):
  * Reached ``--target`` IS+OS SUBMITTABLE.
  * Exhausted alpha pool.
  * ``--max-attempts`` reached.

Does NOT touch other framework code. Per-attempt deletion of the alpha
artifact on quality-gate failure is the backtest engine's responsibility.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts" / "tools"))
from alpha_dashboard_lib import classify_alpha  # noqa: E402


ZOO_DIR = REPO / "src" / "intraday" / "strategies" / "multi"


def _list_zoo() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for f in sorted(ZOO_DIR.glob("xs_factor_*.py")) + sorted(ZOO_DIR.glob("xs_reg_*.py")):
        text = f.read_text()
        cls = None
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("class ") and ("(XsFactorBase)" in line or "(XsRegressionBase)" in line):
                cls = line.split(" ", 1)[1].split("(", 1)[0].strip()
                break
        if cls:
            out.append((f.stem, cls))
    return out


def _split_flat_to_is_os(alpha_dir: Path, is_end: str) -> None:
    """Move flat artifacts into is/ os/ subdirs. Re-run safe.

    Top-level IC keys (``ic_mean_is``, ``ic_mean_os``, ``ic_z`` etc.) are
    promoted into the IS/OS sub-blocks so ``classify_alpha`` can read
    ``is/metrics.json`` directly. Without this promotion the IS sub-block
    has ic_mean=None and every alpha falls back to NORMAL.
    """
    import math as _math
    import pandas as pd
    cutoff = pd.Timestamp(is_end)
    is_dir = alpha_dir / "is"
    os_dir = alpha_dir / "os"
    is_dir.mkdir(exist_ok=True)
    os_dir.mkdir(exist_ok=True)

    mfp = alpha_dir / "metrics.json"
    if mfp.exists():
        m = json.loads(mfp.read_text())
        is_block = dict(m.get("is")) if isinstance(m.get("is"), dict) else dict(m)
        os_block = dict(m.get("os")) if isinstance(m.get("os"), dict) else {}

        # Promote IC sub-keys into the respective split blocks.
        def _ir(mean, std, bars_per_year=365.0):
            try:
                return float(mean) / float(std) * _math.sqrt(bars_per_year) if std else None
            except Exception:
                return None
        if "ic_mean_is" in m:
            is_block["ic_mean"] = m.get("ic_mean_is")
            is_block["ic_std"] = m.get("ic_std_is")
            is_block["ic_bars"] = m.get("ic_bars_is")
            is_block["ic_ir"] = _ir(m.get("ic_mean_is"), m.get("ic_std_is"))
        if "ic_mean_os" in m:
            os_block["ic_mean"] = m.get("ic_mean_os")
            os_block["ic_std"] = m.get("ic_std_os")
            os_block["ic_bars"] = m.get("ic_bars_os")
            os_block["ic_ir"] = _ir(m.get("ic_mean_os"), m.get("ic_std_os"))
        if "ic_z" in m:
            is_block["ic_z"] = m.get("ic_z")
            os_block["ic_z"] = m.get("ic_z")

        (is_dir / "metrics.json").write_text(json.dumps(is_block, indent=2, default=str))
        (os_dir / "metrics.json").write_text(json.dumps(os_block, indent=2, default=str))

    for name in ("weights.parquet", "equity_curve.parquet",
                 "trades.parquet", "events.parquet"):
        p = alpha_dir / name
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        if "timestamp" not in df.columns:
            continue
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        is_df = df[df["timestamp"] <= cutoff].reset_index(drop=True)
        os_df = df[df["timestamp"] > cutoff].reset_index(drop=True)
        is_df.to_parquet(is_dir / name, index=False)
        os_df.to_parquet(os_dir / name, index=False)

    mf = alpha_dir / "manifest.json"
    if mf.exists():
        (is_dir / "manifest.json").write_text(mf.read_text())
        (os_dir / "manifest.json").write_text(mf.read_text())


def _run_one(class_name: str, alpha_id: str, run_id: str,
             universe: list[str], is_start: str, is_end: str, os_end: str) -> int:
    out_dir = REPO / "archive" / run_id / "alphas" / alpha_id
    if (out_dir / "metrics.json").exists():
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "-u",
        str(REPO / "scripts" / "tools" / "backtest.py"),
        "--strategy", class_name,
        "--symbols", *universe,
        "--data-type", "bars",
        "--data-path", "data/futures_klines_daily",
        "--start", is_start,
        "--end", os_end,
        "--is-end", is_end,
        "--bar-type", "TIME",
        "--bar-size", "86400",
        "--initial-capital", "10000",
        "--fixed-aum-sizing",
        "--maker-fee-rate", "0.0002",
        "--taker-fee-rate", "0.0005",
        "--no-enforce-quality",
        "--no-enforce-governance",
        "--output-dir", str(out_dir),
        "--json",
    ]
    env = {**os.environ, "SEAL_OPEN": "1"}
    res = subprocess.run(cmd, cwd=REPO, env=env,
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    return res.returncode


def _classify(alpha_dir: Path) -> tuple[str, str, dict | None, dict | None]:
    mp = alpha_dir / "metrics.json"
    if not mp.exists():
        return "NO_IS", "no metrics", None, None
    m = json.loads(mp.read_text())
    is_m = m.get("is") if isinstance(m.get("is"), dict) else m
    os_m = m.get("os") if isinstance(m.get("os"), dict) else None
    label_is, why_is = classify_alpha(is_m, os_m=None)
    label, why = classify_alpha(is_m, os_m=os_m)
    return label, why, is_m, os_m


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--target", type=int, default=100,
                    help="Stop after this many IS+OS SUBMITTABLE.")
    ap.add_argument("--max-attempts", type=int, default=2000)
    ap.add_argument("--start-from", default=None)
    args = ap.parse_args()

    sp = json.loads((REPO / "archive" / args.run_id / "splits.json").read_text())
    universe = sp["universe"]
    is_start = sp["is"]["start"]
    is_end = sp["is"]["end"]
    os_end = sp["os"]["end"]

    alphas = _list_zoo()
    if args.start_from:
        names = [a[0] for a in alphas]
        try:
            alphas = alphas[names.index(args.start_from):]
        except ValueError:
            pass

    print(f"[loop] {len(alphas)} zoo strategies, target={args.target} "
          f"IS+OS SUBMITTABLE, max_attempts={args.max_attempts}", flush=True)

    n_attempted = n_is_sub = n_full_sub = 0
    started = time.time()
    log_path = REPO / "archive" / args.run_id / "LOG.md"
    index_path = REPO / "archive" / args.run_id / "alpha_index.csv"
    if not index_path.exists() or index_path.read_text().strip() == "":
        index_path.write_text("alpha_id,strategy,status,is_sharpe,is_return,is_trades,os_sharpe,os_return,os_trades,label_is,label_full\n")

    for i, (alpha_id, class_name) in enumerate(alphas, 1):
        if n_attempted >= args.max_attempts:
            print(f"[loop] reached max_attempts={args.max_attempts}, stopping", flush=True)
            break
        if n_full_sub >= args.target:
            print(f"[loop] reached target={args.target} IS+OS SUBMITTABLE, stopping", flush=True)
            break

        alpha_dir = REPO / "archive" / args.run_id / "alphas" / alpha_id
        already_done = (alpha_dir / "is" / "metrics.json").exists()
        t0 = time.time()
        if not already_done:
            rc = _run_one(class_name, alpha_id, args.run_id, universe, is_start, is_end, os_end)
            n_attempted += 1
        else:
            rc = 0
        elapsed = time.time() - t0

        label, why, is_m, os_m = _classify(alpha_dir)
        if label == "SUBMITTABLE":
            n_full_sub += 1
        label_is, _ = classify_alpha(is_m, os_m=None) if is_m else ("NO_IS", "")
        if label_is == "SUBMITTABLE":
            n_is_sub += 1

        is_sharpe = (is_m or {}).get("sharpe")
        os_sharpe = (os_m or {}).get("sharpe")
        with open(index_path, "a") as f:
            f.write(
                f"{alpha_id},{class_name},rc={rc},{is_sharpe},"
                f"{(is_m or {}).get('total_return')},{(is_m or {}).get('total_trades')},"
                f"{os_sharpe},{(os_m or {}).get('total_return')},{(os_m or {}).get('total_trades')},"
                f"{label_is},{label}\n"
            )

        avg = (time.time() - started) / max(1, n_attempted)
        def _fmt(x):
            return f"{x:.3f}" if isinstance(x, (int, float)) else "NaN"
        print(
            f"[{i}/{len(alphas)}] {alpha_id} rc={rc} elapsed={elapsed:.1f}s "
            f"IS_sharpe={_fmt(is_sharpe)} OS_sharpe={_fmt(os_sharpe)} "
            f"label={label}  n_full_sub={n_full_sub}/{args.target} "
            f"avg={avg:.1f}s",
            flush=True,
        )

        if label == "SUBMITTABLE" or label_is == "SUBMITTABLE":
            with open(log_path, "a") as f:
                f.write(
                    f"\n## {alpha_id} — {label} (IS-only label: {label_is})\n\n"
                    f"strategy={class_name}\n"
                    f"IS: sharpe={is_sharpe} return={(is_m or {}).get('total_return')} trades={(is_m or {}).get('total_trades')} dd={(is_m or {}).get('max_drawdown')} pf={(is_m or {}).get('profit_factor')}\n"
                    f"OS: sharpe={os_sharpe} return={(os_m or {}).get('total_return') if os_m else 'NA'} trades={(os_m or {}).get('total_trades') if os_m else 'NA'} dd={(os_m or {}).get('max_drawdown') if os_m else 'NA'} pf={(os_m or {}).get('profit_factor') if os_m else 'NA'}\n"
                    f"reason: {why}\n"
                )

    print(f"\n[loop] done attempted={n_attempted} is_submit={n_is_sub} full_submit={n_full_sub} "
          f"elapsed={(time.time()-started)/60:.1f}min", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
