# Claude Code Instructions

Read `AGENT.md` before generating alphas.
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
