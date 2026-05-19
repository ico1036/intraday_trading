#!/usr/bin/env python3
"""Loader gateway for alpha artifacts.

Reads alpha artifacts and emits only the in-sample (IS) slice to stdout.
Out-of-sample (OS) slices and the full unsliced view require
``SEAL_OPEN=1`` in the environment — that gate is the anti-look-ahead
barrier for the research/reflect phases.

Backtests run once across the full IS+OS range and write a single set
of artifacts into ``archive/<run_id>/alphas/<alpha_id>/``. ``metrics.json``
contains ``"is"`` and ``"os"`` sub-blocks computed by
``backtest.py``'s ``_compute_split_metrics``; raw parquet artifacts
keep their timestamp column so this loader can slice them on demand.

Usage:
    uv run python scripts/tools/load_alpha.py <run_id>/<alpha_id> \\
        --kind metrics [--split is|os|full] [--field <dot.path>]

    uv run python scripts/tools/load_alpha.py <run_id>/<alpha_id> \\
        --kind equity|trades|weights [--split is|os|full] [--head N]

    uv run python scripts/tools/load_alpha.py <run_id>/<alpha_id> \\
        --kind report [--split is|os]

Exit codes:
    0 — success
    1 — usage error
    2 — sealed: requested OS/full without SEAL_OPEN=1
    3 — artifact missing
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


def _seal_blocks(split: str) -> bool:
    if split == "is":
        return False
    return os.environ.get("SEAL_OPEN") != "1"


def _alpha_dir(spec: str) -> Path:
    if "/" not in spec:
        sys.stderr.write("error: alpha must be <run_id>/<alpha_id>\n")
        sys.exit(1)
    run_id, alpha_id = spec.split("/", 1)
    root = Path(__file__).resolve().parents[2]
    return root / "archive" / run_id / "alphas" / alpha_id


def _is_end(alpha_dir: Path) -> str | None:
    m = alpha_dir / "metrics.json"
    if not m.exists():
        return None
    try:
        return json.loads(m.read_text()).get("is_end")
    except Exception:
        return None


def _emit_metrics(alpha_dir: Path, split: str, field: str | None) -> int:
    m = alpha_dir / "metrics.json"
    if not m.exists():
        sys.stderr.write(f"missing metrics.json under {alpha_dir}\n")
        return 3
    payload = json.loads(m.read_text())
    if split == "full":
        view = payload
    else:
        view = payload.get(split)
        if view is None:
            sys.stderr.write(
                f"split={split!r} not populated in metrics.json — "
                "this alpha was not run with --is-end set.\n"
            )
            return 3

    if field:
        for part in field.split("."):
            if isinstance(view, dict) and part in view:
                view = view[part]
            else:
                sys.stderr.write(f"field {field!r} not found\n")
                return 3

    print(json.dumps(view, indent=2, default=str))
    return 0


def _emit_parquet(alpha_dir: Path, kind: str, split: str, head: int | None) -> int:
    name = {"equity": "equity_curve.parquet", "trades": "trades.parquet",
            "weights": "weights.parquet"}[kind]
    p = alpha_dir / name
    if not p.exists():
        sys.stderr.write(f"missing {name} under {alpha_dir}\n")
        return 3
    try:
        import pandas as pd  # local import — keep CLI cheap when not needed
    except Exception:
        sys.stderr.write("pandas not available\n")
        return 1
    df = pd.read_parquet(p)
    is_end = _is_end(alpha_dir)
    if split != "full" and is_end and "timestamp" in df.columns:
        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        cutoff = pd.Timestamp(is_end)
        df = df[df["timestamp"] <= cutoff] if split == "is" else df[df["timestamp"] > cutoff]
    if head is not None:
        df = df.head(head)
    # Emit as JSON records — agents work in JSON, not parquet bytes.
    print(df.to_json(orient="records", date_format="iso"))
    return 0


def _emit_report(alpha_dir: Path, split: str) -> int:
    rep = alpha_dir / "backtest_report.md"
    if not rep.exists():
        sys.stderr.write(f"missing backtest_report.md under {alpha_dir}\n")
        return 3
    text = rep.read_text()
    # New format: backtest.py rewrites the report with explicit
    # `## In-Sample (IS)` and `## Out-of-Sample (OS)` headers when run
    # with --is-end. Detect those and slice; otherwise refuse for IS
    # unless SEAL_OPEN=1.
    is_marker = "## In-Sample (IS)"
    os_marker = "## Out-of-Sample (OS)"
    has_sections = is_marker in text and os_marker in text

    if split == "full":
        print(text)
        return 0

    if has_sections:
        if split == "is":
            chunk = text.split(is_marker, 1)[1].split(os_marker, 1)[0]
            print(f"{is_marker}\n{chunk}".rstrip() + "\n")
            return 0
        if split == "os":
            chunk = text.split(os_marker, 1)[1]
            print(f"{os_marker}\n{chunk}".rstrip() + "\n")
            return 0

    if split == "is" and os.environ.get("SEAL_OPEN") != "1":
        sys.stderr.write(
            "backtest_report.md has no IS/OS sections (legacy or full-period "
            "run). SEAL_OPEN=1 required, or use --kind metrics --split is.\n"
        )
        return 2
    print(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read alpha artifacts with IS/OS gating."
    )
    parser.add_argument("alpha", help="<run_id>/<alpha_id>")
    parser.add_argument(
        "--kind", required=True,
        choices=["metrics", "equity", "trades", "weights", "report"],
    )
    parser.add_argument("--split", default="is", choices=["is", "os", "full"])
    parser.add_argument("--field", default=None, help="dot-path inside metrics JSON")
    parser.add_argument("--head", type=int, default=None,
                        help="emit only the first N rows of a parquet kind")
    args = parser.parse_args(argv)

    if _seal_blocks(args.split):
        sys.stderr.write(
            f"SEALED: split={args.split!r} requires SEAL_OPEN=1 in env. "
            "OS / full-period artifacts are hidden during research/reflect.\n"
        )
        return 2

    alpha_dir = _alpha_dir(args.alpha)
    if not alpha_dir.exists():
        sys.stderr.write(f"alpha dir not found: {alpha_dir}\n")
        return 3

    if args.kind == "metrics":
        return _emit_metrics(alpha_dir, args.split, args.field)
    if args.kind in {"equity", "trades", "weights"}:
        return _emit_parquet(alpha_dir, args.kind, args.split, args.head)
    if args.kind == "report":
        return _emit_report(alpha_dir, args.split)
    return 1


if __name__ == "__main__":
    sys.exit(main())
