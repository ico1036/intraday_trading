# Post Analysis: xs_factor_bbwidth20d_rev_c05

- kind: `alpha`
- run_id: `run_2026_05_full531_rerun_backtests`
- id: `xs_factor_bbwidth20d_rev_c05`
- status: `IS_FAIL`
- family: `xs_factor_bb_width_20d_fwd_c10`
- artifact_dir: `/Users/jj_home/Git/intraday_trading/archive/run_2026_05_full531_rerun_backtests/alphas/xs_factor_bbwidth20d_rev_c05`
- source_notes: `['research/notes/xs_factor_zoo.md']`
- alpha_cell: `{"bar": "TIME", "exit": "signal_flip", "horizon": "multi_day", "idea_family": "xs_factor_bb_width_20d_fwd_c10", "transform": "rolling_rank", "universe": "basket_full"}`

## Implemented Strategy
xs_factor_bbwidth20d_fwd_c10 — auto-generated XS factor. Signal: bb_width_20d direction=fwd concentration=0.1 Cross-sectional rank of ``_compute_score`` over the eligible universe each emit bar, top/bottom concentration_pct legs.

This section was auto-backfilled from archived source metadata and should be tightened manually before using it as high-confidence research memory.

## IS Performance State
- IS Sharpe: `-0.4976476755623525`
- IS Return: `-0.9424490845531771` (-94.24%)
- IS Max Drawdown: `-1.0812893401834052` (-108.13%)
- IS Trades: `5352`
- IS Win Rate: `0.5332585949177877`
- PnL bps simple: `1761.6008851275799`
- PnL bps notional weighted: `-84.02149029164552`
- Artifact counts: `{"equity_rows": 373816, "trades_rows": 38590, "weights_rows": 38628}`

The current state is recorded as an IS-only artifact summary. This report does not use OS/full-period results for generation guidance.

## Goal Fit
No run-specific goal fit was inferred during automatic backfill. A future loop should compare this strategy against `research/wiki/goals/<run_id>.md` before reuse.

## Current Interpretation
alpha `xs_factor_bbwidth20d_rev_c05` is indexed as family `xs_factor_bb_width_20d_fwd_c10` with status `IS_FAIL`; IS Sharpe -0.4976, return -94.24%, max drawdown -108.13%, trades 5352. Treat this as a retrieval description, not a recommendation to clone the strategy.

## Reuse Notes
- Auto-backfilled entry. Prefer mechanism-level reuse only.
- Do not infer best parameters from this report.
- Inspect source, weights, and IS PnL before using this as context for a new attempt.
