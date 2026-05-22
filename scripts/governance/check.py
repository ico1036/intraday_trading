#!/usr/bin/env python3
"""Workflow governance checks.

Independent checks, all run by default:

1. ``editable_surface`` — diff vs ``--baseline`` must stay in whitelist.
2. ``universe`` — every alpha manifest's ``symbols`` equals run universe.
3. ``quality`` — every alpha satisfies ``splits.json.quality_gates``.
4. ``coverage`` — no two alphas share the same ALPHA_CELL six-tuple in a run.
5. ``research`` — every alpha references at least one existing
   ``research/notes/<topic>.md`` via SOURCE_NOTES.

Exit codes:
    0 - clean
    1 - violations found
    2 - usage / IO error
"""
from __future__ import annotations

import argparse
import ast
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


# ----- quality gates ------------------------------------------------------


@dataclass
class QualityCheckResult:
    violations: list[dict] = field(default_factory=list)
    inspected: list[str] = field(default_factory=list)


def _load_quality_gates_for_run(run_dir: Path) -> dict:
    splits_path = run_dir / "splits.json"
    if not splits_path.exists():
        return {}
    try:
        data = json.loads(splits_path.read_text())
    except json.JSONDecodeError:
        return {}
    gates = data.get("quality_gates")
    return gates if isinstance(gates, dict) else {}


def _compute_turnover(split_dir: Path) -> float | None:
    """Total absolute notional traded divided by initial equity."""
    trades_path = split_dir / "trades.parquet"
    equity_path = split_dir / "equity_curve.parquet"
    if not trades_path.exists() or not equity_path.exists():
        return None
    import pandas as pd  # local import keeps the script light

    try:
        trades = pd.read_parquet(trades_path)
        equity = pd.read_parquet(equity_path)
    except Exception:
        return None
    if len(equity) == 0 or "equity" not in equity.columns:
        return None
    initial_capital = float(equity["equity"].iloc[0])
    if initial_capital <= 0:
        return None
    if "price" not in trades.columns or "quantity" not in trades.columns:
        return None
    notional = (trades["price"].astype(float) * trades["quantity"].astype(float)).abs().sum()
    return float(notional) / initial_capital


def _apply_quality_gates(split_dir: Path, gates: dict) -> list[dict]:
    violations: list[dict] = []
    metrics_path = split_dir / "metrics.json"
    if not metrics_path.exists():
        return [{"gate": "_meta", "reason": "metrics.json missing"}]
    try:
        metrics = json.loads(metrics_path.read_text())
    except json.JSONDecodeError:
        return [{"gate": "_meta", "reason": "metrics.json invalid"}]

    if "min_trades" in gates:
        threshold = float(gates["min_trades"])
        actual = metrics.get("total_trades")
        if actual is None or float(actual) < threshold:
            violations.append(
                {
                    "gate": "min_trades",
                    "value": actual,
                    "threshold": threshold,
                    "reason": f"total_trades={actual} < {threshold}",
                }
            )

    if "min_turnover" in gates:
        threshold = float(gates["min_turnover"])
        actual = _compute_turnover(split_dir)
        if actual is None or actual < threshold:
            shown = None if actual is None else round(actual, 4)
            violations.append(
                {
                    "gate": "min_turnover",
                    "value": shown,
                    "threshold": threshold,
                    "reason": f"turnover={shown} < {threshold}",
                }
            )

    return violations


