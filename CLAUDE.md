# Claude Code Instructions

Read `AGENT.md` before generating alphas.

Use the simple markdown workflow:

1. Pick one search-space cell different from recent `archive/<run_id>/LOG.md`
   entries.
2. Copy `src/intraday/strategies/multi/_alpha_template.py`.
3. Implement one strategy in `src/intraday/strategies/multi/<alpha>.py`.
4. Add focused tests in `tests/strategies/test_<alpha>.py`.
5. Run focused tests.
6. Backtest into `archive/<run_id>/alphas/<alpha_id>/`.
7. Inspect artifact files and `weights.parquet` values.
8. Append a short entry to `archive/<run_id>/LOG.md`.

Do not use or recreate a Python research orchestrator loop. During exploration,
do not refine prior winners; move to a different area of the search space.

Editable surface during alpha generation:

- `src/intraday/strategies/multi/<alpha>.py`
- `tests/strategies/test_<alpha>.py`
- `archive/<run_id>/alphas/<alpha_id>/**`
- `archive/<run_id>/LOG.md`

Do not edit framework code unless explicitly asked.
