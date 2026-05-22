#!/usr/bin/env python3
"""Backtest every strategy module under strategies/multi/zoo serially.

Each call is the same canonical full-period+IS/OS-split backtest the
unified forward pipeline uses, but writes into a flat
``archive/<run>/alphas/<alpha_id>/`` directory so the dashboard's
classifier can read IC fields directly without a forward slice.

Run:
    SEAL_OPEN=1 uv run python scripts/run_batch_backtests.py \\
        --run-id run_2026_05_xs500 --max-workers 1
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
ZOO_PKG = "intraday.strategies.multi"
ZOO_DIR = REPO / "src" / "intraday" / "strategies" / "multi"


def _splits(run_id: str) -> dict:
    return json.loads((REPO / "archive" / run_id / "splits.json").read_text())


def _list_zoo_modules() -> list[tuple[str, str]]:
    """(module_filename_stem, class_name) for every generated zoo module.
    Picks up xs_factor_* (XsFactorBase subclasses) AND xs_reg_*
    (XsRegressionBase subclasses) — anything starting with xs_factor_
    or xs_reg_ in strategies/multi/."""
    out: list[tuple[str, str]] = []
    patterns = ["xs_factor_*.py", "xs_reg_*.py"]
    seen: set[Path] = set()
    files: list[Path] = []
    for pat in patterns:
        for f in ZOO_DIR.glob(pat):
            if f in seen: continue
            seen.add(f); files.append(f)
    for f in sorted(files):
        try:
            text = f.read_text()
        except Exception:
            continue
        cls = None
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("class ") and ("(XsFactorBase)" in line or "(XsRegressionBase)" in line):
                cls = line.split(" ", 1)[1].split("(", 1)[0].strip()
                break
        if cls:
            out.append((f.stem, cls))
    return out


def _alpha_id_for(module_stem: str) -> str:
    return module_stem  # already snake_case, unique


def _run_one(class_name: str, alpha_id: str, run_id: str,
             universe: list[str], is_start: str, is_end: str, os_end: str,
             initial_capital: float, fee_taker: float, fee_maker: float,
             force: bool = False) -> int:
    out_dir = REPO / "archive" / run_id / "alphas" / alpha_id
    if not force and (out_dir / "metrics.json").exists():
        return 0  # already backtested — idempotent skip
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
        "--initial-capital", str(initial_capital),
        "--fixed-aum-sizing",
        "--maker-fee-rate", str(fee_maker),
        "--taker-fee-rate", str(fee_taker),
        "--no-enforce-quality",
        "--no-enforce-governance",
        "--output-dir", str(out_dir),
        "--json",
    ]
    # Send backtest stdout to DEVNULL — its --json blob is several KB
    # per alpha and `capture_output=True` deadlocked the parent loop after
    # the first few iterations. metrics.json on disk is the canonical
    # output we care about.
    res = subprocess.run(cmd, cwd=REPO,
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    if res.returncode not in (0, 2):
        return res.returncode
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-id", default="run_2026_05_xs500")
    ap.add_argument("--initial-capital", type=float, default=10000.0)
    ap.add_argument("--maker-fee-rate", type=float, default=0.0002)
    ap.add_argument("--taker-fee-rate", type=float, default=0.0005)
    ap.add_argument("--limit", type=int, default=None,
                    help="Process at most N alphas (for smoke runs).")
    ap.add_argument("--start-from", default=None,
                    help="Resume from this alpha id (sorted order).")
    ap.add_argument("--force", action="store_true",
                    help="Re-run even when metrics.json already exists.")
    args = ap.parse_args()

    sp = _splits(args.run_id)
    universe = sp["universe"]
    is_start = sp["is"]["start"]
    is_end = sp["is"]["end"]
    os_end = sp["os"]["end"]

    alphas = _list_zoo_modules()
    if args.start_from:
        names = [a[0] for a in alphas]
        try:
            idx = names.index(args.start_from)
            alphas = alphas[idx:]
        except ValueError:
            pass
    if args.limit:
        alphas = alphas[: args.limit]

    print(f"[batch] {len(alphas)} alphas, universe={len(universe)}", flush=True)
    started = time.time()
    n_ok = 0
    n_fail = 0
    failed: list[str] = []
    for i, (module_stem, class_name) in enumerate(alphas, 1):
        alpha_id = _alpha_id_for(module_stem)
        t0 = time.time()
        rc = _run_one(class_name, alpha_id, args.run_id, universe,
                      is_start, is_end, os_end,
                      args.initial_capital, args.taker_fee_rate, args.maker_fee_rate,
                      force=args.force)
        elapsed = time.time() - t0
        if rc == 0:
            n_ok += 1
        else:
            n_fail += 1
            failed.append(f"{alpha_id} rc={rc}")
        avg = (time.time() - started) / i
        eta = avg * (len(alphas) - i)
        print(f"  [{i}/{len(alphas)}] {alpha_id} rc={rc} elapsed={elapsed:.1f}s "
              f"avg={avg:.1f}s eta={eta/60:.1f}min", flush=True)
    print(f"\n[batch] done ok={n_ok} fail={n_fail}", flush=True)
    for f in failed[:20]:
        print(f"  fail: {f}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