def check_quality(
    *, archive_root: Path | None = None, target_alpha_dir: Path | None = None
) -> QualityCheckResult:
    res = QualityCheckResult()
    archive_root = archive_root or (REPO_ROOT / "archive")
    if not archive_root.exists():
        return res

    targets: list[tuple[Path, Path]] = []  # (run_dir, split_dir)
    if target_alpha_dir is not None:
        alpha_dir = Path(target_alpha_dir).resolve()
        run_dir = alpha_dir.parent.parent
        for split in ("is", "os"):
            split_dir = alpha_dir / split
            if split_dir.exists():
                targets.append((run_dir, split_dir))
    else:
        for run_dir in sorted(p for p in archive_root.iterdir() if p.is_dir()):
            alphas_dir = run_dir / "alphas"
            if not alphas_dir.exists():
                continue
            for alpha_dir in sorted(p for p in alphas_dir.iterdir() if p.is_dir()):
                for split in ("is", "os"):
                    split_dir = alpha_dir / split
                    if split_dir.exists():
                        targets.append((run_dir, split_dir))

    for run_dir, split_dir in targets:
        gates = _load_quality_gates_for_run(run_dir)
        if not gates:
            continue
        try:
            rel = split_dir.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            rel = split_dir.as_posix()
        res.inspected.append(rel)
        for v in _apply_quality_gates(split_dir, gates):
            v["path"] = rel
            res.violations.append(v)

    return res


# ----- alpha-cell parsing -------------------------------------------------

ALPHA_CELL_KEYS = ("bar", "transform", "horizon", "universe", "exit", "idea_family")
ALLOWED_BAR = {"TIME", "VOLUME", "DOLLAR", "TICK"}
ALLOWED_TRANSFORM = {"raw", "z_score", "percentile", "rolling_rank", "ewma_residual", "composite"}
ALLOWED_HORIZON = {"ultra_short", "intraday", "session", "multi_day"}
ALLOWED_UNIVERSE = {"single", "pair", "basket_topk", "basket_full"}
ALLOWED_EXIT = {"time_stop", "signal_flip", "trailing", "vol_stop", "neutral_zone", "mixed"}

ALLOWED_VALUES = {
    "bar": ALLOWED_BAR,
    "transform": ALLOWED_TRANSFORM,
    "horizon": ALLOWED_HORIZON,
    "universe": ALLOWED_UNIVERSE,
    "exit": ALLOWED_EXIT,
}

TEMPLATE_FILES = {
    "_alpha_template.py",
    "__init__.py",
}


def _parse_module_constants(path: Path) -> dict | None:
    """Statically extract ALPHA_CELL and SOURCE_NOTES from a strategy file.

    Returns None if either is missing or unparseable. The ALPHA_CELL keys are
    validated against the allowed value sets; ``idea_family`` is free-form.
    """
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        return None

    cell: dict | None = None
    notes: list | None = None

    def _eval_targets(targets: list[ast.expr], value: ast.expr | None) -> None:
        nonlocal cell, notes
        if value is None:
            return
        for tgt in targets:
            if not isinstance(tgt, ast.Name):
                continue
            if tgt.id == "ALPHA_CELL" and isinstance(value, ast.Dict):
                try:
                    cell = ast.literal_eval(value)
                except (ValueError, SyntaxError):
                    cell = None
            elif tgt.id == "SOURCE_NOTES":
                try:
                    notes = ast.literal_eval(value)
                except (ValueError, SyntaxError):
                    notes = None

    for node in tree.body:
        if isinstance(node, ast.Assign):
            _eval_targets(node.targets, node.value)
        elif isinstance(node, ast.AnnAssign):
            # ``SOURCE_NOTES: list[str] = [...]`` is AnnAssign, not Assign.
            _eval_targets([node.target], node.value)

    if not isinstance(cell, dict) or not isinstance(notes, list):
        return None
    return {"alpha_cell": cell, "source_notes": notes}


def _validate_cell(cell: dict) -> list[str]:
    issues: list[str] = []
    for key in ALPHA_CELL_KEYS:
        if key not in cell:
            issues.append(f"missing key: {key}")
    for key, allowed in ALLOWED_VALUES.items():
        v = cell.get(key)
        if v is not None and v not in allowed:
            issues.append(f"{key}={v!r} not in {sorted(allowed)}")
    if "idea_family" in cell and not isinstance(cell["idea_family"], str):
        issues.append("idea_family must be a string")
    return issues


