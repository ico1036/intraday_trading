# Claude Code Instructions

For any quant research, alpha generation, composite alpha construction, or
ad-hoc analysis task: read `RESEARCH.md` first. It is the project's research
philosophy — task-agnostic principles that apply regardless of which workflow
follows.

Read `AGENT.md` before generating individual alphas.
Read `archive/<run_id>/splits.json` before attempts. Use IS for development;
run OS only after strategy code is frozen.

Use the simple markdown workflow:

1. Pick one search-space cell different from recent `archive/<run_id>/LOG.md`
   entries.
2. Copy `src/intraday/strategies/multi/_alpha_template.py`.
3. Implement one strategy in `src/intraday/strategies/multi/<alpha>.py`.
4. Add focused tests in `tests/strategies/test_<alpha>.py`.
5. Run focused tests.
6. Run IS backtest into `archive/<run_id>/alphas/<alpha_id>/is/`.
7. Freeze the strategy code, then run OS backtest into
   `archive/<run_id>/alphas/<alpha_id>/os/`.
8. Verify both splits with `uv run python scripts/tools/verify_artifact.py ... --json`
   and inspect `weights.parquet` values.
9. Label IS/OS drift with `uv run python scripts/tools/validate_is_os.py ... --json`.
10. Append a short entry to `archive/<run_id>/LOG.md`.

Do not use or recreate a Python research orchestrator loop. During exploration,
do not refine prior winners; move to a different area of the search space.
OS validation labels distribution shift only. Do not modify the strategy based
on OS results.

Editable surface during alpha generation:

- `src/intraday/strategies/multi/<alpha>.py` (never `_alpha_template.py` or `__init__.py`)
- `tests/strategies/test_<alpha>.py`
- `archive/<run_id>/alphas/<alpha_id>/**`
- `archive/<run_id>/LOG.md`
- `archive/<run_id>/alpha_index.csv`

Do not edit framework code unless explicitly asked. Do not propose or take
forbidden actions listed in `AGENT.md` (data downloads, fee changes,
framework edits, etc.). After every attempt run:

```
uv run python scripts/governance/check.py --json
```

A non-zero exit means the editable surface or universe consistency was
violated; revert the disallowed changes before continuing.

Default universe is in `archive/<run_id>/splits.json` under `"universe"`;
pass it to `--symbols` when running backtests.

## Composite alpha workflow (agentic exploration)

Composites combine archived per-alpha weight streams into a single weight
stream: `W_comp[t,s] = Σ_a c_a · W_a[t,s]`, row-L1 normalized. The composite
is itself an alpha — own IS+OS backtest, manifest, dashboard card, live tick.

Mirror of the individual-alpha workflow: each attempt is one *combination
idea* — selection rule + optimization rule together. Do NOT pre-enumerate
methods. Each attempt explores a new cell of the (selection, optimization)
search space — read the literature, propose a fresh idea, implement, log,
move to a different region next time.

Examples of *one* combination idea (each is a single attempt):
- top-K by IS Sharpe + 1/N
- correlation-dedup (threshold 0.7) + IS-Sharpe-weighted
- PC1-residual β-neutral with k-medoids cluster centroid selection
- Lopez de Prado hierarchical risk parity (HRP) over IS daily returns
- Ledoit-Wolf shrinkage + Markowitz max-Sharpe with no-short constraint
- robust Mahalanobis-distance dedup + rolling 252d refit
- IC-stability filtered (rolling IC std < threshold) + Black-Litterman tilt

None of those is the "official" method. They are illustrations of the
combinatorial scope. The actual research happens during each attempt:
*read what worked in cross-sectional equity / crypto / academic literature
for selecting and weighting alphas, pick something new, try it.*

Editable surface during composite generation:
- `src/intraday/composites/<composite_id>.py` (never `_composite_template.py`,
  `_runner.py`, `_optim_helpers.py`, `__init__.py`)
- `archive/<run_id>/composites/<composite_id>/**`
- `archive/<run_id>/composites/LOG.md`

Eleven-step workflow (mirrors the individual-alpha 10-step):

1. Survey `archive/<run_id>/composites/LOG.md` for the *idea families* already
   attempted. Pick a region of the (selection × optimization) space that has
   not been recently tried.
