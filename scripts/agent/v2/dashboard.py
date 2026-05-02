#!/usr/bin/env python3
"""Live status dashboard for a v2 run.

Usage:
    uv run python scripts/agent/v2/dashboard.py pilot_01

No external deps — ANSI escapes + polling every 2s.

Detects the orchestrator's current step by filesystem state:

    no algorithm_prompt.txt in latest exp        → ② Researcher
    algorithm_prompt.txt but no strategy .py     → ④ Developer
    strategy .py but no metrics.json             → ⑤ Analyst (backtest)
    metrics.json but no failure_mode.txt         → ⑤ Analyst (tagging)
    failure_mode.txt but last log != this exp    → ⑥-⑧ Gate / log append
    all artifacts present                        → waiting for next iter
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ARCHIVE_ROOT = PROJECT_ROOT / "archive"
STRATEGIES_DIR = PROJECT_ROOT / "src" / "intraday" / "strategies" / "tick"


# ---------------------------------------------------------------------------
# ANSI helpers.
# ---------------------------------------------------------------------------


class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    CLS = "\033[2J\033[H"
    GREEN = "\033[32m"
    RED = "\033[31m"
    YELLOW = "\033[33m"
    CYAN = "\033[36m"
    MAGENTA = "\033[35m"
    BLUE = "\033[34m"


def bold(s: str) -> str:
    return f"{C.BOLD}{s}{C.RESET}"


def dim(s: str) -> str:
    return f"{C.DIM}{s}{C.RESET}"


def green(s: str) -> str:
    return f"{C.GREEN}{s}{C.RESET}"


def red(s: str) -> str:
    return f"{C.RED}{s}{C.RESET}"


def yellow(s: str) -> str:
    return f"{C.YELLOW}{s}{C.RESET}"


def cyan(s: str) -> str:
    return f"{C.CYAN}{s}{C.RESET}"


# ---------------------------------------------------------------------------
# State probe.
# ---------------------------------------------------------------------------


@dataclass
class State:
    run_id: str
    run_dir: Path
    done: bool
    done_reason: str | None
    total_expressions: int
    total_theses: int
    latest_thesis: str | None
    latest_exp: str | None
    current_step: str  # one of "idle", "② researcher", "④ developer", etc.
    current_step_detail: str
    mode_counter: Counter
    recent_entries: list[dict]
    budget: dict
    process_alive: bool
    process_cpu: str | None


STEP_LABELS = {
    "idle": dim("idle / waiting"),
    "researcher": cyan("② Researcher") + " — writing thesis / expression",
    "developer": cyan("④ Developer") + " — strategy code + tests",
    "analyst_run": cyan("⑤ Analyst") + " — running backtest",
    "analyst_tag": cyan("⑤ Analyst") + " — tagging failure_mode",
    "gate_log": cyan("⑥-⑧ Gate + log") + " — verdict / research_map",
    "done": green("✓ DONE"),
    "missing": red("run not scaffolded"),
}


# ---------------------------------------------------------------------------
# Probe.
# ---------------------------------------------------------------------------


def _latest_thesis(run_dir: Path) -> Path | None:
    theses = sorted((run_dir / "theses").glob("th_*")) if (run_dir / "theses").is_dir() else []
    return theses[-1] if theses else None


def _latest_expression(thesis_dir: Path) -> Path | None:
    exps = sorted((thesis_dir / "expressions").glob("exp_*")) if (
        thesis_dir / "expressions"
    ).is_dir() else []
    return exps[-1] if exps else None


def _derive_strategy_name(algorithm_prompt: str) -> str | None:
    # Scan body for "# Strategy: <Name>"
    m = re.search(r"^# Strategy:\s*([A-Za-z0-9_]+)", algorithm_prompt, re.MULTILINE)
    return m.group(1) if m else None


def _strategy_file_exists(strategy_name: str) -> bool:
    # Case-insensitive snake/camel match
    target = strategy_name.lower().replace("strategy", "").strip("_")
    for p in STRATEGIES_DIR.glob("*.py"):
        stem = p.stem.lower()
        if target and (target in stem or stem in target):
            return True
    return False


def _last_log_entry(run_dir: Path) -> dict | None:
    path = run_dir / "expression_log.jsonl"
    if not path.exists():
        return None
    lines = path.read_text().splitlines()
    for line in reversed(lines):
        line = line.strip()
        if line:
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return None


def _read_log(run_dir: Path) -> list[dict]:
    path = run_dir / "expression_log.jsonl"
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _parse_budget(run_dir: Path) -> dict:
    plan_path = run_dir / "PLAN.md"
    if not plan_path.exists():
        return {}
    out = {
        "max_trials": 20,
        "max_theses_per_run": 5,
        "max_expressions_per_thesis": 8,
    }
    for line in plan_path.read_text().splitlines():
        line = line.strip()
        for key in list(out.keys()):
            if line.startswith(f"{key}:"):
                try:
                    out[key] = int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
    return out


def _process_status() -> tuple[bool, str | None]:
    try:
        import subprocess

        out = subprocess.check_output(
            ["ps", "-ax", "-o", "pid,pcpu,comm"], text=True, stderr=subprocess.DEVNULL
        )
    except Exception:
        return False, None
    for line in out.splitlines():
        if "run_v2.py" in line or "claude" in line.lower():
            if "run_v2.py" in line:
                parts = line.split(None, 2)
                if len(parts) >= 2:
                    return True, parts[1]
    return False, None


def probe(run_id: str) -> State:
    run_dir = ARCHIVE_ROOT / run_id
    if not run_dir.is_dir():
        return State(
            run_id=run_id,
            run_dir=run_dir,
            done=False,
            done_reason=None,
            total_expressions=0,
            total_theses=0,
            latest_thesis=None,
            latest_exp=None,
            current_step="missing",
            current_step_detail="",
            mode_counter=Counter(),
            recent_entries=[],
            budget={},
            process_alive=False,
            process_cpu=None,
        )

    done_path = run_dir / "DONE"
    done = done_path.exists()
    done_reason = None
    if done:
        for line in done_path.read_text().splitlines():
            if line.startswith("reason:"):
                done_reason = line.split(":", 1)[1].strip()
                break

    log = _read_log(run_dir)
    theses = sorted((run_dir / "theses").glob("th_*")) if (run_dir / "theses").is_dir() else []
    latest_th = theses[-1] if theses else None
    latest_exp = _latest_expression(latest_th) if latest_th else None
    mode_counter = Counter(e.get("failure_mode", "?") for e in log)

    alive, cpu = _process_status()

    # Decide step.
    if done:
        step = "done"
        detail = done_reason or ""
    elif latest_exp is None:
        step = "researcher"
        detail = "first expression of new thesis"
    else:
        ap_path = latest_exp / "algorithm_prompt.txt"
        failure_path = latest_exp / "failure_mode.txt"
        metrics_path = latest_exp / "metrics.json"
        last_log = _last_log_entry(run_dir)
        exp_id = latest_exp.name

        if not ap_path.exists():
            step = "researcher"
            detail = f"writing {exp_id}"
        else:
            strategy_name = _derive_strategy_name(ap_path.read_text())
            if strategy_name and not _strategy_file_exists(strategy_name):
                step = "developer"
                detail = f"implementing {strategy_name}"
            elif not metrics_path.exists():
                step = "analyst_run"
                detail = f"backtesting {exp_id}"
            elif not failure_path.exists():
                step = "analyst_tag"
                detail = f"tagging {exp_id}"
            elif last_log is None or last_log.get("expression_id") != exp_id:
                step = "gate_log"
                detail = f"verdict + log for {exp_id}"
            else:
                step = "idle"
                detail = "iteration done — next researcher call imminent"

    return State(
        run_id=run_id,
        run_dir=run_dir,
        done=done,
        done_reason=done_reason,
        total_expressions=len(log),
        total_theses=len(theses),
        latest_thesis=latest_th.name if latest_th else None,
        latest_exp=latest_exp.name if latest_exp else None,
        current_step=step,
        current_step_detail=detail,
        mode_counter=mode_counter,
        recent_entries=log[-5:],
        budget=_parse_budget(run_dir),
        process_alive=alive,
        process_cpu=cpu,
    )


def state_to_dict(state: State) -> dict:
    """JSON-serialisable snapshot, consumed by the web UI."""
    return {
        "run_id": state.run_id,
        "run_dir": str(state.run_dir),
        "done": state.done,
        "done_reason": state.done_reason,
        "total_expressions": state.total_expressions,
        "total_theses": state.total_theses,
        "latest_thesis": state.latest_thesis,
        "latest_exp": state.latest_exp,
        "current_step": state.current_step,
        "current_step_detail": state.current_step_detail,
        "mode_counter": dict(state.mode_counter),
        "recent_entries": list(state.recent_entries),
        "budget": dict(state.budget),
        "process_alive": state.process_alive,
        "process_cpu": state.process_cpu,
    }


def list_runs() -> list[dict]:
    """Lightweight listing for the web run-picker."""
    if not ARCHIVE_ROOT.is_dir():
        return []
    out = []
    for p in sorted(ARCHIVE_ROOT.iterdir(), key=lambda x: -x.stat().st_mtime):
        if not p.is_dir() or p.name.startswith("."):
            continue
        done = (p / "DONE").exists()
        log = _read_log(p)
        out.append(
            {
                "run_id": p.name,
                "done": done,
                "mtime": p.stat().st_mtime,
                "expressions": len(log),
                "theses": len(
                    list((p / "theses").glob("th_*")) if (p / "theses").is_dir() else []
                ),
                "approved": sum(
                    1 for e in log if e.get("failure_mode") == "APPROVED"
                ),
            }
        )
    return out


def _metric(r: dict, key: str):
    """Read a metric from flat top-level, falling back to nested is_metrics."""
    if r.get(key) is not None:
        return r[key]
    is_m = r.get("is_metrics") or {}
    if is_m.get(key) is not None:
        return is_m[key]
    return None


def list_strategies() -> list[dict]:
    """Flatten every expression across every run into a strategy catalogue."""
    if not ARCHIVE_ROOT.is_dir():
        return []
    out: list[dict] = []
    for run in sorted(ARCHIVE_ROOT.iterdir(), key=lambda x: -x.stat().st_mtime):
        if not run.is_dir() or run.name.startswith("."):
            continue
        log = _read_log(run)
        for e in log:
            r = e.get("result") or {}
            out.append(
                {
                    "run_id": e.get("run_id", run.name),
                    "thesis_id": e.get("thesis_id"),
                    "expression_id": e.get("expression_id"),
                    "failure_mode": e.get("failure_mode"),
                    "verdict_after": e.get("verdict_after"),
                    "features_used": e.get("features_used") or [],
                    "profit_factor": _metric(r, "profit_factor"),
                    "total_return": _metric(r, "total_return"),
                    "total_trades": _metric(r, "total_trades"),
                    "win_rate": _metric(r, "win_rate"),
                    "max_drawdown": _metric(r, "max_drawdown"),
                    "sharpe": _metric(r, "sharpe") or _metric(r, "sharpe_ratio"),
                    "backtest_wall_seconds": _metric(r, "backtest_wall_seconds"),
                    "tick_throughput": _metric(r, "tick_throughput"),
                    "iter_duration_s": e.get("iter_duration_s"),
                    "ts": e.get("ts"),
                    "artifact_path": e.get("artifact_path"),
                }
            )
    return out


def strategy_detail(run_id: str, thesis_id: str, expression_id: str) -> dict:
    exp_dir = ARCHIVE_ROOT / run_id / "theses" / thesis_id / "expressions" / expression_id
    if not exp_dir.is_dir():
        return {"error": f"expression not found: {exp_dir}"}

    ap_path = exp_dir / "algorithm_prompt.txt"
    metrics_path = exp_dir / "metrics.json"
    failure_path = exp_dir / "failure_mode.txt"
    report_path = exp_dir / "backtest_report.md"
    thesis_path = ARCHIVE_ROOT / run_id / "theses" / thesis_id / "thesis.md"
    verdict_path = ARCHIVE_ROOT / run_id / "theses" / thesis_id / "verdict.md"

    def _safe_read(p: Path) -> str:
        try:
            return p.read_text()
        except FileNotFoundError:
            return ""

    metrics = {}
    if metrics_path.exists():
        try:
            metrics = json.loads(metrics_path.read_text())
        except json.JSONDecodeError:
            pass

    return {
        "run_id": run_id,
        "thesis_id": thesis_id,
        "expression_id": expression_id,
        "algorithm_prompt": _safe_read(ap_path),
        "thesis_md": _safe_read(thesis_path),
        "verdict_md": _safe_read(verdict_path),
        "backtest_report": _safe_read(report_path),
        "metrics": metrics,
        "failure_mode": _safe_read(failure_path).strip() or None,
        "has_equity_curve": (exp_dir / "equity_curve.parquet").exists()
        or (exp_dir / "equity_curve.csv").exists(),
        "has_trades": (exp_dir / "trades.parquet").exists()
        or (exp_dir / "trades.csv").exists(),
        "has_report_png": (exp_dir / "report.png").exists(),
    }


def equity_curve(run_id: str, thesis_id: str, expression_id: str, max_points: int = 2000) -> dict:
    exp_dir = ARCHIVE_ROOT / run_id / "theses" / thesis_id / "expressions" / expression_id
    pqt = exp_dir / "equity_curve.parquet"
    csv = exp_dir / "equity_curve.csv"

    import pandas as pd  # lazy import — only needed on detail fetch

    if pqt.exists():
        df = pd.read_parquet(pqt)
    elif csv.exists():
        df = pd.read_csv(csv)
    else:
        return {"points": [], "error": "no equity curve artifact"}

    if len(df) > max_points:
        step = max(1, len(df) // max_points)
        df = df.iloc[::step].reset_index(drop=True)

    ts_col = "timestamp" if "timestamp" in df.columns else df.columns[0]
    eq_col = "equity" if "equity" in df.columns else df.columns[-1]

    points = [
        {"ts": str(row[ts_col]), "equity": float(row[eq_col])}
        for _, row in df.iterrows()
    ]
    return {"points": points, "count": len(points)}


# ---------------------------------------------------------------------------
# Render.
# ---------------------------------------------------------------------------


def _bar(n: int, total: int, width: int = 30) -> str:
    if total <= 0:
        return dim("no budget")
    filled = int(width * n / total)
    bar = "█" * filled + "░" * (width - filled)
    return f"{bar} {n}/{total}"


def render(state: State) -> str:
    lines = []
    header = f" v2 Dashboard — run={state.run_id} "
    lines.append(bold("═" * 2 + header + "═" * max(0, 76 - len(header))))

    # Process & top-level status
    proc_str = (
        green("● alive") + f" (cpu {state.process_cpu}%)"
        if state.process_alive
        else red("○ not running")
    )
    lines.append(f" process      : {proc_str}")
    lines.append(f" current step : {STEP_LABELS.get(state.current_step, state.current_step)}")
    if state.current_step_detail:
        lines.append(f"                {dim(state.current_step_detail)}")
    lines.append("")

    # Budgets
    budget = state.budget
    if budget:
        lines.append(bold(" Budgets"))
        lines.append(
            f"   trials  {_bar(state.total_expressions, budget.get('max_trials', 0))}"
        )
        lines.append(
            f"   theses  {_bar(state.total_theses, budget.get('max_theses_per_run', 0))}"
        )
        lines.append("")

    # Latest state
    lines.append(bold(" Latest"))
    lines.append(f"   thesis      : {state.latest_thesis or dim('(none)')}")
    lines.append(f"   expression  : {state.latest_exp or dim('(none)')}")
    lines.append("")

    # Mode distribution
    if state.mode_counter:
        lines.append(bold(" Failure mode distribution"))
        for mode, n in sorted(state.mode_counter.items()):
            colour = green if mode == "APPROVED" else (
                red if mode in ("SIGNAL_NOISY", "THESIS_INVERTED") else yellow
            )
            lines.append(f"   {colour(mode.ljust(20))} {n}")
        lines.append("")

    # Recent expressions
    if state.recent_entries:
        lines.append(bold(" Recent expressions"))
        for e in state.recent_entries:
            mode = e.get("failure_mode", "?")
            verdict = e.get("verdict_after", "?")
            tid = e.get("thesis_id", "?")
            eid = e.get("expression_id", "?")
            r = e.get("result") or {}
            pf = r.get("profit_factor")
            pf_str = f" pf={pf:.2f}" if isinstance(pf, (int, float)) else ""
            lines.append(
                f"   {tid}/{eid}  {mode.ljust(18)} → {verdict.ljust(18)}{pf_str}"
            )
        lines.append("")

    # Done / exit reason
    if state.done:
        reason = state.done_reason or "?"
        lines.append(bold(green(f" ✓ RUN COMPLETE — reason: {reason}")))
    elif not state.process_alive and state.total_expressions > 0:
        lines.append(yellow(" ⚠ process not running but no DONE sentinel — crashed?"))

    lines.append("")
    lines.append(dim(" (q to quit, any other key to refresh now)  polling 2s"))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main loop.
# ---------------------------------------------------------------------------


def _autodetect_run() -> str | None:
    if not ARCHIVE_ROOT.is_dir():
        return None
    runs = [p for p in ARCHIVE_ROOT.iterdir() if p.is_dir() and p.name != ".gitkeep"]
    if not runs:
        return None
    return max(runs, key=lambda p: p.stat().st_mtime).name


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="v2 harness live dashboard")
    p.add_argument(
        "run_id",
        nargs="?",
        help="run id; defaults to the most recently modified run under archive/",
    )
    p.add_argument("--interval", type=float, default=2.0, help="poll interval seconds")
    args = p.parse_args(argv)

    run_id = args.run_id or _autodetect_run()
    if not run_id:
        print("no runs found in archive/", file=sys.stderr)
        return 1

    try:
        while True:
            state = probe(run_id)
            sys.stdout.write(C.CLS)
            sys.stdout.write(render(state))
            sys.stdout.flush()
            if state.done:
                print("\n")
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
