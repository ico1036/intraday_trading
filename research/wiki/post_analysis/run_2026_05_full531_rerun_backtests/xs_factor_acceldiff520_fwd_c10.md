# Post Analysis: xs_factor_acceldiff520_fwd_c10

- kind: `alpha`
- run_id: `run_2026_05_full531_rerun_backtests`
- id: `xs_factor_acceldiff520_fwd_c10`
- status: `IS_FAIL`
- family: `xs_factor_accel_diff_5_20_fwd_c10`
- artifact_dir: `/Users/jj_home/Git/intraday_trading/archive/run_2026_05_full531_rerun_backtests/alphas/xs_factor_acceldiff520_fwd_c10`
- source_notes: `['research/notes/xs_factor_zoo.md']`
- alpha_cell: `{"bar": "TIME", "exit": "signal_flip", "horizon": "multi_day", "idea_family": "xs_factor_accel_diff_5_20_fwd_c10", "transform": "rolling_rank", "universe": "basket_full"}`

## Implemented Strategy
xs_factor_acceldiff520_fwd_c10 — auto-generated XS factor. Signal: accel_diff_5_20 direction=fwd concentration=0.1 Cross-sectional rank of ``_compute_score`` over the eligible universe each emit bar, top/bottom concentration_pct legs.

This section was auto-backfilled from archived source metadata and should be tightened manually before using it as high-confidence research memory.

## IS Performance State
- IS Sharpe: `-0.611203154314223`
- IS Return: `-0.7010388556553407` (-70.10%)
- IS Max Drawdown: `-0.7359152833023274` (-73.59%)
- IS Trades: `13839`
- IS Win Rate: `0.48905267721656187`
- PnL bps simple: `-1504.4791295432597`
- PnL bps notional weighted: `-21.651671554148056`
- Artifact counts: `{"equity_rows": 373816, "trades_rows": 98512, "weights_rows": 97294}`

The current state is recorded as an IS-only artifact summary. This report does not use OS/full-period results for generation guidance.

## Goal Fit
No run-specific goal fit was inferred during automatic backfill. A future loop should compare this strategy against `research/wiki/goals/<run_id>.md` before reuse.

## Current Interpretation
alpha `xs_factor_acceldiff520_fwd_c10` is indexed as family `xs_factor_accel_diff_5_20_fwd_c10` with status `IS_FAIL`; IS Sharpe -0.6112, return -70.10%, max drawdown -73.59%, trades 13839. Treat this as a retrieval description, not a recommendation to clone the strategy.

## Reuse Notes
- Auto-backfilled entry. Prefer mechanism-level reuse only.
- Do not infer best parameters from this report.
- Inspect source, weights, and IS PnL before using this as context for a new attempt.
