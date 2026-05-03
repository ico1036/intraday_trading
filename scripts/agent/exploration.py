#!/usr/bin/env python3
"""Coverage utilities for markdown-driven alpha exploration.

This module is intentionally not an orchestrator loop. It only initializes a
run directory, proposes underexplored cells, and records completed alpha
artifacts.
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd


SEARCH_SPACE: dict[str, list[str]] = {
    "bar_domain": ["TIME", "VOLUME", "DOLLAR", "TICK"],
    "signal_family": [
        "momentum",
        "reversal",
        "volatility",
        "volume_pressure",
        "dispersion",
        "correlation_break",
        "lead_lag",
        "funding",
        "regime_transition",
    ],
    "feature_set": [
        "return",
        "vwap_gap",
        "volume_imbalance",
        "range_expansion",
        "realized_vol",
        "cross_rank",
        "pair_spread",
        "trend_state",
    ],
    "normalization": ["raw", "z_score", "percentile", "rolling_rank", "ewma_residual"],
    "horizon": ["ultra_short", "intraday", "session", "multi_day"],
    "entry_logic": [
        "threshold",
        "rank_top_bottom",
        "breakout",
        "mean_reversion",
        "state_transition",
    ],
    "exit_logic": ["time_stop", "signal_flip", "trailing", "vol_stop", "neutral_zone"],
    "sizing": ["fixed", "equal_weight", "inverse_vol", "confidence_scaled"],
    "universe": ["single", "pair", "basket_topk"],
}

CORE_ARTIFACTS = {
    "manifest.json",
    "weights.parquet",
    "metrics.json",
    "summary.json",
    "summary.csv",
    "equity_curve.parquet",
    "trades.parquet",
    "events.parquet",
    "backtest_report.md",
}

WEIGHT_COLUMNS = {
    "timestamp",
    "alpha_id",
    "symbol",
    "target_weight",
    "target_notional",
    "target_qty",
    "price",
    "bar_type",
    "bar_size",
    "metadata",
}


class ExplorationError(RuntimeError):
    """Raised when exploration state or artifacts are invalid."""


def _coverage_path(run_dir: Path) -> Path:
    return run_dir / "coverage_map.json"


def _index_path(run_dir: Path) -> Path:
    return run_dir / "alpha_index.csv"


def _default_coverage() -> dict[str, Any]:
    return {
        "version": 1,
        "search_space": SEARCH_SPACE,
        "visited_cells": [],
        "axis_counts": {axis: {value: 0 for value in values} for axis, values in SEARCH_SPACE.items()},
        "combo_counts": {},
    }


def init_run(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "alphas").mkdir(exist_ok=True)
    cov = _coverage_path(run_dir)
    if not cov.exists():
        cov.write_text(json.dumps(_default_coverage(), indent=2))
    idx = _index_path(run_dir)
    if not idx.exists():
        with idx.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "alpha_id",
                    "artifact_dir",
                    "valid",
                    "total_return",
                    "profit_factor",
                    "max_drawdown",
                    "total_trades",
                    "win_rate",
                    "sharpe",
                    "search_cell",
                ]
            )


def load_coverage(run_dir: Path) -> dict[str, Any]:
    path = _coverage_path(run_dir)
    if not path.exists():
        return _default_coverage()
    return json.loads(path.read_text())


def validate_search_cell(cell: dict[str, Any]) -> dict[str, str]:
    missing = [axis for axis in SEARCH_SPACE if axis not in cell]
    if missing:
        raise ExplorationError(f"search_cell missing axes: {missing}")

    normalized: dict[str, str] = {}
    for axis, values in SEARCH_SPACE.items():
        value = str(cell[axis])
        if value not in values:
            raise ExplorationError(f"invalid {axis}={value!r}; expected one of {values}")
        normalized[axis] = value
    return normalized


def _combo_key(cell: dict[str, str]) -> str:
    axes = ("signal_family", "feature_set", "normalization", "horizon", "universe")
    return "|".join(f"{axis}={cell[axis]}" for axis in axes)


def _cell_tuple(cell: dict[str, str]) -> tuple[str, ...]:
    return tuple(cell[axis] for axis in SEARCH_SPACE)


def _iter_candidate_cells() -> list[dict[str, str]]:
    axes = list(SEARCH_SPACE)
    product = itertools.product(*(SEARCH_SPACE[axis] for axis in axes))
    return [dict(zip(axes, values, strict=True)) for values in product]


def next_cells(run_dir: Path, limit: int = 10) -> list[dict[str, str]]:
    coverage = load_coverage(run_dir)
    visited = {
        _cell_tuple(validate_search_cell(cell["cell"]))
        for cell in coverage.get("visited_cells", [])
        if isinstance(cell, dict) and isinstance(cell.get("cell"), dict)
    }
    combo_counts = Counter(coverage.get("combo_counts", {}))
    axis_counts_raw = coverage.get("axis_counts", {})

    def score(cell: dict[str, str]) -> tuple[int, int, tuple[int, ...], tuple[str, ...]]:
        direct_seen = 1 if _cell_tuple(cell) in visited else 0
        combo_seen = int(combo_counts.get(_combo_key(cell), 0))
        axis_counts = tuple(
            int(axis_counts_raw.get(axis, {}).get(cell[axis], 0))
            for axis in SEARCH_SPACE
        )
        return (direct_seen, combo_seen, axis_counts, _cell_tuple(cell))

    ranked = sorted(_iter_candidate_cells(), key=score)
    return ranked[:limit]


def _validate_artifacts(alpha_dir: Path) -> tuple[bool, dict[str, Any]]:
    missing = sorted(name for name in CORE_ARTIFACTS if not (alpha_dir / name).exists())
    if missing:
        return False, {"missing": missing}

    weights = pd.read_parquet(alpha_dir / "weights.parquet")
    missing_cols = sorted(WEIGHT_COLUMNS - set(weights.columns))
    if missing_cols:
        return False, {"missing_weight_columns": missing_cols}

    if not weights.empty:
        finite = weights["target_weight"].map(lambda x: isinstance(x, (int, float)) and math.isfinite(float(x)))
        if not bool(finite.all()):
            return False, {"invalid_target_weight": True}

    return True, {"weight_rows": int(len(weights))}


def _read_metrics(alpha_dir: Path) -> dict[str, Any]:
    path = alpha_dir / "metrics.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def record_alpha(run_dir: Path, alpha_id: str) -> dict[str, Any]:
    init_run(run_dir)
    alpha_dir = run_dir / "alphas" / alpha_id
    cell_path = alpha_dir / "search_cell.json"
    if not cell_path.exists():
        raise ExplorationError(f"missing {cell_path}")

    cell = validate_search_cell(json.loads(cell_path.read_text()))
    valid, evidence = _validate_artifacts(alpha_dir)
    metrics = _read_metrics(alpha_dir)

    coverage = load_coverage(run_dir)
    entry = {
        "alpha_id": alpha_id,
        "artifact_dir": str(alpha_dir),
        "valid": valid,
        "cell": cell,
        "evidence": evidence,
    }

    existing = [e for e in coverage.get("visited_cells", []) if e.get("alpha_id") != alpha_id]
    existing.append(entry)
    coverage["visited_cells"] = existing

    axis_counts = {axis: {value: 0 for value in values} for axis, values in SEARCH_SPACE.items()}
    combo_counts: Counter[str] = Counter()
    for e in existing:
        if not e.get("valid"):
            continue
        e_cell = validate_search_cell(e["cell"])
        for axis, value in e_cell.items():
            axis_counts[axis][value] += 1
        combo_counts[_combo_key(e_cell)] += 1

    coverage["axis_counts"] = axis_counts
    coverage["combo_counts"] = dict(sorted(combo_counts.items()))
    _coverage_path(run_dir).write_text(json.dumps(coverage, indent=2))

    _rewrite_index(run_dir, coverage, metrics_by_alpha={alpha_id: metrics})
    return entry


def _rewrite_index(
    run_dir: Path,
    coverage: dict[str, Any],
    metrics_by_alpha: dict[str, dict[str, Any]] | None = None,
) -> None:
    metrics_by_alpha = metrics_by_alpha or {}
    rows = []
    for entry in sorted(coverage.get("visited_cells", []), key=lambda e: e.get("alpha_id", "")):
        alpha_id = entry["alpha_id"]
        alpha_dir = Path(entry["artifact_dir"])
        metrics = metrics_by_alpha.get(alpha_id) or _read_metrics(alpha_dir)
        rows.append(
            {
                "alpha_id": alpha_id,
                "artifact_dir": str(alpha_dir),
                "valid": entry.get("valid", False),
                "total_return": metrics.get("total_return", ""),
                "profit_factor": metrics.get("profit_factor", ""),
                "max_drawdown": metrics.get("max_drawdown", ""),
                "total_trades": metrics.get("total_trades", ""),
                "win_rate": metrics.get("win_rate", ""),
                "sharpe": metrics.get("sharpe", metrics.get("sharpe_ratio", "")),
                "search_cell": json.dumps(entry.get("cell", {}), sort_keys=True),
            }
        )

    with _index_path(run_dir).open("w", newline="") as f:
        fieldnames = [
            "alpha_id",
            "artifact_dir",
            "valid",
            "total_return",
            "profit_factor",
            "max_drawdown",
            "total_trades",
            "win_rate",
            "sharpe",
            "search_cell",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _cmd_init(args: argparse.Namespace) -> int:
    init_run(Path(args.run_dir))
    return 0


def _cmd_next_cells(args: argparse.Namespace) -> int:
    cells = next_cells(Path(args.run_dir), limit=args.limit)
    print(json.dumps(cells, indent=2))
    return 0


def _cmd_record(args: argparse.Namespace) -> int:
    entry = record_alpha(Path(args.run_dir), args.alpha_id)
    print(json.dumps(entry, indent=2))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Alpha exploration coverage utility")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="initialize a markdown exploration run")
    p_init.add_argument("run_dir")
    p_init.set_defaults(func=_cmd_init)

    p_next = sub.add_parser("next-cells", help="print underexplored search cells")
    p_next.add_argument("run_dir")
    p_next.add_argument("--limit", type=int, default=10)
    p_next.set_defaults(func=_cmd_next_cells)

    p_record = sub.add_parser("record", help="record one completed alpha artifact")
    p_record.add_argument("run_dir")
    p_record.add_argument("alpha_id")
    p_record.set_defaults(func=_cmd_record)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return int(args.func(args))
    except ExplorationError as exc:
        print(f"error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
