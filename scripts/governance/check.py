#!/usr/bin/env python3
"""Workflow governance checks.

Two independent checks, both run by default:

1. ``editable_surface``
   Compare changed files (vs ``--baseline``, default ``HEAD``) against a
   whitelist of paths agents may modify during alpha generation. Any file
   outside the whitelist is a violation.

2. ``universe``
   For every alpha artifact directory under ``archive/<run_id>/alphas/<alpha_id>/{is,os}``,
   ensure the recorded ``manifest.json`` ``symbols`` exactly equals the
   run's declared ``universe`` in ``archive/<run_id>/splits.json``.

Exit codes:
    0 - clean
    1 - violations found
    2 - usage / IO error

Usage:
    uv run python scripts/governance/check.py --json
    uv run python scripts/governance/check.py --baseline HEAD~1
    uv run python scripts/governance/check.py --staged
    uv run python scripts/governance/check.py --only editable_surface
    uv run python scripts/governance/check.py --only universe
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_UNIVERSE = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "ADAUSDT",
]


# ----- editable surface ---------------------------------------------------

ALLOWED_GLOBS: tuple[str, ...] = (
    "src/intraday/strategies/multi/*.py",
    "tests/strategies/test_*.py",
    "archive/**",
    # governance itself may grow; commits to it should still be reviewed,
    # but they are not "framework" edits.
    "scripts/governance/**",
    "tests/governance/**",
    ".githooks/**",
    # workflow docs are co-evolved with governance; their edits are
    # intentional and visible in PR review.
    "AGENT.md",
    "AUTORESEARCH.md",
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
    "MEMORY.md",  # rare, but explicit
)

# Even if a path matches an allowed glob, these exact files remain frozen
# during alpha generation.
HARD_DENY: tuple[str, ...] = (
    "src/intraday/strategies/multi/_alpha_template.py",
    "src/intraday/strategies/multi/__init__.py",
)


def _match_any(path: str, globs: Iterable[str]) -> bool:
    for pat in globs:
        if fnmatch.fnmatchcase(path, pat):
            return True
        # support ``a/**`` matching nested children
        if pat.endswith("/**") and (path == pat[:-3] or path.startswith(pat[:-2])):
            return True
    return False


def _is_alpha_strategy_path(path: str) -> bool:
    """Allow new alpha files but NOT _alpha_template.py or __init__.py."""
    if not path.startswith("src/intraday/strategies/multi/"):
        return False
    name = Path(path).name
    if name in {"_alpha_template.py", "__init__.py"}:
        return False
    return name.endswith(".py")


def _changed_files(baseline: str | None, staged: bool) -> list[str]:
    if staged:
        cmd = ["git", "diff", "--name-only", "--cached"]
    else:
        cmd = ["git", "diff", "--name-only", baseline or "HEAD"]
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"git diff failed (exit {proc.returncode}): {proc.stderr.strip()}"
        )
    return [line for line in proc.stdout.splitlines() if line.strip()]


def check_editable_surface(
    *, baseline: str | None, staged: bool
) -> tuple[list[dict], list[str]]:
    violations: list[dict] = []
    changed = _changed_files(baseline=baseline, staged=staged)
    for path in changed:
        if path in HARD_DENY:
            violations.append(
                {"path": path, "reason": "hard_deny (frozen during alpha generation)"}
            )
            continue
        if _is_alpha_strategy_path(path):
            continue
        if _match_any(path, ALLOWED_GLOBS):
            continue
        violations.append({"path": path, "reason": "outside editable surface"})
    return violations, changed


# ----- universe consistency -----------------------------------------------


@dataclass
class UniverseCheckResult:
    violations: list[dict] = field(default_factory=list)
    inspected: list[str] = field(default_factory=list)


def _load_universe_for_run(run_dir: Path) -> list[str]:
    splits_path = run_dir / "splits.json"
    if not splits_path.exists():
        return []
    try:
        data = json.loads(splits_path.read_text())
    except json.JSONDecodeError:
        return []
    universe = data.get("universe")
    if isinstance(universe, list) and all(isinstance(x, str) for x in universe):
        return [s.upper() for s in universe]
    return []


def check_universe(*, archive_root: Path | None = None) -> UniverseCheckResult:
    res = UniverseCheckResult()
    archive_root = archive_root or (REPO_ROOT / "archive")
    if not archive_root.exists():
        return res
    for run_dir in sorted(p for p in archive_root.iterdir() if p.is_dir()):
        run_universe = _load_universe_for_run(run_dir)
        if not run_universe:
            # legacy run with no universe declared; skip
            continue
        run_universe_set = sorted(set(run_universe))
        alphas_dir = run_dir / "alphas"
        if not alphas_dir.exists():
            continue
        for alpha_dir in sorted(p for p in alphas_dir.iterdir() if p.is_dir()):
            for split in ("is", "os"):
                manifest = alpha_dir / split / "manifest.json"
                if not manifest.exists():
                    continue
                try:
                    rel = manifest.relative_to(REPO_ROOT).as_posix()
                except ValueError:
                    rel = manifest.as_posix()
                res.inspected.append(rel)
                try:
                    m = json.loads(manifest.read_text())
                except json.JSONDecodeError:
                    res.violations.append(
                        {"path": rel, "reason": "invalid manifest.json"}
                    )
                    continue
                symbols = m.get("symbols")
                if not isinstance(symbols, list):
                    res.violations.append(
                        {"path": rel, "reason": "manifest missing symbols list"}
                    )
                    continue
                symbols_set = sorted({s.upper() for s in symbols})
                if symbols_set != run_universe_set:
                    res.violations.append(
                        {
                            "path": rel,
                            "reason": "symbols != run universe",
                            "manifest_symbols": symbols_set,
                            "run_universe": run_universe_set,
                        }
                    )
    return res


# ----- CLI ----------------------------------------------------------------

CHECK_NAMES = ("editable_surface", "universe")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run workflow governance checks.")
    parser.add_argument(
        "--baseline",
        default="HEAD",
        help="git ref to diff against for editable_surface (default: HEAD).",
    )
    parser.add_argument(
        "--staged",
        action="store_true",
        help="Use staged diff (--cached) instead of working-tree diff vs baseline.",
    )
    parser.add_argument(
        "--only",
        choices=CHECK_NAMES,
        action="append",
        help="Run only the named check. May be repeated. Default: all.",
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit JSON output."
    )
    args = parser.parse_args(argv)

    selected = tuple(args.only) if args.only else CHECK_NAMES
    out: dict = {"ok": True, "checks": {}}

    if "editable_surface" in selected:
        try:
            es_violations, changed = check_editable_surface(
                baseline=args.baseline, staged=args.staged
            )
        except RuntimeError as exc:
            print(f"editable_surface: {exc}", file=sys.stderr)
            return 2
        out["checks"]["editable_surface"] = {
            "ok": not es_violations,
            "baseline": "STAGED" if args.staged else args.baseline,
            "changed": changed,
            "violations": es_violations,
        }
        if es_violations:
            out["ok"] = False

    if "universe" in selected:
        u = check_universe()
        out["checks"]["universe"] = {
            "ok": not u.violations,
            "inspected_count": len(u.inspected),
            "violations": u.violations,
        }
        if u.violations:
            out["ok"] = False

    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        _emit_human(out)

    return 0 if out["ok"] else 1


def _emit_human(out: dict) -> None:
    es = out["checks"].get("editable_surface")
    if es is not None:
        print(f"[editable_surface] baseline={es['baseline']}")
        print(f"  changed: {len(es['changed'])} file(s)")
        if es["violations"]:
            print(f"  VIOLATIONS ({len(es['violations'])}):")
            for v in es["violations"]:
                print(f"    - {v['path']}  ({v['reason']})")
        else:
            print("  ok: all changes inside editable surface")
    u = out["checks"].get("universe")
    if u is not None:
        print(f"[universe] inspected {u['inspected_count']} manifest(s)")
        if u["violations"]:
            print(f"  VIOLATIONS ({len(u['violations'])}):")
            for v in u["violations"]:
                detail = ""
                if "manifest_symbols" in v and "run_universe" in v:
                    detail = f"\n      manifest={v['manifest_symbols']}\n      universe={v['run_universe']}"
                print(f"    - {v['path']}  ({v['reason']}){detail}")
        else:
            print("  ok: all manifests match declared run universe")
    print(f"\nresult: {'OK' if out['ok'] else 'FAIL'}")


if __name__ == "__main__":
    sys.exit(main())
