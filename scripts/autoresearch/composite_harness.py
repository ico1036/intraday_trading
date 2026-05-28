"""Autoresearch loop for composite alpha discovery.

Karpathy-style 3-layer architecture (see AUTORESEARCH_COMPOSITE.md):

    immutable evaluator → scripts/tools/backtest.py + _runner.py
    agent sandbox       → src/intraday/composites/auto_<NNN>_<slug>.py
    human direction     → scripts/autoresearch/AUTORESEARCH_COMPOSITE.md

The harness:

1.  Builds a prompt (prompt_template.md + live run/pool/history context).
2.  Calls `claude` CLI in print mode to generate one composite file.
3.  Validates the file against the AST + structural sandbox policy.
4.  If valid, writes the file and runs the canonical backtester
    (`uv run python -m intraday.composites.<id> --run-id <run>`),
    which produces both IS and OS metrics via the same engine used for
    every other composite.
5.  Parses metrics.json from both splits and logs to LOG.md + state.json.
6.  Stops when OS Sharpe ≥ target, iteration budget exhausted, or wall
    clock elapsed.

Run:

    uv run python scripts/autoresearch/composite_harness.py \
        --run-id run_2026_05_full531 \
        --target-os-sharpe 2.0 \
        --max-iterations 500 \
        --wall-clock-seconds 28800

State persisted at scripts/autoresearch/state.json. Per-iteration
prompt + response + backtest log at scripts/autoresearch/iterations/.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = REPO_ROOT / "archive"
SANDBOX_DIR = REPO_ROOT / "src" / "intraday" / "composites"
HARNESS_DIR = Path(__file__).resolve().parent
ITERATIONS_DIR = HARNESS_DIR / "iterations"
STATE_PATH = HARNESS_DIR / "state.json"
PROMPT_TEMPLATE = HARNESS_DIR / "prompt_template.md"
SPEC_DOC = HARNESS_DIR / "AUTORESEARCH_COMPOSITE.md"

ALLOWED_STDLIB = {
    "__future__", "argparse", "math", "json", "dataclasses", "typing",
    "itertools", "functools", "collections",
}
ALLOWED_THIRDPARTY = {
    "numpy", "pandas", "scipy", "scipy.linalg", "scipy.cluster",
    "scipy.cluster.hierarchy", "scipy.spatial", "scipy.spatial.distance",
    "scipy.stats", "scipy.optimize",
}
ALLOWED_PROJECT = {
    "intraday", "intraday.composites", "intraday.composites._runner",
    "intraday.composites._optim_helpers",
}
ALLOWED_RUNNER_NAMES = {"build_and_backtest"}
ALLOWED_OPTIM_HELPER_NAMES = {
    "correlation_dedup", "member_signs_ic", "member_signs", "apply_signs",
    "shrink_cov", "select_is_submittable", "select_all_alphas",
    "member_is_sharpe", "member_ic", "load_member_is_returns",
    "normalize_coefficients",
}
FORBIDDEN_NAMES = {
    "open", "exec", "eval", "compile", "__import__", "globals", "locals",
    "input", "breakpoint", "Path", "PurePath", "PosixPath", "WindowsPath",
}
FORBIDDEN_MODULE_ATTRS = {
    "os", "sys", "subprocess", "shutil", "socket", "urllib", "requests",
    "pickle", "joblib", "ctypes", "cffi", "io",
}
PATH_LITERAL_RE = re.compile(
    r"(?:archive/[^\s\"']*?/(?:alphas|composites)/[^/\s\"']+/os/|/os/weights\.parquet|/os/metrics\.json)"
)
CODE_BLOCK_RE = re.compile(
    r"```python\s+COMPOSITE_FILE\s*\n(.*?)\n```", re.DOTALL
)
SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


@dataclass
class IterationResult:
    n: int
    composite_id: str
    status: str  # INVALID | EVALUATED | ERRORED | TARGET_HIT
    reason: str = ""
    is_sharpe: Optional[float] = None
    os_sharpe: Optional[float] = None
    is_return: Optional[float] = None
    os_return: Optional[float] = None
    is_dd: Optional[float] = None
    os_dd: Optional[float] = None
    n_members: Optional[int] = None
    notes: str = ""


# ---------- AST / sandbox validation ----------


class SandboxViolation(Exception):
    pass


def _check_imports(tree: ast.Module) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                full = alias.name
                if full in ALLOWED_STDLIB or root in ALLOWED_STDLIB:
                    continue
                if full in ALLOWED_THIRDPARTY or root in ALLOWED_THIRDPARTY:
                    continue
                if full in ALLOWED_PROJECT or root in ALLOWED_PROJECT:
                    continue
                raise SandboxViolation(f"forbidden import: {full}")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            root = mod.split(".")[0]
            if mod in ALLOWED_STDLIB or root in ALLOWED_STDLIB:
                continue
            if mod in ALLOWED_THIRDPARTY or root in ALLOWED_THIRDPARTY:
                continue
            if mod == "intraday.composites._runner":
                for alias in node.names:
                    if alias.name not in ALLOWED_RUNNER_NAMES:
                        raise SandboxViolation(
                            f"_runner: only {ALLOWED_RUNNER_NAMES} allowed, got {alias.name}"
                        )
                continue
            if mod == "intraday.composites._optim_helpers":
                for alias in node.names:
                    if alias.name not in ALLOWED_OPTIM_HELPER_NAMES:
                        raise SandboxViolation(
                            f"_optim_helpers: name {alias.name} not on allow-list"
                        )
                continue
            if mod in ALLOWED_PROJECT or root in ALLOWED_PROJECT:
                raise SandboxViolation(
                    f"project import {mod} not in {ALLOWED_PROJECT}"
                )
            raise SandboxViolation(f"forbidden ImportFrom: {mod}")


def _check_names_and_attrs(tree: ast.Module) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            raise SandboxViolation(f"forbidden name: {node.id}")
        if isinstance(node, ast.Attribute):
            base = node
            chain = []
            while isinstance(base, ast.Attribute):
                chain.append(base.attr)
                base = base.value
            if isinstance(base, ast.Name):
                root = base.id
                if root in FORBIDDEN_MODULE_ATTRS:
                    raise SandboxViolation(
                        f"forbidden attribute access on {root}: "
                        f"{root}.{'.'.join(reversed(chain))}"
                    )
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name) and f.id in FORBIDDEN_NAMES:
                raise SandboxViolation(f"forbidden call: {f.id}(...)")


def _check_path_literals(source: str) -> None:
    if PATH_LITERAL_RE.search(source):
        raise SandboxViolation(
            "string literal references OS-split path — selection/weighting "
            "must not peek at OS data"
        )


def _check_required_structure(tree: ast.Module, expected_id: str) -> None:
    top_names = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    top_names[target.id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.value is not None:
                top_names[node.target.id] = node.value
        elif isinstance(node, ast.FunctionDef):
            top_names[node.name] = node
    missing = [
        n for n in ("COMPOSITE_ID", "COMPOSITION_NOTE",
                    "select_members", "member_weights", "main")
        if n not in top_names
    ]
    if missing:
        raise SandboxViolation(f"missing required top-level names: {missing}")
    cid_node = top_names["COMPOSITE_ID"]
    if not isinstance(cid_node, ast.Constant) or cid_node.value != expected_id:
        got = ast.unparse(cid_node) if hasattr(ast, "unparse") else "<expr>"
        raise SandboxViolation(
            f'COMPOSITE_ID must be the literal string "{expected_id}", got {got}'
        )
    note_node = top_names["COMPOSITION_NOTE"]
    if not isinstance(note_node, ast.Constant) or not isinstance(note_node.value, str):
        raise SandboxViolation("COMPOSITION_NOTE must be a string literal")
    for fn_name, n_args in (("select_members", 1), ("member_weights", 2)):
        fn = top_names[fn_name]
        if not isinstance(fn, ast.FunctionDef):
            raise SandboxViolation(f"{fn_name} must be a function")
        if len(fn.args.args) != n_args:
            raise SandboxViolation(
                f"{fn_name} must take exactly {n_args} positional arg(s)"
            )


def validate_file_source(source: str, expected_id: str) -> None:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise SandboxViolation(f"syntax error: {exc}") from exc
    _check_imports(tree)
    _check_names_and_attrs(tree)
    _check_path_literals(source)
    _check_required_structure(tree, expected_id)


# ---------- alpha pool / context ----------


def load_pool_summary(run_id: str) -> dict:
    import pandas as pd  # local import — harness deliberately lightweight
    idx_path = ARCHIVE / run_id / "alpha_index.csv"
    df = pd.read_csv(idx_path) if idx_path.exists() else pd.DataFrame()
    keep = [c for c in df.columns if not c.startswith("os_")]
    df = df[keep].copy()

    # Fallback: if alpha_index is essentially empty, scan archive for
    # per-alpha is/metrics.json so the prompt still gets useful summary
    # statistics.
    if len(df) < 5:
        alphas_dir = ARCHIVE / run_id / "alphas"
        rows = []
        if alphas_dir.exists():
            for d in alphas_dir.iterdir():
                if not d.is_dir():
                    continue
                m = d / "is" / "metrics.json"
                if not m.exists():
                    continue
                try:
                    js = json.loads(m.read_text())
                except Exception:
                    continue
                rows.append({
                    "alpha_id": d.name,
                    "strategy": js.get("strategy_name") or js.get("strategy") or "?",
                    "is_sharpe": js.get("sharpe_daily") or js.get("sharpe"),
                    "is_return": js.get("total_return"),
                    "is_trades": js.get("total_trades"),
                    "ic_mean_is": js.get("ic_mean"),
                    "label_is": "FS_SCAN",  # synthetic label — agent must use helpers
                })
        df = pd.DataFrame(rows)

    sharpe_col = "is_sharpe_daily" if "is_sharpe_daily" in df.columns else "is_sharpe"
    label_col = "label_is" if "label_is" in df.columns else None
    if sharpe_col in df.columns:
        df[sharpe_col] = pd.to_numeric(df[sharpe_col], errors="coerce")
    df = df.dropna(subset=[sharpe_col]) if sharpe_col in df.columns else df
    n_alphas = int(len(df))
    if label_col is not None and (df[label_col] == "SUBMITTABLE").any():
        n_submittable = int((df[label_col] == "SUBMITTABLE").sum())
    else:
        # filesystem fallback: invoke the same classifier used by helpers
        try:
            sys.path.insert(0, str(REPO_ROOT / "src"))
            from intraday.composites._optim_helpers import select_is_submittable
            n_submittable = len(select_is_submittable(run_id))
        except Exception:
            n_submittable = -1
    s = df[sharpe_col].dropna() if sharpe_col in df.columns else pd.Series([], dtype=float)
    median = float(s.median()) if len(s) else 0.0
    p90 = float(s.quantile(0.9)) if len(s) else 0.0
    top_cols = [c for c in ["alpha_id", "strategy", sharpe_col] if c in df.columns]
    top = df.nlargest(10, sharpe_col)[top_cols] if sharpe_col in df.columns else df.head(10)
    top_lines = ["    | alpha_id | strategy | is_sharpe |",
                 "    |---|---|---:|"]
    for _, r in top.iterrows():
        top_lines.append(
            f"    | {r['alpha_id']} | {r.get('strategy','?')} | {float(r[sharpe_col]):.3f} |"
        )
    columns_str = ", ".join(df.columns)
    return {
        "n_alphas": n_alphas,
        "n_submittable": n_submittable,
        "is_sharpe_median": median,
        "is_sharpe_p90": p90,
        "top_alphas_table": "\n".join(top_lines),
        "alpha_index_columns": columns_str,
    }


def load_tried_ideas(run_id: str, last_k: int = 30) -> str:
    log = ARCHIVE / run_id / "composites" / "LOG.md"
    if not log.exists():
        return "    (none yet)"
    text = log.read_text().splitlines()
    rows = [ln for ln in text if ln.startswith("| ") and not ln.startswith("|---")]
    if not rows:
        return "    (no tabular rows yet)"
    header = rows[0]
    body = rows[1:]
    if len(body) > last_k:
        body = body[-last_k:]
    return "\n".join(["    " + header] + ["    " + r for r in body])


def load_recent_rejects(state: dict, n: int = 5) -> str:
    rejects = [r for r in state.get("history", []) if r["status"] in ("INVALID", "ERRORED")]
    rejects = rejects[-n:]
    if not rejects:
        return "    (no rejections yet)"
    out = []
    for r in rejects:
        out.append(f"    - iter {r['n']:03d} `{r['composite_id']}` → {r['status']}: {r['reason'][:160]}")
    return "\n".join(out)


# ---------- claude CLI invocation ----------


AGENT_SYSTEM_PROMPT = (
    "You are an automated quant-research code generator. "
    "Respond with exactly one fenced ```python COMPOSITE_FILE block "
    "that conforms to the user's spec. Cite the method by name in the "
    "module docstring. No tools, no questions, no chit-chat. "
    "Free-form rationale is allowed BEFORE the fenced block."
)


def call_claude(prompt: str, timeout_seconds: int = 600,
                model: str = "opus") -> str:
    """Invoke claude CLI in print mode.

    Output captured via direct file descriptors (not subprocess.PIPE) because
    PIPE capture was observed to truncate claude CLI's stdout to a single
    newline when invoked from inside another claude CLI session. Writing to
    a real file works correctly.
    """
    import tempfile
    with tempfile.NamedTemporaryFile(
        mode="r", suffix=".out.txt", delete=False, encoding="utf-8",
    ) as of:
        out_path = of.name
    err_path = out_path + ".err"

    cmd = [
        "claude", "-p", prompt,
        "--model", model,
        "--output-format", "text",
        "--permission-mode", "plan",
        "--setting-sources", "local",
        "--no-session-persistence",
        "--append-system-prompt", AGENT_SYSTEM_PROMPT,
        "--exclude-dynamic-system-prompt-sections",
    ]
    # Strip Claude-Code-specific env vars from the child process. When
    # CLAUDECODE / CLAUDE_CODE_ENTRYPOINT / CLAUDE_CODE_EXECPATH are present,
    # the child `claude -p` session detects "I am inside another claude"
    # and emits a single-byte stdout — observed reproducibly in this repo.
    # Removing them lets the child behave like a fresh invocation.
    child_env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    with open(out_path, "w", encoding="utf-8") as out_f, \
         open(err_path, "w", encoding="utf-8") as err_f:
        result = subprocess.run(
            cmd, stdout=out_f, stderr=err_f,
            stdin=subprocess.DEVNULL,
            timeout=timeout_seconds, cwd=str(REPO_ROOT),
            env=child_env,
        )
    try:
        stdout = Path(out_path).read_text(encoding="utf-8")
        stderr = Path(err_path).read_text(encoding="utf-8") if Path(err_path).exists() else ""
    finally:
        for p in (out_path, err_path):
            try:
                Path(p).unlink(missing_ok=True)
            except Exception:
                pass
    if result.returncode != 0:
        raise RuntimeError(
            f"claude CLI exited {result.returncode}\nstderr: {stderr[:2000]}"
        )
    if len(stdout.strip()) < 50:
        raise RuntimeError(
            f"claude CLI returned suspiciously short output ({len(stdout)} bytes); "
            f"stderr tail: {stderr[-400:]}"
        )
    return stdout


def extract_code_block(response: str) -> Optional[str]:
    m = CODE_BLOCK_RE.search(response)
    if m is None:
        return None
    return m.group(1)


# ---------- backtest invocation ----------


def run_composite_backtest(composite_id: str, run_id: str,
                            log_path: Path) -> tuple[bool, str]:
    cmd = [
        "uv", "run", "python", "-m",
        f"intraday.composites.{composite_id}",
        "--run-id", run_id,
    ]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w") as logf:
        logf.write(f"$ {' '.join(cmd)}\n\n")
        logf.flush()
        result = subprocess.run(
            cmd, stdout=logf, stderr=subprocess.STDOUT,
            cwd=str(REPO_ROOT),
        )
    return result.returncode == 0, str(log_path)


def parse_metrics(composite_dir: Path) -> dict:
    out: dict = {}
    for split in ("is", "os"):
        m = composite_dir / split / "metrics.json"
        if not m.exists():
            continue
        try:
            data = json.loads(m.read_text())
        except Exception:
            continue
        out[split] = {
            "sharpe": data.get("sharpe_daily") or data.get("sharpe"),
            "return": data.get("total_return"),
            "trades": data.get("total_trades"),
            "max_dd": data.get("max_drawdown"),
        }
    man = composite_dir / "manifest.json"
    if man.exists():
        try:
            out["manifest"] = json.loads(man.read_text())
        except Exception:
            pass
    return out


# ---------- state / log ----------


def load_state(run_id: str, target: float, max_iterations: int) -> dict:
    if STATE_PATH.exists():
        s = json.loads(STATE_PATH.read_text())
        # carry over but update flags
        s["target_os_sharpe"] = target
        s["max_iterations"] = max(s.get("max_iterations", 0), max_iterations)
        s["status"] = "running"
        return s
    return {
        "run_id": run_id,
        "target_os_sharpe": target,
        "max_iterations": max_iterations,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "iterations_run": 0,
        "iterations_invalid": 0,
        "iterations_evaluated": 0,
        "best": {"composite_id": None, "os_sharpe": None, "is_sharpe": None,
                 "n_members": None, "os_return": None},
        "leaderboard": [],
        "history": [],
        "status": "running",
    }


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2, default=str))


def append_log_row(run_id: str, result: IterationResult) -> None:
    log = ARCHIVE / run_id / "composites" / "LOG.md"
    if not log.exists():
        return
    def fmt(v, pct=False):
        if v is None:
            return "?"
        if pct:
            return f"{v*100:+.2f}%"
        return f"{v:+.2f}"
    row = (
        f"| {result.composite_id} | autores_{result.composite_id.split('_')[2] if len(result.composite_id.split('_'))>2 else 'auto'} "
        f"| {result.n_members if result.n_members is not None else '?'} "
        f"| {fmt(result.is_sharpe)} | {fmt(result.is_return, pct=True)} | {fmt(result.is_dd, pct=True)} "
        f"| {fmt(result.os_sharpe)} | {fmt(result.os_return, pct=True)} | {fmt(result.os_dd, pct=True)} "
        f"| {result.status} | {result.notes[:120]} |\n"
    )
    with log.open("a") as f:
        f.write(row)


def update_leaderboard(state: dict, result: IterationResult) -> None:
    if result.os_sharpe is None:
        return
    state["leaderboard"].append({
        "composite_id": result.composite_id,
        "os_sharpe": result.os_sharpe,
        "is_sharpe": result.is_sharpe,
        "os_return": result.os_return,
        "n_members": result.n_members,
    })
    state["leaderboard"].sort(key=lambda x: (x["os_sharpe"] is None, -(x["os_sharpe"] or -1e9)))
    state["leaderboard"] = state["leaderboard"][:10]
    cur_best = state["best"]["os_sharpe"]
    if cur_best is None or result.os_sharpe > cur_best:
        state["best"] = {
            "composite_id": result.composite_id,
            "os_sharpe": result.os_sharpe,
            "is_sharpe": result.is_sharpe,
            "os_return": result.os_return,
            "n_members": result.n_members,
        }


# ---------- one iteration ----------


class _SafeDict(dict):
    """format_map helper: leaves unknown {placeholders} literal instead of raising."""
    def __missing__(self, key):
        return "{" + key + "}"


def _safe_format(tpl: str, values: dict) -> str:
    """Render `tpl` with `values`; any unhandled brace expression in `tpl`
    is rolled back into a literal so the format step never raises."""
    import string
    class _F(string.Formatter):
        def get_value(self, key, args, kwargs):
            return kwargs.get(key, "{" + str(key) + "}")
        def format_field(self, value, format_spec):
            try:
                return super().format_field(value, format_spec)
            except (ValueError, TypeError):
                # spec was not a real format spec — most likely a stray
                # brace expression in the template; emit it verbatim.
                return str(value) + (":" + format_spec if format_spec else "")
        def vformat(self, format_string, args, kwargs):
            # When parse() itself fails (truly unbalanced braces), fall
            # back to leaving the chunk literal.
            try:
                return super().vformat(format_string, args, kwargs)
            except Exception:
                import re
                # naive escape: double up every brace, then format once.
                escaped = format_string.replace("{", "{{").replace("}", "}}")
                # but re-inject known placeholders
                for k in kwargs:
                    escaped = escaped.replace("{{" + k + "}}", "{" + k + "}")
                return super().vformat(escaped, args, kwargs)
    return _F().vformat(tpl, (), values)


def build_prompt(n: int, composite_id: str, run_id: str, target: float,
                 max_iterations: int, pool: dict, tried: str, rejects: str) -> str:
    tpl = PROMPT_TEMPLATE.read_text()
    return _safe_format(tpl, dict(
        N=n,
        composite_id=composite_id,
        run_id=run_id,
        target_os_sharpe=target,
        max_iterations=max_iterations,
        n_alphas=pool["n_alphas"],
        n_submittable=pool["n_submittable"],
        is_sharpe_median=pool["is_sharpe_median"],
        is_sharpe_p90=pool["is_sharpe_p90"],
        top_alphas_table=pool["top_alphas_table"],
        alpha_index_columns=pool["alpha_index_columns"],
        tried_ideas_table=tried,
        recent_rejects=rejects,
        n_recent_rejects=5,
    ))


def _format_keep_unknown(tpl: str, values: dict) -> str:
    return _safe_format(tpl, values)


def next_iteration_n(state: dict) -> int:
    return state["iterations_run"] + 1


def assign_composite_id(n: int) -> str:
    return f"auto_{n:03d}"  # slug appended after agent sets COMPOSITION_NOTE


def slugify(note: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", note.lower()).strip("_")
    s = s[:40].strip("_") or "idea"
    if not SLUG_RE.match(s):
        s = "idea"
    return s


def run_iteration(state: dict, args) -> IterationResult:
    n = next_iteration_n(state)
    initial_id = assign_composite_id(n)
    iter_dir = ITERATIONS_DIR / f"{n:03d}"
    iter_dir.mkdir(parents=True, exist_ok=True)

    pool = load_pool_summary(args.run_id)
    tried = load_tried_ideas(args.run_id)
    rejects = load_recent_rejects(state)
    prompt = build_prompt(n, initial_id, args.run_id, args.target_os_sharpe,
                          args.max_iterations, pool, tried, rejects)
    (iter_dir / "prompt.md").write_text(prompt)

    try:
        response = call_claude(prompt, timeout_seconds=args.llm_timeout, model=args.model)
    except (subprocess.TimeoutExpired, RuntimeError) as exc:
        return IterationResult(
            n=n, composite_id=initial_id, status="ERRORED",
            reason=f"claude CLI: {exc}"[:400],
        )
    (iter_dir / "response.md").write_text(response)

    code = extract_code_block(response)
    if code is None:
        return IterationResult(
            n=n, composite_id=initial_id, status="INVALID",
            reason="no ```python COMPOSITE_FILE block found",
        )

    # Parse COMPOSITION_NOTE first so we can build the final composite_id
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return IterationResult(
            n=n, composite_id=initial_id, status="INVALID",
            reason=f"syntax: {exc}",
        )
    note_value: Optional[str] = None
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 \
                and isinstance(stmt.targets[0], ast.Name) \
                and stmt.targets[0].id == "COMPOSITION_NOTE" \
                and isinstance(stmt.value, ast.Constant):
            note_value = str(stmt.value.value)
            break
    slug = slugify(note_value or "idea")
    composite_id = f"auto_{n:03d}_{slug}"

    # Patch COMPOSITE_ID inside the source so it matches the final filename
    # Accept any auto_* literal the agent may have written.
    code_patched = re.sub(
        r'^(COMPOSITE_ID\s*=\s*)["\']auto_[A-Za-z0-9_]*["\'](\s*#.*)?$',
        rf'\1"{composite_id}"',
        code, count=1, flags=re.MULTILINE,
    )

    try:
        validate_file_source(code_patched, composite_id)
    except SandboxViolation as exc:
        return IterationResult(
            n=n, composite_id=composite_id, status="INVALID",
            reason=f"sandbox: {exc}",
        )

    target_file = SANDBOX_DIR / f"{composite_id}.py"
    target_file.write_text(code_patched)
    (iter_dir / "composite_source.py").write_text(code_patched)

    bt_log = iter_dir / "backtest.log"
    ok, _ = run_composite_backtest(composite_id, args.run_id, bt_log)
    comp_dir = ARCHIVE / args.run_id / "composites" / composite_id
    metrics = parse_metrics(comp_dir)

    if not metrics.get("is") or not metrics.get("os"):
        tail = bt_log.read_text()[-1200:] if bt_log.exists() else ""
        return IterationResult(
            n=n, composite_id=composite_id, status="ERRORED",
            reason=f"backtest produced incomplete metrics. tail: {tail[-300:]}",
        )

    is_m = metrics["is"]
    os_m = metrics["os"]
    n_members = metrics.get("manifest", {}).get("n_members")
    status = "TARGET_HIT" if (os_m["sharpe"] or -1e9) >= args.target_os_sharpe else "EVALUATED"

    return IterationResult(
        n=n, composite_id=composite_id, status=status,
        reason="ok" if status == "EVALUATED" else "OS Sharpe target hit",
        is_sharpe=is_m["sharpe"], os_sharpe=os_m["sharpe"],
        is_return=is_m["return"], os_return=os_m["return"],
        is_dd=is_m["max_dd"], os_dd=os_m["max_dd"],
        n_members=n_members,
        notes=note_value or "",
    )


# ---------- driver ----------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--target-os-sharpe", type=float, default=2.0)
    parser.add_argument("--max-iterations", type=int, default=500)
    parser.add_argument("--wall-clock-seconds", type=int, default=28800)
    parser.add_argument("--llm-timeout", type=int, default=600)
    parser.add_argument("--max-consecutive-errors", type=int, default=5)
    parser.add_argument("--model", default="opus",
                        help="claude CLI model alias or id (e.g. 'opus', 'sonnet', 'claude-opus-4-7')")
    args = parser.parse_args()

    ITERATIONS_DIR.mkdir(parents=True, exist_ok=True)
    state = load_state(args.run_id, args.target_os_sharpe, args.max_iterations)
    save_state(state)

    t_started = time.monotonic()
    consecutive_errors = 0

    while True:
        elapsed = time.monotonic() - t_started
        if elapsed >= args.wall_clock_seconds:
            state["status"] = "exhausted"
            state["stop_reason"] = "wall clock"
            save_state(state)
            print(f"[harness] wall-clock budget exhausted ({elapsed:.0f}s)", flush=True)
            return 0
        if state["iterations_run"] >= args.max_iterations:
            state["status"] = "exhausted"
            state["stop_reason"] = "iteration budget"
            save_state(state)
            print(f"[harness] iteration budget exhausted", flush=True)
            return 0

        n = next_iteration_n(state)
        print(f"\n[harness] === iteration {n:03d} (elapsed {elapsed:.0f}s) ===", flush=True)
        t0 = time.monotonic()
        result = run_iteration(state, args)
        dt = time.monotonic() - t0
        print(f"[harness] iter {n:03d} {result.status} ({dt:.0f}s) → "
              f"{result.composite_id} IS={result.is_sharpe} OS={result.os_sharpe} "
              f"reason={result.reason[:140]}", flush=True)

        state["iterations_run"] = n
        if result.status == "INVALID":
            state["iterations_invalid"] += 1
            consecutive_errors = 0  # INVALID is agent's fault, not infra
        elif result.status == "ERRORED":
            consecutive_errors += 1
        else:
            state["iterations_evaluated"] += 1
            consecutive_errors = 0
            update_leaderboard(state, result)
            append_log_row(args.run_id, result)
        state.setdefault("history", []).append({
            "n": result.n,
            "composite_id": result.composite_id,
            "status": result.status,
            "reason": result.reason,
            "is_sharpe": result.is_sharpe,
            "os_sharpe": result.os_sharpe,
            "n_members": result.n_members,
            "elapsed_seconds": dt,
        })
        state["history"] = state["history"][-200:]
        state["elapsed_seconds"] = int(time.monotonic() - t_started)
        save_state(state)

        if result.status == "TARGET_HIT":
            state["status"] = "target_hit"
            save_state(state)
            print(f"\n[harness] *** TARGET HIT *** OS Sharpe {result.os_sharpe:.3f} ≥ "
                  f"{args.target_os_sharpe} by {result.composite_id}", flush=True)
            return 0
        if consecutive_errors >= args.max_consecutive_errors:
            state["status"] = "failed"
            state["stop_reason"] = f"{consecutive_errors} consecutive infra errors"
            save_state(state)
            print(f"[harness] aborting — {consecutive_errors} consecutive infra errors", flush=True)
            return 2


if __name__ == "__main__":
    sys.exit(main())
