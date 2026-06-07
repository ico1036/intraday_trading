# Post Analysis: xs_factor_closetohigh10d_fwd_c10

- kind: `alpha`
- run_id: `run_2026_05_full531_rerun_backtests`
- id: `xs_factor_closetohigh10d_fwd_c10`
- status: `IS_FAIL`
- family: `xs_factor_close_to_high_10d_fwd_c10`
- artifact_dir: `/Users/jj_home/Git/intraday_trading/archive/run_2026_05_full531_rerun_backtests/alphas/xs_factor_closetohigh10d_fwd_c10`
- source_notes: `['research/notes/xs_factor_zoo.md']`
- alpha_cell: `{"bar": "TIME", "exit": "signal_flip", "horizon": "multi_day", "idea_family": "xs_factor_close_to_high_10d_fwd_c10", "transform": "rolling_rank", "universe": "basket_full"}`

## Implemented Strategy
xs_factor_closetohigh10d_fwd_c10 — auto-generated XS factor. Signal: close_to_high_10d direction=fwd concentration=0.1 Cross-sectional rank of ``_compute_score`` over the eligible universe each emit bar, top/bottom concentration_pct legs.

This section was auto-backfilled from archived source metadata and should be tightened manually before using it as high-confidence research memory.

## IS Performance State
- IS Sharpe: `-0.14247886790195283`
- IS Return: `-0.28094417535260324` (-28.09%)
- IS Max Drawdown: `-0.520272804217053` (-52.03%)
- IS Trades: `15905`
- IS Win Rate: `0.5219742219427853`
- PnL bps simple: `446.45535262296346`
- PnL bps notional weighted: `-14.741490787028532`
- Artifact counts: `{"equity_rows": 373816, "trades_rows": 108626, "weights_rows": 107797}`

The current state is recorded as an IS-only artifact summary. This report does not use OS/full-period results for generation guidance.

## Goal Fit
No run-specific goal fit was inferred during automatic backfill. A future loop should compare this strategy against `research/wiki/goals/<run_id>.md` before reuse.

## Current Interpretation
alpha `xs_factor_closetohigh10d_fwd_c10` is indexed as family `xs_factor_close_to_high_10d_fwd_c10` with status `IS_FAIL`; IS Sharpe -0.1425, return -28.09%, max drawdown -52.03%, trades 15905. Treat this as a retrieval description, not a recommendation to clone the strategy.

## Reuse Notes
- Auto-backfilled entry. Prefer mechanism-level reuse only.
- Do not infer best parameters from this report.
- Inspect source, weights, and IS PnL before using this as context for a new attempt.
