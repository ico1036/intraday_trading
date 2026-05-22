#!/usr/bin/env python3
"""Split flat-layout alpha artifacts into ``is/`` / ``os/`` subdirs.

The batch backtester (``scripts/run_batch_backtests.py``) writes each
alpha's artifacts flat under ``archive/<run>/alphas/<alpha>/`` with
metrics.json containing ``"is"`` and ``"os"`` sub-blocks and the parquet
files spanning the full IS+OS range.

The composite runner (``src/intraday/composites/_runner.py``) reads each
member's per-split ``is/weights.parquet`` and ``os/weights.parquet``.
This script bridges the two: for each alpha dir found under a run, slice
the flat parquets on the IS-end timestamp and rewrite them into
``is/`` / ``os/`` subfolders, plus split metrics.json into
``is/metrics.json`` and ``os/metrics.json``.

Idempotent: skips an alpha that already has both ``is/metrics.json`` and
``os/metrics.json``. Use ``--force`` to re-split.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd


REPO = Path(__file__).resolve().parents[2]


def _slice_parquet(src: Path, dst_is: Path, dst_os: Path, cutoff: pd.Timestamp) -> None:
    if not src.exists():
        return
    df = pd.read_parquet(src)
    if "timestamp" not in df.columns:
        return
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    is_df = df[df["timestamp"] <= cutoff].reset_index(drop=True)
    os_df = df[df["timestamp"] > cutoff].reset_index(drop=True)
    dst_is.parent.mkdir(parents=True, exist_ok=True)
    dst_os.parent.mkdir(parents=True, exist_ok=True)
    is_df.to_parquet(dst_is, index=False)
    os_df.to_parquet(dst_os, index=False)


def _split_metrics(src: Path, dst_is: Path, dst_os: Path) -> None:
    if not src.exists():
        return
    m = json.loads(src.read_text())
    is_block = m.get("is")
    os_block = m.get("os")
    if not isinstance(is_block, dict) or not isinstance(os_block, dict):
        # Flat metrics without sub-blocks — keep top-level as IS (heuristic),
        # leave OS empty. Caller can re-run with explicit metrics if needed.
        is_block = {k: v for k, v in m.items() if k not in ("is", "os")}
        os_block = {}
    dst_is.parent.mkdir(parents=True, exist_ok=True)
    dst_os.parent.mkdir(parents=True, exist_ok=True)
    dst_is.write_text(json.dumps(is_block, indent=2, default=str))
    dst_os.write_text(json.dumps(os_block, indent=2, default=str))


def _split_one(alpha_dir: Path, is_cutoff: pd.Timestamp, force: bool = False) -> str:
    is_dir = alpha_dir / "is"
    os_dir = alpha_dir / "os"
    if (
        not force
        and (is_dir / "metrics.json").exists()
        and (os_dir / "metrics.json").exists()
    ):
        return "skip"
    if not (alpha_dir / "metrics.json").exists():
        return "no_metrics"
    _split_metrics(alpha_dir / "metrics.json",
                   is_dir / "metrics.json", os_dir / "metrics.json")
    for name in ("weights.parquet", "equity_curve.parquet",
                 "trades.parquet", "events.parquet"):
        _slice_parquet(alpha_dir / name, is_dir / name, os_dir / name, is_cutoff)
    # Copy manifest verbatim for both splits — the canonical record is the
    # flat one. We just make a thin pointer.
    mf = alpha_dir / "manifest.json"
    if mf.exists():
        (is_dir / "manifest.json").write_text(mf.read_text())
        (os_dir / "manifest.json").write_text(mf.read_text())
    return "ok"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    run_dir = REPO / "archive" / args.run_id
    splits = json.loads((run_dir / "splits.json").read_text())
    cutoff = pd.Timestamp(splits["is"]["end"])
    alphas_root = run_dir / "alphas"

    if not alphas_root.exists():
        print(f"no alphas dir under {run_dir}", file=sys.stderr)
        return 1

    counts = {"ok": 0, "skip": 0, "no_metrics": 0}
    for d in sorted(alphas_root.iterdir()):
        if not d.is_dir():
            continue
        r = _split_one(d, cutoff, force=args.force)
        counts[r] = counts.get(r, 0) + 1

    print(f"split flat→is/os under {run_dir}: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
