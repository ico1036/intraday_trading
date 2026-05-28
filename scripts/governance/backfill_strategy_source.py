#!/usr/bin/env python3
"""Backfill strategy_source.py snapshots into archive directories.

Walks every ``archive/<run>/alphas/<aid>/{is,os}/`` that has a
``manifest.json`` but no ``strategy_source.py``, locates the matching
strategy module either in the current working tree or in git history,
and writes the source into the archive so the alpha stays reproducible.

Past trap: when ``xs_factor_amihud60d_fwd_c20`` was removed during a
variant-sweep cleanup, the archive metrics survived but the code did
not — running this script after such a cleanup restores the link.

Usage:
    uv run python scripts/governance/backfill_strategy_source.py
    uv run python scripts/governance/backfill_strategy_source.py --dry-run
    uv run python scripts/governance/backfill_strategy_source.py \\
        --archive archive/run_2026_05_full531
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _class_to_module(name: str) -> str:
    """XsFactorAmihud60dFwdC20 -> xs_factor_amihud60d_fwd_c20."""
    out = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    out = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", out)
    return out.lower()


def _candidate_paths(class_name: str) -> list[str]:
    mod = _class_to_module(class_name)
    return [
        f"src/intraday/strategies/multi/{mod}.py",
        f"src/intraday/strategies/{mod}.py",
    ]


def _read_strategy_class(manifest_path: Path) -> str | None:
    try:
        m = json.loads(manifest_path.read_text())
    except Exception:
        return None
    cls = m.get("strategy_name") or m.get("strategy_class") or m.get("alpha_id")
    if isinstance(cls, str) and cls:
        return cls
    return None


def _from_working_tree(rel_paths: list[str]) -> Path | None:
    for rel in rel_paths:
        p = REPO / rel
        if p.exists():
            return p
    return None


def _from_git_history(rel_paths: list[str]) -> tuple[str, str] | None:
    """Return (source_text, commit_sha) for any commit that contains a
    non-empty version of any rel_path. We walk all commits touching the
    path because the most recent one is often a deletion commit whose
    `git show <sha>:<path>` yields empty — we want the latest commit
    *before* the deletion."""
    for rel in rel_paths:
        try:
            shas = subprocess.run(
                ["git", "rev-list", "--all", "--", rel],
                cwd=REPO, capture_output=True, text=True, timeout=10,
            ).stdout.strip().splitlines()
        except Exception:
            continue
        for sha in shas:
            sha = sha.strip()
            if not sha:
                continue
            try:
                text = subprocess.run(
                    ["git", "show", f"{sha}:{rel}"],
                    cwd=REPO, capture_output=True, text=True, timeout=5,
                ).stdout
            except Exception:
                continue
            if text.strip():
                return (text, sha)
    return None


def backfill_one(split_dir: Path, dry_run: bool) -> dict:
    out_src = split_dir / "strategy_source.py"
    meta_path = split_dir / "strategy_source.meta.json"
    manifest = split_dir / "manifest.json"
    result = {"split": str(split_dir), "status": "skip", "reason": ""}
    if out_src.exists():
        result["status"] = "already"
        return result
    if not manifest.exists():
        result["reason"] = "no manifest"
        return result
    cls = _read_strategy_class(manifest)
    if not cls:
        result["reason"] = "no strategy_class in manifest"
        return result
    rels = _candidate_paths(cls)
    wt = _from_working_tree(rels)
    if wt is not None:
        if not dry_run:
            shutil.copy2(wt, out_src)
            meta_path.write_text(json.dumps({
                "strategy_class": cls,
                "source_relpath": str(wt.relative_to(REPO)),
                "origin": "working_tree",
            }, indent=2))
        result["status"] = "restored_wt"
        result["source"] = str(wt.relative_to(REPO))
        return result
    git = _from_git_history(rels)
    if git is None:
        result["status"] = "missing"
        result["reason"] = f"class={cls} not in tree nor git"
        return result
    text, sha = git
    if not dry_run:
        out_src.write_text(text)
        meta_path.write_text(json.dumps({
            "strategy_class": cls,
            "source_relpath": rels[0],
            "origin": "git",
            "git_sha": sha,
        }, indent=2))
    result["status"] = "restored_git"
    result["git_sha"] = sha
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", default="archive", help="root or specific run dir")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    root = (REPO / args.archive).resolve()
    if not root.exists():
        print(f"  not found: {root}", file=sys.stderr)
        return 2

    if (root / "alphas").exists():
        run_dirs = [root]
    else:
        run_dirs = sorted(p for p in root.iterdir() if p.is_dir() and (p / "alphas").exists())

    totals = {"already": 0, "restored_wt": 0, "restored_git": 0, "missing": 0, "skip": 0}
    missing_items: list[str] = []
    for run_dir in run_dirs:
        for alpha_dir in sorted((run_dir / "alphas").iterdir()):
            if not alpha_dir.is_dir():
                continue
            for split in ("is", "os"):
                sd = alpha_dir / split
                if not sd.is_dir():
                    continue
                r = backfill_one(sd, dry_run=args.dry_run)
                totals[r["status"]] = totals.get(r["status"], 0) + 1
                if r["status"] == "missing":
                    missing_items.append(f"  {sd.relative_to(REPO)}: {r['reason']}")

    print(f"archive root: {root.relative_to(REPO)}")
    print(f"runs scanned: {len(run_dirs)}")
    for k in ("already", "restored_wt", "restored_git", "missing", "skip"):
        print(f"  {k:14s} {totals.get(k, 0):>5d}")
    if missing_items:
        print()
        print("[missing — manual attention]")
        for line in missing_items[:30]:
            print(line)
        if len(missing_items) > 30:
            print(f"  ... ({len(missing_items)-30} more)")
    if args.dry_run:
        print()
        print("(dry-run — no files written)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
