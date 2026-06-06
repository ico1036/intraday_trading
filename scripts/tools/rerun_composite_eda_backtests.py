#!/usr/bin/env python3
"""Rerun composite_eda alpha backtests and export return-only EDA inputs.

The historical ``composite_eda`` bundle stores legacy split artifacts:

    alphas/<alpha_id>/is/{equity_curve.parquet,metrics.json}
    alphas/<alpha_id>/os/{equity_curve.parquet,metrics.json}

New backtests write one artifact directory. This tool reruns the available
strategies into a clean backtest run, then exports only the split equity and
metrics needed by ``oracle_ceiling_eda.py``.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pandas as pd


REPO = Path(__file__).resolve().parents[2]
SRC_MULTI = REPO / "src" / "intraday" / "strategies" / "multi"
DEFAULT_SOURCE_RUN = "run_2026_05_full531"
DEFAULT_BACKTEST_RUN = "run_2026_05_full531_rerun_backtests"
DEFAULT_RETURN_RUN = "run_2026_05_full531_rerun_returns"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _strategy_class_for_module(module_stem: str) -> str:
    path = SRC_MULTI / f"{module_stem}.py"
    tree = ast.parse(path.read_text())
    classes: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        classes.append(node.name)
    if not classes:
        raise ValueError(f"no strategy class in {path}")
    if len(classes) > 1:
        raise ValueError(f"ambiguous strategy classes in {path}: {classes}")
    return classes[0]


def _map_alpha(alpha_id: str) -> tuple[str, dict[str, Any]]:
    """Return ``(strategy_class, strategy_params)`` for a composite alpha id."""
    exact = SRC_MULTI / f"{alpha_id}.py"
    if exact.exists():
        return _strategy_class_for_module(alpha_id), {}
    exact_strategy = SRC_MULTI / f"{alpha_id}_strategy.py"
    if exact_strategy.exists():
        return _strategy_class_for_module(f"{alpha_id}_strategy"), {}

    match = re.match(r"^(xs_factor_.+)_(fwd|rev)_c(05|10|20|30|40|50)$", alpha_id)
    if match:
        base_module = f"{match.group(1)}_fwd_c10"
        if (SRC_MULTI / f"{base_module}.py").exists():
            params = {
                "concentration_pct": int(match.group(3)) / 100.0,
                "reverse": match.group(2) == "rev",
            }
            return _strategy_class_for_module(base_module), params

    raise ValueError(f"cannot map alpha_id to strategy: {alpha_id}")


def _candidate_ids(source_run: str) -> list[str]:
    root = REPO / "composite_eda" / "data" / source_run / "alphas"
    ids = []
    for alpha_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        if (
            (alpha_dir / "is" / "equity_curve.parquet").exists()
            and (alpha_dir / "os" / "equity_curve.parquet").exists()
        ):
            ids.append(alpha_dir.name)
    return ids


def _write_splits(source_splits: dict[str, Any], run_id: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = dict(source_splits)
    payload["run_id"] = run_id
    (out_dir / "splits.json").write_text(json.dumps(payload, indent=2))


def _run_backtest(
    *,
    alpha_id: str,
    strategy_class: str,
    strategy_params: dict[str, Any],
    symbols: list[str],
    splits: dict[str, Any],
    output_dir: Path,
) -> int:
    is_start = splits["is"]["start"]
    is_end = splits["is"]["end"]
    os_end = splits["os"]["end"]
    cmd = [
        sys.executable,
        str(REPO / "scripts" / "tools" / "backtest.py"),
        "--data-type",
        "bars",
        "--strategy",
        strategy_class,
        "--symbols",
        *symbols,
        "--data-path",
        "data/futures_klines_daily",
        "--start",
        is_start,
        "--end",
        os_end,
        "--is-end",
        is_end,
        "--bar-type",
        "TIME",
        "--bar-size",
        "86400",
        "--initial-capital",
        "10000",
        "--fixed-aum-sizing",
        "--maker-fee-rate",
        "0.0002",
        "--taker-fee-rate",
        "0.0005",
        "--strategy-params",
        json.dumps(strategy_params),
        "--output-dir",
        str(output_dir),
        "--no-enforce-quality",
        "--no-enforce-governance",
        "--json",
    ]
    print(f"[backtest] {alpha_id} -> {strategy_class} {strategy_params}", flush=True)
    proc = subprocess.run(cmd, cwd=REPO, check=False, capture_output=True, text=True)
    if proc.returncode not in (0, 2):
        print(proc.stdout[-4000:], flush=True)
        print(proc.stderr[-4000:], flush=True)
    return int(proc.returncode)


def _export_return_only(src_dir: Path, dst_dir: Path, is_end: str) -> None:
    metrics = _read_json(src_dir / "metrics.json")
    equity = pd.read_parquet(src_dir / "equity_curve.parquet")
    equity["timestamp"] = pd.to_datetime(equity["timestamp"])
    cutoff = pd.Timestamp(is_end)

    is_dir = dst_dir / "is"
    os_dir = dst_dir / "os"
    is_dir.mkdir(parents=True, exist_ok=True)
    os_dir.mkdir(parents=True, exist_ok=True)

    equity[equity["timestamp"] <= cutoff].reset_index(drop=True).to_parquet(
        is_dir / "equity_curve.parquet",
        index=False,
    )
    equity[equity["timestamp"] > cutoff].reset_index(drop=True).to_parquet(
        os_dir / "equity_curve.parquet",
        index=False,
    )
    (is_dir / "metrics.json").write_text(
        json.dumps(metrics.get("is", {}), indent=2, default=str)
    )
    (os_dir / "metrics.json").write_text(
        json.dumps(metrics.get("os", {}), indent=2, default=str)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", default=DEFAULT_SOURCE_RUN)
    parser.add_argument("--backtest-run", default=DEFAULT_BACKTEST_RUN)
    parser.add_argument("--return-run", default=DEFAULT_RETURN_RUN)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--only", action="append", default=[])
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--export-only", action="store_true")
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--no-summary", action="store_true")
    args = parser.parse_args(argv)

    source_dir = REPO / "composite_eda" / "data" / args.source_run
    source_splits = _read_json(source_dir / "splits.json")
    data_root = REPO / "data" / "futures_klines_daily"
    requested_symbols = [s.upper() for s in source_splits["universe"]]
    missing_symbols = [s for s in requested_symbols if not (data_root / s).exists()]
    symbols = [s for s in requested_symbols if s not in set(missing_symbols)]
    if missing_symbols:
        print(
            f"[symbols] using {len(symbols)}/{len(requested_symbols)}; "
            f"missing local data for {missing_symbols}",
            flush=True,
        )

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

    failures: list[dict[str, Any]] = []
    for idx, alpha_id in enumerate(ids, start=1):
        try:
            strategy_class, params = _map_alpha(alpha_id)
        except Exception as exc:
            failures.append({"alpha_id": alpha_id, "stage": "map", "error": str(exc)})
            print(f"[{idx}/{len(ids)}] {alpha_id} MAP_FAIL {exc}", flush=True)
            continue

        artifact_dir = backtest_root / "alphas" / alpha_id
        if not args.export_only:
            if args.skip_existing and (artifact_dir / "metrics.json").exists():
                print(f"[{idx}/{len(ids)}] {alpha_id} skip existing", flush=True)
            else:
                rc = _run_backtest(
                    alpha_id=alpha_id,
                    strategy_class=strategy_class,
                    strategy_params=params,
                    symbols=symbols,
                    splits=source_splits,
                    output_dir=artifact_dir,
                )
                if rc not in (0, 2) or not (artifact_dir / "metrics.json").exists():
                    failures.append({"alpha_id": alpha_id, "stage": "backtest", "returncode": rc})
                    print(f"[{idx}/{len(ids)}] {alpha_id} BACKTEST_FAIL rc={rc}", flush=True)
                    continue

        try:
            _export_return_only(
                artifact_dir,
                return_root / "alphas" / alpha_id,
                source_splits["is"]["end"],
            )
        except Exception as exc:
            failures.append({"alpha_id": alpha_id, "stage": "export", "error": str(exc)})
            print(f"[{idx}/{len(ids)}] {alpha_id} EXPORT_FAIL {exc}", flush=True)
            continue
        print(f"[{idx}/{len(ids)}] {alpha_id} ok", flush=True)

    summary = {
        "source_run": args.source_run,
        "backtest_run": args.backtest_run,
        "return_run": args.return_run,
        "requested": len(ids),
        "failures": failures,
    }
    if not args.no_summary:
        (return_root / "rerun_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