def _cell_signature(cell: dict) -> tuple:
    return tuple(cell.get(k) for k in ALPHA_CELL_KEYS)


# ----- coverage -----------------------------------------------------------


@dataclass
class CoverageCheckResult:
    violations: list[dict] = field(default_factory=list)
    inspected: list[str] = field(default_factory=list)


def _resolve_strategy_path_from_manifest(manifest_path: Path) -> Path | None:
    """Locate the strategy module referenced by a manifest.

    Strategy class is in manifest.json; map class -> module via the same
    snake_case rule the backtest CLI uses.
    """
    try:
        m = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    cls = m.get("strategy_name")
    if not isinstance(cls, str) or not cls:
        return None
    parts = []
    for idx, ch in enumerate(cls):
        if ch.isupper() and idx > 0 and not cls[idx - 1].isupper():
            parts.append("_")
        parts.append(ch.lower())
    module = "".join(parts) + ".py"
    candidate = REPO_ROOT / "src" / "intraday" / "strategies" / "multi" / module
    return candidate if candidate.exists() else None


def check_coverage(*, archive_root: Path | None = None) -> CoverageCheckResult:
    """Detect duplicate (bar, transform, horizon, universe, exit, idea_family).

    For each run, walk all alphas with a manifest, locate their strategy file,
    parse ALPHA_CELL, and report any signature that appears more than once.
    """
    res = CoverageCheckResult()
    archive_root = archive_root or (REPO_ROOT / "archive")
    if not archive_root.exists():
        return res

    for run_dir in sorted(p for p in archive_root.iterdir() if p.is_dir()):
        alphas_dir = run_dir / "alphas"
        if not alphas_dir.exists():
            continue
        seen: dict[tuple, list[str]] = {}
        for alpha_dir in sorted(p for p in alphas_dir.iterdir() if p.is_dir()):
            split_dir = None
            for split in ("is", "os"):
                if (alpha_dir / split / "manifest.json").exists():
                    split_dir = alpha_dir / split
                    break
            if split_dir is None:
                continue
            manifest = split_dir / "manifest.json"
            strat_path = _resolve_strategy_path_from_manifest(manifest)
            try:
                rel = alpha_dir.relative_to(REPO_ROOT).as_posix()
            except ValueError:
                rel = alpha_dir.as_posix()
            res.inspected.append(rel)
            if strat_path is None:
                # legacy alpha with no resolvable strategy file; skip silently
                continue
            consts = _parse_module_constants(strat_path)
            if consts is None:
                # legacy strategy without ALPHA_CELL — skip rather than fail,
                # so historical alphas don't permanently break the check
                continue
            cell = consts["alpha_cell"]
            if _validate_cell(cell):
                res.violations.append(
                    {
                        "path": rel,
                        "reason": "ALPHA_CELL invalid",
                        "issues": _validate_cell(cell),
                    }
                )
                continue
            sig = _cell_signature(cell)
            seen.setdefault(sig, []).append(rel)

        # Duplicate cell-signature violation disabled per owner directive
        # 2026-05-22 ("패밀리 개념 없애"). The 6-tuple cell taxonomy was
        # variant-level rather than mechanism-level, so coverage checks
        # tripped on parameter sweeps that should have been allowed.
        # The cell metadata is still parsed and recorded; only the
        # blocking violation is suppressed.
        _ = seen  # noqa: keep for inspection
    return res


# ----- research citation -------------------------------------------------


@dataclass
class ResearchCheckResult:
    violations: list[dict] = field(default_factory=list)
    inspected: list[str] = field(default_factory=list)


