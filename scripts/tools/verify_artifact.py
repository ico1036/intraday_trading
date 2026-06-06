#!/usr/bin/env python3
"""Verify a saved alpha artifact directory and emit JSON."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd


REQUIRED_FILES = {
    "weights.parquet",
    "metrics.json",
    "equity_curve.parquet",
    "trades.parquet",
    "strategy_source.py",
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

METRIC_KEYS = {
    "profit_factor",
    "total_return",
    "max_drawdown",
    "total_trades",
    "win_rate",
    "sharpe",
    "strategy_class",
    "strategy_source",
}


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def verify_artifact(artifact_dir: Path) -> dict[str, Any]:
    artifact_dir = Path(artifact_dir)
    errors: list[str] = []
    warnings: list[str] = []

    if not artifact_dir.exists():
        return {
            "ok": False,
            "artifact_dir": str(artifact_dir),
            "errors": [f"artifact_dir not found: {artifact_dir}"],
            "warnings": [],
        }

    missing = sorted(name for name in REQUIRED_FILES if not (artifact_dir / name).exists())
    if missing:
        errors.append(f"missing required files: {missing}")

    metrics: dict[str, Any] = {}
    metrics_path = artifact_dir / "metrics.json"
    if metrics_path.exists():
        try:
            metrics = json.loads(metrics_path.read_text())
            missing_metrics = sorted(METRIC_KEYS - set(metrics))
            if missing_metrics:
                errors.append(f"metrics.json missing keys: {missing_metrics}")
        except Exception as exc:
            errors.append(f"metrics.json unreadable: {exc}")

    weights_rows = 0
    weights_path = artifact_dir / "weights.parquet"
    if weights_path.exists():
        try:
            weights = pd.read_parquet(weights_path)
            weights_rows = int(len(weights))
            missing_columns = sorted(WEIGHT_COLUMNS - set(weights.columns))
            if missing_columns:
                errors.append(f"weights.parquet missing columns: {missing_columns}")
            if "target_weight" in weights.columns and not weights.empty:
                finite = weights["target_weight"].map(
                    lambda x: isinstance(x, (int, float)) and math.isfinite(float(x))
                )
                if not bool(finite.all()):
                    errors.append("weights.parquet has non-finite target_weight")
            if weights.empty:
                warnings.append("weights.parquet is empty")
        except Exception as exc:
            errors.append(f"weights.parquet unreadable: {exc}")

    for parquet_name in ("equity_curve.parquet", "trades.parquet"):
        path = artifact_dir / parquet_name
        if not path.exists():
            continue
        try:
            pd.read_parquet(path)
        except Exception as exc:
            errors.append(f"{parquet_name} unreadable: {exc}")

    return {
        "ok": not errors,
        "artifact_dir": str(artifact_dir),
        "errors": errors,
        "warnings": warnings,
        "weights_rows": weights_rows,
        "metrics": metrics,
        "files": {name: str(artifact_dir / name) for name in sorted(REQUIRED_FILES)},
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify alpha artifact directory")
    parser.add_argument("artifact_dir")
    parser.add_argument("--json", action="store_true", help="emit JSON only")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = verify_artifact(Path(args.artifact_dir))
    print(json.dumps(result, indent=2, default=_json_default))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
