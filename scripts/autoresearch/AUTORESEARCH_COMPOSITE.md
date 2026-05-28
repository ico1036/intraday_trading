# Autoresearch — Composite Alpha Loop

A Karpathy-style autonomous research loop for composite-alpha discovery.
The orchestrator drives an LLM agent (via `claude` CLI) through repeated
attempts; each attempt is one composite idea. The official backtester is
the **only** source of truth — agent claims are never trusted.

This file is the **human direction** layer (mirrors `program.md` in
Karpathy's autoresearch). Treat it as immutable contract.

---

## Mission

For a given `--run-id` and `--target-os-sharpe T`, run autonomous attempts
until either:

- a composite achieves `os.metrics.json.sharpe ≥ T`, or
- `--max-iterations` is exhausted, or
- `--wall-clock-seconds` budget elapses.

Each attempt = one fresh idea = one new file under
`src/intraday/composites/auto_<NNN>_<slug>.py`. No mutation of previous
attempts. No re-running OS with different selections.

Default target: `T = 2.0` (OS daily Sharpe on the full archive universe,
real fees + slippage via `PrecomputedWeightsStrategy`).

---

## Three-layer contract (Karpathy pattern)

| Layer | What it is | Who edits |
|---|---|---|
| **Immutable evaluator** | `scripts/tools/backtest.py`, `src/intraday/composites/_runner.py`, `_optim_helpers.py`, `_composite_template.py`, `_alpha_template.py`, `__init__.py`, all archive data | **NEVER** the agent. Harness rejects any diff outside the sandbox. |
| **Agent sandbox** | `src/intraday/composites/auto_<NNN>_<slug>.py` (one file per iteration) | Agent writes; harness validates via AST + sandbox-policy before any backtest. |
| **Human direction** | This file, the prompt template, run/target flags | Human edits between sessions. Agent reads but never modifies. |

The agent never invokes the backtester directly, never writes to archive,
never runs git commands, never installs packages. It writes **one Python
file**. The harness alone runs evaluation and logs the truth.

---

## Editable surface (agent's only write target)

For attempt number `N` (e.g. `017`), the only file the agent may produce
is:

```
src/intraday/composites/auto_<NNN>_<slug>.py
```

where:

- `<NNN>` = zero-padded iteration index assigned by the harness
- `<slug>` = snake_case ≤ 40 chars, agent's choice, must reflect the idea
- The file must define **exactly** the four required top-level names
  required by `_composite_template.py`:
  - `COMPOSITE_ID: str` (must equal `auto_<NNN>_<slug>`)
  - `COMPOSITION_NOTE: str` (≤ 80 chars, one-line idea label)
  - `def select_members(alpha_index: pd.DataFrame) -> list[str]`
  - `def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]`
- Plus the standard `main()` and `if __name__ == "__main__":` block (the
  harness ignores these but they must be present so the file is also
  manually runnable via `uv run python -m intraday.composites.<id>`).

**Anything else in the file is invalid and rejected before backtest.**

---

## Sandbox policy (AST-enforced, pre-backtest)

The harness parses the file with `ast` and rejects any of the following:

1. **Forbidden imports.** Allow-list only:
   - `from __future__ import annotations`
   - stdlib: `argparse`, `math`, `json`, `dataclasses`, `typing`, `itertools`,
     `functools`, `collections`
   - third-party: `numpy as np`, `pandas as pd`, `scipy.linalg`,
     `scipy.cluster.hierarchy`, `scipy.spatial.distance`, `scipy.stats`,
     `scipy.optimize`
   - project: `intraday.composites._runner` (must import only `build_and_backtest`),
     `intraday.composites._optim_helpers` (any name)
   Anything else (`os`, `sys`, `subprocess`, `pathlib`, `shutil`, `socket`,
   `urllib`, `requests`, `pickle`, `joblib`, `sklearn`, `torch`, `tensorflow`,
   etc.) → REJECT.

2. **Forbidden calls / names.** AST walk rejects any reference to:
   `open`, `exec`, `eval`, `compile`, `__import__`, `globals`, `locals`,
   `setattr`, `getattr` with non-literal attr, `Path`, `os.*`, `sys.*`,
   `subprocess.*`, `shutil.*`, `socket.*`, `urllib.*`, `requests.*`,
   `pickle.*`, `joblib.*`, `__builtins__`.

3. **Forbidden attribute lookups** on disallowed roots (see above).

4. **No string literals matching paths** outside the composite directory
   (regex: `archive/.*/(alphas|composites)/[^/]+/(is|os)/os/` etc. — OS
   weight files are loaded by `_runner.py` only; user code must not touch
   the OS split directly).

5. **Required structure check:** the four required top-level names exist
   with the right kind (constant / function), `COMPOSITE_ID` constant
   value equals the harness-assigned id, and `select_members` /
   `member_weights` have the exact signatures shown in the template.

A rejected file is **deleted** and the iteration is logged as `INVALID`.
The agent is told the rejection reason and a new attempt begins from a
different angle.

---

## What the agent IS allowed to do inside the sandbox

- Read `alpha_index` (passed in) — `os_*` columns already stripped by
  `_runner.load_alpha_index_is_only`.
- Call any helper in `_optim_helpers`: `correlation_dedup`,
  `member_signs_ic`, `member_signs`, `apply_signs`, `shrink_cov`,
  `select_is_submittable`, `select_all_alphas`, `member_is_sharpe`,
  `member_ic`, `load_member_is_returns`, `normalize_coefficients`.
- Use numpy/scipy for: eigendecomposition, denoising via Marchenko-Pastur,
  Neumann-series inverse, hierarchical clustering, scipy.optimize for
  convex sub-problems (NCO inner/outer), risk parity Newton iteration,
  Ledoit-Wolf optimal shrinkage closed form, etc.
- Compute its own auxiliary statistics from IS data (returns matrix R
  built via `load_member_is_returns`).

## What the agent IS NOT allowed to do (even within the sandbox)

- Touch the OS split of any alpha (load `os/weights.parquet`, read
  `os/metrics.json`, etc.). The `_runner.py` already strips these from
  `alpha_index` and the AST guard blocks path strings.
- Pre-enumerate / sweep parameters: each attempt is one combination idea,
  not a grid search dressed as composites.
- Re-implement the backtester or fees / slippage.
- Reference a previous `auto_*.py` (no copy-paste-then-tweak; each attempt
  is its own idea).

---

## Loop protocol (one iteration)

```
1. Harness reads state.json, LOG.md tail, alpha_index summary.
2. Harness builds prompt: mission + literature menu + tried-ideas table
   + alpha-pool summary + last K rejection reasons.
3. Harness invokes claude CLI in print mode with strict timeout.
4. Harness extracts python file from response (between explicit markers).
5. Harness validates: AST policy, structural check, name match.
   - Reject → log INVALID, delete file, next iteration.
6. Harness writes file to src/intraday/composites/auto_NNN_slug.py.
7. Harness runs: uv run python -m intraday.composites.auto_NNN_slug \
                 --run-id <run_id>
   (this is the canonical backtester — IS + OS via _runner.py)
8. Harness parses archive/<run_id>/composites/auto_NNN_slug/is/metrics.json
   and os/metrics.json. If either missing → INVALID, log, next.
9. Harness appends row to:
   - scripts/autoresearch/state.json (running stats, best so far)
   - archive/<run_id>/composites/LOG.md (one row, same schema as manual)
   - scripts/autoresearch/iterations/NNN.log (full LLM prompt + response
     + backtest stdout/stderr)
10. If os.sharpe ≥ target → mark SUCCESS, exit 0.
    Else continue to next iteration.
```

The harness is the only entity that:
- writes/deletes files in the sandbox,
- runs the backtester,
- writes to `state.json` / `LOG.md` / `iterations/`,
- decides stop conditions.

The agent only produces text (one python file).

---

## Output protocol (agent → harness)

The agent's response MUST contain exactly one fenced code block of the
form:

````
```python COMPOSITE_FILE
# ... entire file content ...
```
````

The harness extracts the first such block. No other parsing. If absent or
malformed → INVALID.

Free-form text before/after the block (rationale, citations) is preserved
in `iterations/NNN.log` for human review but ignored by the validator.

---

## Logging schema

Each iteration appends one row to
`archive/<run_id>/composites/LOG.md` matching the existing manual
schema, with `composite_id = auto_NNN_<slug>` and `notes` carrying the
short LLM-supplied rationale (≤ 120 chars).

`scripts/autoresearch/state.json`:

```json
{
  "run_id": "...",
  "target_os_sharpe": 2.0,
  "started_utc": "...",
  "elapsed_seconds": 0,
  "iterations_run": 0,
  "iterations_invalid": 0,
  "iterations_evaluated": 0,
  "best": {
    "composite_id": null,
    "os_sharpe": null,
    "os_return": null,
    "is_sharpe": null,
    "n_members": null
  },
  "leaderboard": [
    {"composite_id": "...", "os_sharpe": 1.42, "is_sharpe": 1.87, "n_members": 23}
  ],
  "status": "running | target_hit | exhausted | failed"
}
```

Leaderboard is the top 10 attempts by OS Sharpe.

---

## Stop conditions (any one triggers exit)

- `os_sharpe ≥ target_os_sharpe` for any one attempt → `status: target_hit`, exit 0.
- `iterations_run ≥ max_iterations` → `status: exhausted`, exit 0.
- `time.monotonic() - started ≥ wall_clock_seconds` → `status: exhausted`, exit 0.
- Three consecutive backtest infrastructure failures (e.g. `_runner` raises before
  any `metrics.json` written) → `status: failed`, exit 2.

---

## Reproducibility

- Every iteration's full LLM prompt + response goes to
  `scripts/autoresearch/iterations/NNN.{prompt.md,response.md,backtest.log}`.
- The composite file lives at `src/intraday/composites/auto_NNN_slug.py`
  (kept after success or failure — used as the audit trail).
- `archive/<run_id>/composites/auto_NNN_slug/strategy_source.py` is
  written automatically by `backtest.py` for both IS and OS splits.

A successful attempt can therefore be reproduced by anyone re-running
the composite module directly.