2. Copy `src/intraday/composites/_composite_template.py` to
   `src/intraday/composites/<composite_id>.py`. Choose `composite_id` to
   reflect the idea (e.g. `hrp_top30_corrdedup`, `bl_view_blend_q4`).
3. Implement `select_members(alpha_index)` — filter on IS-only metrics
   (`alpha_index` has all `os_*` columns stripped; referencing them raises).
4. Implement `member_weights(member_ids, alpha_index)` — return
   `{alpha_id: coefficient}`. Magnitudes are relative; `_runner.py` row-L1
   normalizes so `Σ_s |W_comp[t,s]| ≤ 1`. Helpers in `_optim_helpers.py`
   (`correlation_dedup`, `member_signs_ic`, `apply_signs`, `shrink_cov`,
   `load_member_is_returns`, etc.) are free utilities — use any subset.
5. Set `COMPOSITION_NOTE` to a short label describing the idea, so the
   dashboard / LOG can group attempts. Set `COMPOSITE_ID` to match the file.
6. Run IS backtest:
   ```
   uv run python -m intraday.composites.<composite_id> --run-id <run_id> --no-os
   ```
   Inspect `archive/<run_id>/composites/<composite_id>/is/` — Sharpe,
   return, DD, max_row_l1.
7. Inspect `member_gross_daily.parquet` — no single member should dominate
   (>50% of total activity is a red flag for hidden concentration).
8. Freeze the composite (the selection + coefficients are already locked in
   `manifest.json`), then run OS:
   ```
   uv run python -m intraday.composites.<composite_id> --run-id <run_id>
   ```
   OS backtest replays the frozen weights — selection is never recomputed.
9. Verify the new composite shows up on the dashboard's Composites tab
   (auto-discovery via `composites/<id>/manifest.json`).
10. Compare IS vs OS metrics. Sharpe degradation < 0.7 ⇒ overfit pool.
    Negative OS return ⇒ REJECT — document in LOG.md as a failed attempt.
    Do NOT modify the composite based on OS results.
11. Append a short entry to `archive/<run_id>/composites/LOG.md`:
    `composite_id | idea family | n_members | IS Sh | OS Sh | OS ret | verdict`.
    Run `uv run python scripts/governance/check.py --json`.

IS/OS windows are inherited from `archive/<run_id>/splits.json` and match
the per-alpha windows exactly — `_runner.py` passes the same start/end to
`backtest.py`. Do not override.

Look-ahead safeguards (enforced by `_runner.py`):
- `alpha_index` passed to `select_members` / `member_weights` has all `os_*`
  columns dropped.
- Selected list and coefficients are frozen in `manifest.json` before any OS
  backtest runs.
- OS backtest is a pure replay of `weights.parquet`; the strategy code does
  not re-select or re-fit.

Forbidden during composite work:
- Reading `archive/<run>/alphas/<aid>/os/` or composite `os/` while iterating
  on selection — that is OS contamination.
- Re-running OS with different member selection — that turns OS into an
  in-sample tuning knob.
- Modifying `_runner.py` or `_optim_helpers.py` for one-off composite tweaks.
- Pre-enumerating a fixed list of methods. Each attempt is its own research
  question; if you find yourself running the "next method on the list" you
  are doing parameter-sweep, not exploration.

## Strategy source preservation (mandatory)

Every backtest writes `strategy_source.py` + `strategy_source.meta.json`
into the archive directory next to `metrics.json`. The archive is the
permanent record — once an alpha is backtested, the source that produced
it must be reconstructable from the archive alone, independent of git
history or the current working tree.

`scripts/tools/backtest.py` does this automatically. Never delete or
modify these snapshot files; they are the audit trail. If the working
tree loses a strategy file (refactor, cleanup, etc.) the archive copy
is still authoritative for reproducing that alpha.

To backfill archives that predate this guarantee:

```
uv run python scripts/governance/backfill_strategy_source.py \
    --archive archive/<run_id>
```

The script restores sources from the working tree first, then from
`git rev-list --all` (walks past deletion commits). Run after any bulk
strategy-file cleanup.
