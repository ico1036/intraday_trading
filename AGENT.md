# Alpha Exploration Agent

This repository uses a markdown-driven agent workflow. Do not run a Python
research orchestrator loop. Read this file, pick one underexplored search-space
cell, implement one alpha, verify its artifacts, record coverage, then move to
another cell when asked to continue.

## Objective

Generate many independent long/short alpha ledgers for crypto intraday trading.
The durable product is `weights.parquet`, not a strategy write-up and not a
winner that should be refined.

This is a search-space coverage problem, not an evolutionary optimization
problem.

## Exploration Policy

- Do not imitate the best prior alpha.
- Do not mutate the current winner.
- Do not add filters to a previously successful strategy just because it
  worked.
- Do not use prior metrics to choose similar features or thresholds.
- Use prior results only to avoid duplicates, avoid invalid framework features,
  and update coverage counts.
- Bad performance is not a reason to repair an alpha. Archive it and move to a
  different search-space cell.
- Repair only syntax/runtime errors, broken tests, invalid artifact schemas, or
  framework-contract violations.

## Allowed Edit Surface

You may edit:

- `src/intraday/strategies/multi/<alpha>.py`
- `tests/strategies/test_<alpha>.py`
- `archive/<run_id>/alphas/<alpha_id>/**`
- `archive/<run_id>/coverage_map.json`
- `archive/<run_id>/alpha_index.csv`

You must not edit during alpha generation:

- `src/intraday/backtest/**`
- `src/intraday/multi_forward_runner.py`
- `src/intraday/data/**`
- `src/intraday/strategy.py`
- `config/**`
- framework docs or scripts

If framework code appears wrong, stop alpha generation and report the blocker.

## Required Strategy Contract

- Copy `src/intraday/strategies/multi/_alpha_template.py`.
- Keep `symbols: list[str]` in the constructor.
- `symbols=["BTCUSDT"]` is the single-coin case.
- Return `PortfolioOrder` from `generate_order`.
- Prefer `Order(weight=...)` targets so `weights.parquet` is immediately useful
  for composite strategies.
- Do not write artifact files from strategy code. Runners own artifacts.

## Search Cell

Before implementing an alpha, write:

```text
archive/<run_id>/alphas/<alpha_id>/search_cell.json
```

It must contain one value for every axis documented in
`docs/agent/SEARCH_SPACE.md`.

Pick cells with low coverage. Use:

```bash
uv run python scripts/agent/exploration.py next-cells archive/<run_id>
```

## One Alpha Pass

For each independent alpha:

1. Pick an underexplored search cell.
2. Create `archive/<run_id>/alphas/<alpha_id>/search_cell.json`.
3. Implement `src/intraday/strategies/multi/<alpha>.py`.
4. Add focused tests in `tests/strategies/test_<alpha>.py`.
5. Run the strategy tests.
6. Run a backtest with `scripts/run_manual_backtest.py` or the MCP backtest
   tool, saving into `archive/<run_id>/alphas/<alpha_id>/`.
7. Verify artifact contract:
   - `manifest.json`
   - `weights.parquet`
   - `metrics.json`
   - `summary.json`
   - `summary.csv`
   - `equity_curve.parquet`
   - `trades.parquet`
   - `events.parquet`
   - `backtest_report.md`
8. Inspect `weights.parquet`, not just file existence:
   - required columns exist
   - `target_weight` is finite
   - signed long/short direction matches the strategy intent
   - timestamps are decision times, not future execution times
9. Record the alpha:

```bash
uv run python scripts/agent/exploration.py record archive/<run_id> <alpha_id>
```

10. Move to a different underexplored cell. Do not refine the same idea unless
    the artifact is invalid.

## Completion

Stop only when the user-specified run budget is exhausted or the requested
number of valid alpha artifact directories exists.

Completion is not based on Sharpe, PnL, or finding a winner. The purpose of
this phase is breadth: many valid, reusable alpha ledgers.

Composite strategy construction is a separate phase that reads saved
`weights.parquet` files. Do not rerun child strategies while composing.
