#!/usr/bin/env python3
"""Forward runner — deterministic backtest of `[IS_start .. as_of]`.

The "forward" output of an alpha is just its full-period backtest re-run
each day, with the latest cached daily kline included. There is no
websocket, no resume state, no warmup logic — every run is independent
and idempotent.

Cron can drive this. Passing ``--as-of <past_date>`` gives a reproducer
of any historical state, so a forward result for a past IS date should
match that alpha's archived IS metrics exactly (modulo the daily kline
cache also covering that range).

Example:
    uv run python scripts/run_forward_tick.py \\
        --run-id run_2026_05_xs500 \\
        --alpha-id xs_volume_rank \\
        --strategy XsVolumeRankStrategy \\
        --strategy-params '{"reverse": true}' \\
        --as-of 2026-05-19

Output goes to ``archive/<run-id>/alphas/<alpha-id>/forward/`` (the same
directory the dashboard already serves). Hook seal_check is configured
to allow this path because forward/ is not OS-window data.

Past-date verification:
    --as-of 2024-04-19 should yield metrics matching the alpha's IS run.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def _splits_path(run_id: str) -> Path:
    return REPO_ROOT / "archive" / run_id / "splits.json"


def _forward_dir(run_id: str, alpha_id: str) -> Path:
    return REPO_ROOT / "archive" / run_id / "alphas" / alpha_id / "forward"


def _load_universe_and_is_start(run_id: str) -> tuple[list[str], str]:
    splits = json.loads(_splits_path(run_id).read_text())
    universe = splits["universe"]
    is_start = splits["is"]["start"]
    return universe, is_start


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--alpha-id", required=True)
    ap.add_argument("--strategy", required=True,
                    help="Strategy class name, e.g. XsVolumeRankStrategy.")
    ap.add_argument("--strategy-params", default="",
                    help="JSON dict of extra strategy kwargs.")
    ap.add_argument("--as-of", required=True,
                    help="Backtest end date (YYYY-MM-DD or full ISO). "
                         "Pass today for live forward, a past date to reproduce IS.")
    ap.add_argument("--data-path", default="data/futures_klines_daily",
                    help="Daily kline cache root.")
    ap.add_argument("--initial-capital", type=float, default=10000.0)
    ap.add_argument("--fixed-aum-sizing", action="store_true", default=True,
                    help="Default on — L/S risk eval needs fixed AUM.")
    ap.add_argument("--no-fixed-aum-sizing", dest="fixed_aum_sizing",
                    action="store_false")
    ap.add_argument("--maker-fee-rate", type=float, default=0.0002)
    ap.add_argument("--taker-fee-rate", type=float, default=0.0005)
    ap.add_argument("--sync-data", action="store_true",
                    help="Run download_daily_klines.py for the universe first "
                         "(daily cron mode). Off by default for fast reruns.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the resolved backtest command and exit.")
    args = ap.parse_args()

    universe, is_start = _load_universe_and_is_start(args.run_id)
    end_ts = args.as_of if " " in args.as_of else f"{args.as_of} 23:59"
    out_dir = _forward_dir(args.run_id, args.alpha_id)

    # Optional: refresh the daily kline cache for the universe up to as-of.
    if args.sync_data:
        sync_cmd = [
            sys.executable, "-u",
            str(REPO_ROOT / "scripts" / "tools" / "download_daily_klines.py"),
            "--start", "2026-01-01",
            "--end", args.as_of,
            "--force",
            "--symbols", *universe,
        ]
        print(f"[sync] {' '.join(sync_cmd[:6])} ... ({len(universe)} symbols)",
              flush=True)
        rc = subprocess.run(sync_cmd, cwd=REPO_ROOT).returncode
        if rc != 0:
            print(f"[sync] failed rc={rc}", file=sys.stderr)
            return rc

    # Clear stale forward artefacts so the new run is the only truth in the
    # directory. backtest.py would overwrite metrics.json anyway but the
    # warning is louder if we leave forwards mixing two as-of dates.
    if out_dir.exists() and not args.dry_run:
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, "-u",
        str(REPO_ROOT / "scripts" / "tools" / "backtest.py"),
        "--strategy", args.strategy,
        "--symbols", *universe,
        "--data-type", "bars",
        "--data-path", args.data_path,
        "--start", is_start,
        "--end", end_ts,
        "--bar-type", "TIME",
        "--bar-size", "86400",
        "--initial-capital", str(args.initial_capital),
        "--maker-fee-rate", str(args.maker_fee_rate),
        "--taker-fee-rate", str(args.taker_fee_rate),
        "--output-dir", str(out_dir),
        "--no-enforce-quality",
        "--no-enforce-governance",
        "--json",
    ]
    if args.fixed_aum_sizing:
        cmd.append("--fixed-aum-sizing")
    if args.strategy_params:
        cmd.extend(["--strategy-params", args.strategy_params])

    if args.dry_run:
        print(" ".join(cmd))
        return 0

    print(f"[forward] as_of={args.as_of}  out={out_dir}", flush=True)
    rc = subprocess.run(cmd, cwd=REPO_ROOT).returncode
    return rc


if __name__ == "__main__":
    sys.exit(main())
