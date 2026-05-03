# Exploration Runbook

This runbook is for the markdown-driven alpha exploration workflow described in
`AGENT.md`.

## Initialize

```bash
uv run python scripts/agent/exploration.py init archive/<run_id>
```

This creates:

```text
archive/<run_id>/
  alphas/
  coverage_map.json
  alpha_index.csv
```

## Choose Cells

```bash
uv run python scripts/agent/exploration.py next-cells archive/<run_id> --limit 10
```

Choose one returned cell. Do not choose by prior alpha performance.

## Implement One Alpha

Create:

```text
archive/<run_id>/alphas/<alpha_id>/search_cell.json
src/intraday/strategies/multi/<alpha>.py
tests/strategies/test_<alpha>.py
```

Then run focused tests and a backtest. Backtest output must be saved into:

```text
archive/<run_id>/alphas/<alpha_id>/
```

## Record

```bash
uv run python scripts/agent/exploration.py record archive/<run_id> <alpha_id>
```

`record` reads `search_cell.json`, `metrics.json`, and `weights.parquet`. It
updates:

- `coverage_map.json`
- `alpha_index.csv`

The command fails if the search cell is malformed or required artifacts are
missing.

## Continue

Ask for another underexplored cell and repeat. Do not refine high-performing
alphas during exploration. Selection and composite construction happen after
coverage generation.