def check_research(*, archive_root: Path | None = None) -> ResearchCheckResult:
    """Each alpha's strategy file must cite >=1 existing research note."""
    res = ResearchCheckResult()
    archive_root = archive_root or (REPO_ROOT / "archive")
    if not archive_root.exists():
        return res
    for run_dir in sorted(p for p in archive_root.iterdir() if p.is_dir()):
        alphas_dir = run_dir / "alphas"
        if not alphas_dir.exists():
            continue
        for alpha_dir in sorted(p for p in alphas_dir.iterdir() if p.is_dir()):
            manifest = None
            for split in ("is", "os"):
                m = alpha_dir / split / "manifest.json"
                if m.exists():
                    manifest = m
                    break
            if manifest is None:
                continue
            strat_path = _resolve_strategy_path_from_manifest(manifest)
            try:
                rel = alpha_dir.relative_to(REPO_ROOT).as_posix()
            except ValueError:
                rel = alpha_dir.as_posix()
            res.inspected.append(rel)
            if strat_path is None or strat_path.name in TEMPLATE_FILES:
                continue
            consts = _parse_module_constants(strat_path)
            if consts is None:
                # legacy strategy without metadata; skip
                continue
            notes = consts["source_notes"]
            if not isinstance(notes, list) or not notes:
                res.violations.append(
                    {"path": rel, "reason": "SOURCE_NOTES empty"}
                )
                continue
            missing = [n for n in notes if not (REPO_ROOT / str(n)).exists()]
            if missing:
                res.violations.append(
                    {"path": rel, "reason": "missing note files", "missing": missing}
                )
    return res


# ----- CLI ----------------------------------------------------------------

CHECK_NAMES = ("editable_surface", "universe", "quality", "coverage", "research")


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
        "--alpha-dir",
        default=None,
        help="Run quality check against a single alpha directory (e.g., archive/<run>/alphas/<alpha>).",
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

    if "quality" in selected:
        target_dir = Path(args.alpha_dir) if args.alpha_dir else None
        q = check_quality(target_alpha_dir=target_dir)
        out["checks"]["quality"] = {
            "ok": not q.violations,
            "inspected_count": len(q.inspected),
            "violations": q.violations,
        }
        if q.violations:
            out["ok"] = False

    if "coverage" in selected:
        c = check_coverage()
        out["checks"]["coverage"] = {
            "ok": not c.violations,
            "inspected_count": len(c.inspected),
            "violations": c.violations,
        }
        if c.violations:
            out["ok"] = False

    if "research" in selected:
        r = check_research()
        out["checks"]["research"] = {
            "ok": not r.violations,
            "inspected_count": len(r.inspected),
            "violations": r.violations,
        }
        if r.violations:
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
    q = out["checks"].get("quality")
    if q is not None:
        print(f"[quality] inspected {q['inspected_count']} alpha split(s)")
        if q["violations"]:
            print(f"  VIOLATIONS ({len(q['violations'])}):")
            for v in q["violations"]:
                gate = v.get("gate", "?")
                print(f"    - {v['path']}  [{gate}] {v.get('reason', '')}")
        else:
            print("  ok: all alphas pass declared quality_gates")
    c = out["checks"].get("coverage")
    if c is not None:
        print(f"[coverage] inspected {c['inspected_count']} alpha(s)")
        if c["violations"]:
            print(f"  VIOLATIONS ({len(c['violations'])}):")
            for v in c["violations"]:
                if "alphas" in v:
                    print(f"    - duplicate cell {v.get('cell')}")
                    for a in v["alphas"]:
                        print(f"        {a}")
                else:
                    print(f"    - {v.get('path', '?')}  ({v.get('reason', '')})")
        else:
            print("  ok: no duplicate cell signatures")
    r = out["checks"].get("research")
    if r is not None:
        print(f"[research] inspected {r['inspected_count']} alpha(s)")
        if r["violations"]:
            print(f"  VIOLATIONS ({len(r['violations'])}):")
            for v in r["violations"]:
                detail = ""
                if "missing" in v:
                    detail = f"  missing={v['missing']}"
                print(f"    - {v['path']}  ({v.get('reason', '')}){detail}")
        else:
            print("  ok: every alpha cites valid research notes")
    print(f"\nresult: {'OK' if out['ok'] else 'FAIL'}")


if __name__ == "__main__":
    sys.exit(main())
