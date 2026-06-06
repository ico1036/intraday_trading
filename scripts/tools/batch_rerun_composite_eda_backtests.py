#!/usr/bin/env python3
"""Run composite EDA alpha backtests in a resource-aware parallel batch."""
from __future__ import annotations

import argparse
import concurrent.futures as futures
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import psutil

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tools.rerun_composite_eda_backtests import (
    DEFAULT_BACKTEST_RUN,
    DEFAULT_RETURN_RUN,
    DEFAULT_SOURCE_RUN,
    REPO,
    _candidate_ids,
    _read_json,
    _write_splits,
)


def _auto_workers() -> int:
    cpu_workers = max(1, (os.cpu_count() or 2) - 2)
    available_gb = psutil.virtual_memory().available / 1024**3
    memory_workers = max(1, int(available_gb // 2.5))
    return max(1, min(cpu_workers, memory_workers, 4))


def _run_one(args: argparse.Namespace, alpha_id: str) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(REPO / "scripts" / "tools" / "rerun_composite_eda_backtests.py"),
        "--source-run",
        args.source_run,
        "--backtest-run",
        args.backtest_run,
        "--return-run",
        args.return_run,
        "--only",
        alpha_id,
        "--skip-existing",
        "--no-summary",
    ]
    if args.export_only:
        cmd.append("--export-only")

    started = time.monotonic()
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, check=False)
    elapsed = time.monotonic() - started
    return {
        "alpha_id": alpha_id,
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "elapsed_sec": elapsed,
        "stdout_tail": proc.stdout[-3000:],
        "stderr_tail": proc.stderr[-3000:],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", default=DEFAULT_SOURCE_RUN)
    parser.add_argument("--backtest-run", default=DEFAULT_BACKTEST_RUN)
    parser.add_argument("--return-run", default=DEFAULT_RETURN_RUN)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--only", action="append", default=[])
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--export-only", action="store_true")
    args = parser.parse_args(argv)

    workers = args.workers if args.workers > 0 else _auto_workers()
    workers = max(1, workers)

    source_dir = REPO / "composite_eda" / "data" / args.source_run
    source_splits = _read_json(source_dir / "splits.json")
    backtest_root = REPO / "archive" / args.backtest_run
    return_root = REPO / "archive" / args.return_run

    if args.clean:
        shutil.rmtree(backtest_root, ignore_errors=True)
        shutil.rmtree(return_root, ignore_errors=True)
    _write_splits(source_splits, args.backtest_run, backtest_root)
    _write_splits(source_splits, args.return_run, return_root)

    ids = args.only or _candidate_ids(args.source_run)
    if args.limit > 0:
        ids = ids[: args.limit]

    print(
        json.dumps(
            {
                "source_run": args.source_run,
                "backtest_run": args.backtest_run,
                "return_run": args.return_run,
                "requested": len(ids),
                "workers": workers,
                "cpu_count": os.cpu_count(),
                "available_memory_gb": round(psutil.virtual_memory().available / 1024**3, 2),
            },
            indent=2,
        ),
        flush=True,
    )

    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    started = time.monotonic()
    with futures.ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_alpha = {executor.submit(_run_one, args, alpha_id): alpha_id for alpha_id in ids}
        for idx, future in enumerate(futures.as_completed(future_to_alpha), start=1):
            alpha_id = future_to_alpha[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {
                    "alpha_id": alpha_id,
                    "ok": False,
                    "returncode": None,
                    "elapsed_sec": None,
                    "error": str(exc),
                }
            results.append(result)
            if not result["ok"]:
                failures.append(result)
            status = "ok" if result["ok"] else "FAIL"
            elapsed = result.get("elapsed_sec")
            elapsed_text = f"{elapsed:.1f}s" if isinstance(elapsed, float) else "n/a"
            print(f"[{idx}/{len(ids)}] {alpha_id} {status} {elapsed_text}", flush=True)
            if not result["ok"]:
                print(result.get("stdout_tail", ""), flush=True)
                print(result.get("stderr_tail", ""), flush=True)

    summary = {
        "source_run": args.source_run,
        "backtest_run": args.backtest_run,
        "return_run": args.return_run,
        "requested": len(ids),
        "workers": workers,
        "elapsed_sec": time.monotonic() - started,
        "failures": failures,
        "results": results,
    }
    return_root.mkdir(parents=True, exist_ok=True)
    (return_root / "batch_rerun_summary.json").write_text(json.dumps(summary, indent=2))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
