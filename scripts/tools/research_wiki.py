#!/usr/bin/env python3
"""Manage the lightweight research wiki and loop harness metadata.

This tool keeps the alpha research memory small and explicit:

- initialize a run goal + harness version record,
- freeze the wiki memory visible at run start,
- create post-analysis templates after backtests,
- upsert compact alpha-memory rows,
- summarize harness versions across completed runs.

The wiki is a retrieval index, not a winner recommender.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.governance.check import _parse_module_constants


ARCHIVE = REPO / "archive"
WIKI = REPO / "research" / "wiki"
ALPHA_MEMORY = WIKI / "alpha_memory.jsonl"
FAMILY_MEMORY = WIKI / "family_memory.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def _ensure_wiki() -> None:
    for path in (
        WIKI,
        WIKI / "goals",
        WIKI / "reflections",
        WIKI / "post_analysis",
        WIKI / "snapshots",
    ):
        path.mkdir(parents=True, exist_ok=True)
    ALPHA_MEMORY.touch(exist_ok=True)
    FAMILY_MEMORY.touch(exist_ok=True)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    text = "".join(json.dumps(row, default=_json_default, sort_keys=True) + "\n" for row in rows)
    path.write_text(text)


def _git_head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        ).stdout.strip()
    except Exception:
        return ""


def _alpha_dir(run_id: str, alpha_id: str) -> Path:
    return ARCHIVE / run_id / "alphas" / alpha_id


def _metrics_for_alpha(alpha_dir: Path) -> dict[str, Any]:
    metrics = _read_json(alpha_dir / "metrics.json")
    if "is" in metrics and isinstance(metrics["is"], dict):
        is_metrics = dict(metrics["is"])
        is_metrics.setdefault("full_total_return", metrics.get("total_return"))
        return is_metrics
    return metrics


def _strategy_source_path(alpha_dir: Path) -> Path | None:
    metrics = _read_json(alpha_dir / "metrics.json")
    snap = alpha_dir / "strategy_source.py"
    if snap.exists():
        return snap
    src = metrics.get("source_original_path")
    if src and Path(src).exists():
        return Path(src)
    return None


def _alpha_cell_and_notes(alpha_dir: Path) -> tuple[dict[str, Any], list[str]]:
    src = _strategy_source_path(alpha_dir)
    if src is None:
        return {}, []
    consts = _parse_module_constants(src)
    if consts is None:
        return {}, []
    return dict(consts.get("alpha_cell") or {}), list(consts.get("source_notes") or [])


def _status_from_metrics(metrics: dict[str, Any], splits: dict[str, Any]) -> str:
    gates = splits.get("quality_gates") or {}
    target = (splits.get("target") or {}).get("threshold")
    if target is None:
        target = gates.get("min_sharpe", 0.0)
    try:
        if metrics.get("sharpe") is not None and float(metrics["sharpe"]) < float(target):
            return "IS_FAIL"
    except Exception:
        pass
    min_trades = gates.get("min_trades")
    if min_trades is not None:
        try:
            if int(metrics.get("total_trades") or 0) < int(min_trades):
                return "IS_FAIL"
        except Exception:
            pass
    return "IS_PASS" if metrics else "UNKNOWN"


def _family_entropy(families: list[str]) -> float:
    if not families:
        return 0.0
    counts = Counter(families)
    total = sum(counts.values())
    return float(-sum((n / total) * math.log(n / total, 2) for n in counts.values()))


def init_run(args: argparse.Namespace) -> int:
    _ensure_wiki()
    run_dir = ARCHIVE / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    harness = {
        "harness_id": args.harness_id,
        "harness_version": args.harness_version,
        "wiki_schema_version": args.wiki_schema_version,
        "prompt_version": args.prompt_version,
        "selection_policy": args.selection_policy,
        "model": args.model,
        "temperature": args.temperature,
        "attempt_budget": args.attempt_budget,
        "data_cutoff": args.data_cutoff,
        "run_id": args.run_id,
        "goal_path": str(WIKI / "goals" / f"{args.run_id}.md"),
        "reflection_path": str(WIKI / "reflections" / f"{args.run_id}.md"),
        "memory_snapshot": str(WIKI / "snapshots" / f"{args.run_id}_start_alpha_memory.jsonl"),
        "git_head": _git_head(),
        "created_at": _now(),
    }
    (run_dir / "harness.json").write_text(json.dumps(harness, indent=2, default=_json_default))

    goal_path = WIKI / "goals" / f"{args.run_id}.md"
    if not goal_path.exists() or args.overwrite:
        goal_path.write_text(
            f"# Goal: {args.run_id}\n\n"
            "## User Goal\n"
            f"{args.goal.strip()}\n\n"
            "## Constraints\n"
            "- IS only for development.\n"
            "- OS/full-period artifacts are sealed unless explicitly opened.\n"
            "- Use target weights and preserve artifact contracts.\n"
            "- Prefix-invariance is a hard backtest gate.\n"
            "- Do not clone prior winners; use memory at mechanism level.\n"
        )

    reflection_path = WIKI / "reflections" / f"{args.run_id}.md"
    if not reflection_path.exists() or args.overwrite:
        reflection_path.write_text(
            f"# Reflection: {args.run_id}\n\n"
            "## Goal Summary\n"
            "TBD by the loop agent after reading the goal and wiki snapshot.\n\n"
            "## Relevant Prior Memory\n"
            "TBD. Read only relevant `alpha_memory.jsonl` rows and linked post-analysis files.\n\n"
            "## Soft Plan\n"
            "TBD. This should guide mechanism-level exploration, not clone prior winners.\n\n"
            "## Anti-Local-Max Guard\n"
            "Do not clone prior winners. Use prior memory only at mechanism level and keep coverage pressure.\n"
        )

    snapshot = WIKI / "snapshots" / f"{args.run_id}_start_alpha_memory.jsonl"
    if not snapshot.exists() or args.overwrite:
        shutil.copy2(ALPHA_MEMORY, snapshot)

    print(json.dumps({"ok": True, "harness": harness}, indent=2, default=_json_default))
    return 0


def post_analysis_template(args: argparse.Namespace) -> int:
    _ensure_wiki()
    alpha_dir = _alpha_dir(args.run_id, args.alpha_id)
    if not alpha_dir.exists():
        raise FileNotFoundError(f"alpha dir not found: {alpha_dir}")
    metrics = _metrics_for_alpha(alpha_dir)
    cell, notes = _alpha_cell_and_notes(alpha_dir)
    out_dir = WIKI / "post_analysis" / args.run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.alpha_id}.md"
    if out_path.exists() and not args.overwrite:
        print(json.dumps({"ok": True, "path": str(out_path), "exists": True}, indent=2))
        return 0
    text = (
        f"# Post Analysis: {args.alpha_id}\n\n"
        f"- run_id: `{args.run_id}`\n"
        f"- alpha_id: `{args.alpha_id}`\n"
        f"- artifact_dir: `{alpha_dir}`\n"
        f"- source_notes: `{notes}`\n"
        f"- alpha_cell: `{json.dumps(cell, sort_keys=True)}`\n\n"
        "## Implemented Strategy\n"
        "Describe what the checked-in code actually does: signal, filters, long/short construction, rebalance, exits.\n\n"
        "## IS Performance State\n"
        f"- IS Sharpe: `{metrics.get('sharpe')}`\n"
        f"- IS Return: `{metrics.get('total_return')}`\n"
        f"- IS Max Drawdown: `{metrics.get('max_drawdown')}`\n"
        f"- IS Trades: `{metrics.get('total_trades')}`\n\n"
        "Explain the IS equity/PnL state without calling the strategy good or bad just because of one number.\n\n"
        "## Goal Fit\n"
        "Explain how this implementation fits the run goal and where it does not.\n\n"
        "## Current Interpretation\n"
        "Explain the current state of the strategy based on code plus IS results. Keep the scope specific.\n\n"
        "## Reuse Notes\n"
        "Short notes for future loops. Avoid best-parameter recommendations and winner-cloning language.\n"
    )
    out_path.write_text(text)
    print(json.dumps({"ok": True, "path": str(out_path)}, indent=2))
    return 0


def upsert_alpha_memory(args: argparse.Namespace) -> int:
    _ensure_wiki()
    alpha_dir = _alpha_dir(args.run_id, args.alpha_id)
    if not alpha_dir.exists():
        raise FileNotFoundError(f"alpha dir not found: {alpha_dir}")
    splits = _read_json(ARCHIVE / args.run_id / "splits.json")
    metrics = _metrics_for_alpha(alpha_dir)
    cell, notes = _alpha_cell_and_notes(alpha_dir)
    family = str(cell.get("idea_family") or args.family or "unknown")
    post = args.post_analysis or str(WIKI / "post_analysis" / args.run_id / f"{args.alpha_id}.md")
    row = {
        "run_id": args.run_id,
        "alpha_id": args.alpha_id,
        "family": family,
        "cell": cell,
        "source_notes": notes,
        "status": args.status or _status_from_metrics(metrics, splits),
        "is_sharpe": metrics.get("sharpe"),
        "is_return": metrics.get("total_return"),
        "is_drawdown": metrics.get("max_drawdown"),
        "is_trades": metrics.get("total_trades"),
        "turnover": metrics.get("turnover"),
        "goal_fit": args.goal_fit,
        "one_line": args.one_line,
        "post_analysis": post,
        "artifact_dir": str(alpha_dir),
        "created_at": _now(),
    }
    rows = _read_jsonl(ALPHA_MEMORY)
    rows = [r for r in rows if not (r.get("run_id") == args.run_id and r.get("alpha_id") == args.alpha_id)]
    rows.append(row)
    _write_jsonl(ALPHA_MEMORY, rows)
    _rewrite_family_memory(rows)
    print(json.dumps({"ok": True, "row": row}, indent=2, default=_json_default))
    return 0


def _rewrite_family_memory(alpha_rows: list[dict[str, Any]]) -> None:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in alpha_rows:
        grouped[str(row.get("family") or "unknown")].append(row)
    family_rows = []
    for family, rows in sorted(grouped.items()):
        statuses = Counter(str(r.get("status") or "UNKNOWN") for r in rows)
        recent = sorted({str(r.get("run_id")) for r in rows if r.get("run_id")})[-5:]
        cells = [json.dumps(r.get("cell") or {}, sort_keys=True) for r in rows]
        family_rows.append(
            {
                "family": family,
                "attempts": len(rows),
                "passes": statuses.get("IS_PASS", 0) + statuses.get("SUBMITTABLE", 0),
                "fails": statuses.get("IS_FAIL", 0) + statuses.get("REJECT", 0),
                "recent_runs": recent,
                "unique_cells": len(set(cells)),
                "saturation_note": "Do not clone prior winners; change mechanism-level context before revisiting.",
                "updated_at": _now(),
            }
        )
    _write_jsonl(FAMILY_MEMORY, family_rows)


def evaluate_harness(args: argparse.Namespace) -> int:
    _ensure_wiki()
    rows = []
    for run_arg in args.run_id:
        run_dir = ARCHIVE / run_arg
        harness = _read_json(run_dir / "harness.json")
        splits = _read_json(run_dir / "splits.json")
        alphas_dir = run_dir / "alphas"
        alpha_dirs = [p for p in sorted(alphas_dir.iterdir()) if p.is_dir()] if alphas_dir.exists() else []
        families: list[str] = []
        cells: list[str] = []
        pass_count = 0
        valid_count = 0
        sharpe_values: list[float] = []
        for alpha_dir in alpha_dirs:
            metrics = _metrics_for_alpha(alpha_dir)
            if metrics:
                valid_count += 1
            status = _status_from_metrics(metrics, splits)
            if status == "IS_PASS":
                pass_count += 1
            try:
                if metrics.get("sharpe") is not None:
                    sharpe_values.append(float(metrics["sharpe"]))
            except Exception:
                pass
            cell, _notes = _alpha_cell_and_notes(alpha_dir)
            family = str(cell.get("idea_family") or "unknown")
            families.append(family)
            cells.append(json.dumps(cell, sort_keys=True))
        rows.append(
            {
                "run_id": run_arg,
                "harness_id": harness.get("harness_id", "unknown"),
                "harness_version": harness.get("harness_version"),
                "attempt_budget": harness.get("attempt_budget"),
                "attempts": len(alpha_dirs),
                "valid_artifact_count": valid_count,
                "is_pass_count": pass_count,
                "is_pass_rate": pass_count / len(alpha_dirs) if alpha_dirs else 0.0,
                "unique_family_count": len(set(families)),
                "unique_cell_count": len(set(cells)),
                "family_entropy": _family_entropy(families),
                "median_is_sharpe": sorted(sharpe_values)[len(sharpe_values) // 2] if sharpe_values else None,
            }
        )
    out = {"ok": True, "generated_at": _now(), "runs": rows}
    if args.output:
        Path(args.output).write_text(json.dumps(out, indent=2, default=_json_default))
    print(json.dumps(out, indent=2, default=_json_default))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init-run", help="create run harness metadata and wiki goal files")
    p.add_argument("--run-id", required=True)
    p.add_argument("--goal", required=True)
    p.add_argument("--harness-id", default="loop_v1_post_analysis_wiki")
    p.add_argument("--harness-version", default="1")
    p.add_argument("--wiki-schema-version", default="2026-06-06.1")
    p.add_argument("--prompt-version", default="goal_reflection_v1")
    p.add_argument("--selection-policy", default="coverage_first_soft_reflection")
    p.add_argument("--model", default="")
    p.add_argument("--temperature", type=float, default=None)
    p.add_argument("--attempt-budget", type=int, default=None)
    p.add_argument("--data-cutoff", default="")
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(func=init_run)

    p = sub.add_parser("post-template", help="write a post-analysis template for an alpha")
    p.add_argument("--run-id", required=True)
    p.add_argument("--alpha-id", required=True)
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(func=post_analysis_template)

    p = sub.add_parser("upsert-alpha", help="upsert alpha_memory.jsonl from an artifact")
    p.add_argument("--run-id", required=True)
    p.add_argument("--alpha-id", required=True)
    p.add_argument("--one-line", required=True)
    p.add_argument("--goal-fit", default="unknown")
    p.add_argument("--status", default="")
    p.add_argument("--family", default="")
    p.add_argument("--post-analysis", default="")
    p.set_defaults(func=upsert_alpha_memory)

    p = sub.add_parser("eval-harness", help="summarize harness versions across runs")
    p.add_argument("--run-id", nargs="+", required=True)
    p.add_argument("--output", default="")
    p.set_defaults(func=evaluate_harness)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
