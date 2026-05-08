#!/usr/bin/env python3
"""Run a JSON alpha queue through IS/OS backtests."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT"]


def _run(cmd: list[str], cwd: Path, timeout: int) -> tuple[int, dict]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return 124, {"error": f"timeout after {timeout}s", "stdout": exc.stdout, "stderr": exc.stderr}
    start = proc.stdout.find("{")
    data = {}
    if start >= 0:
        try:
            data = json.loads(proc.stdout[start:])
        except json.JSONDecodeError:
            data = {"parse_error": proc.stdout[start:]}
    if proc.returncode != 0 and not data:
        data = {"error": proc.stderr or proc.stdout}
    return proc.returncode, data


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run alpha queue")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--queue", default="")
    parser.add_argument("--splits", default="")
    parser.add_argument("--strategy", default="TradingViewOhlcvAlpha")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    parser.add_argument("--data-path", default="data/futures_klines")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--skip-existing", action="store_true", help="skip alphas with validation.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = Path.cwd()
    run_dir = Path(args.run_dir)
    queue_path = Path(args.queue) if args.queue else run_dir / "queue.json"
    splits_path = Path(args.splits) if args.splits else run_dir / "splits.json"
    log_path = run_dir / "LOG.md"

    queue = json.loads(queue_path.read_text())
    splits = json.loads(splits_path.read_text())
    variants = queue["variants"][args.start_index:]
    if args.limit > 0:
        variants = variants[: args.limit]

    run_dir.mkdir(parents=True, exist_ok=True)
    if not log_path.exists():
        log_path.write_text(f"# Alpha Queue Log\n\nrun_dir: `{run_dir}`\n\n")

    failures = 0
    for offset, variant in enumerate(variants, start=args.start_index):
        alpha_id = variant["alpha_id"]
        alpha_dir = run_dir / "alphas" / alpha_id
        if args.skip_existing and (alpha_dir / "validation.json").exists():
            print(f"[{offset + 1}] {alpha_id} skip", flush=True)
            continue
        params = dict(variant["params"])
        params["alpha_id"] = alpha_id
        print(f"[{offset + 1}] {alpha_id}", flush=True)

        split_results = {}
        for split_name in ("is", "os"):
            split = splits[split_name]
            output_dir = alpha_dir / split_name
            cmd = [
                "uv",
                "run",
                "python",
                "scripts/tools/backtest.py",
                "--strategy",
                args.strategy,
                "--symbols",
                *args.symbols,
                "--data-path",
                args.data_path,
                "--start",
                split["start"],
                "--end",
                split["end"],
                "--strategy-params",
                json.dumps(params),
                "--output-dir",
                str(output_dir),
                "--json",
            ]
            rc, data = _run(cmd, repo, args.timeout)
            split_results[split_name] = {"returncode": rc, "result": data}
            if rc != 0:
                failures += 1
                break

        validation = {}
        if split_results.get("is", {}).get("returncode") == 0 and split_results.get("os", {}).get("returncode") == 0:
            rc, validation = _run(
                [
                    "uv",
                    "run",
                    "python",
                    "scripts/tools/validate_is_os.py",
                    "--alpha-dir",
                    str(alpha_dir),
                    "--json",
                ],
                repo,
                args.timeout,
            )
            if rc != 0:
                failures += 1

        entry = {
            "alpha_id": alpha_id,
            "params": params,
            "is_metrics": split_results.get("is", {}).get("result", {}).get("metrics", {}),
            "os_metrics": split_results.get("os", {}).get("result", {}).get("metrics", {}),
            "validation": {
                "status": validation.get("status"),
                "flags": validation.get("flags", []),
            },
        }
        with log_path.open("a") as f:
            f.write(f"## {alpha_id}\n\n```json\n{json.dumps(entry, indent=2)}\n```\n\n")

    print(json.dumps({"ok": failures == 0, "failures": failures, "attempted": len(variants), "run_dir": str(run_dir)}, indent=2))
    return 0 if failures == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
