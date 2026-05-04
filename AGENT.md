# Alpha Exploration

Use this repo like a small autoresearch workspace. These instructions are plain
markdown so they work in Codex, Claude Code, or any coding agent. Do not run a
research orchestrator loop by default. Pick one idea, implement it, test it,
backtest it, save the alpha ledger, write down what happened, then move to a
different idea.

## Goal

Generate many independent intraday long/short alpha ledgers. The durable output
is `weights.parquet`.

Exploration is breadth-first. Do not refine winners during alpha generation.
Bad performance is archived, not repaired. Repair only broken code, broken
tests, or invalid artifact output.

## Editable Surface

Edit only:

- `src/intraday/strategies/multi/<alpha>.py`
- `tests/strategies/test_<alpha>.py`
- `archive/<run_id>/alphas/<alpha_id>/**`
- `archive/<run_id>/LOG.md`

Do not edit framework code unless explicitly asked.

## One Attempt

1. Choose a search-space cell that is different from recent attempts.
2. Copy `src/intraday/strategies/multi/_alpha_template.py`.
3. Implement one strategy in `src/intraday/strategies/multi/<alpha>.py`.
4. Add focused tests in `tests/strategies/test_<alpha>.py`.
5. Run the focused tests.
6. Run `scripts/tools/backtest.py` into
   `archive/<run_id>/alphas/<alpha_id>/`.
7. Run `scripts/tools/verify_artifact.py` and inspect `weights.parquet`.
8. Append one short entry to `archive/<run_id>/LOG.md`.

## Deterministic Commands

Backtest:

```bash
uv run python scripts/tools/backtest.py \
  --strategy <ClassName> \
  --symbols BTCUSDT ETHUSDT \
  --data-path data/futures_ticks \
  --start "2025-03-01 00:00:00" \
  --end "2025-03-07 23:59:59" \
  --bar-type TIME \
  --bar-size 60 \
  --output-dir archive/<run_id>/alphas/<alpha_id> \
  --json
```

Verify:

```bash
uv run python scripts/tools/verify_artifact.py \
  archive/<run_id>/alphas/<alpha_id> \
  --json
```

## Search Space

Use combinations of:

- bar: `TIME`, `VOLUME`, `DOLLAR`, `TICK`
- family: `momentum`, `reversal`, `volatility`, `volume_pressure`,
  `dispersion`, `correlation_break`, `lead_lag`, `funding`, `regime_transition`
- transform: `raw`, `z_score`, `percentile`, `rolling_rank`, `ewma_residual`
- horizon: `ultra_short`, `intraday`, `session`, `multi_day`
- universe: `single`, `pair`, `basket_topk`
- exit: `time_stop`, `signal_flip`, `trailing`, `vol_stop`, `neutral_zone`

Do not select the next idea from the best prior result. Select it from an
underexplored area.
