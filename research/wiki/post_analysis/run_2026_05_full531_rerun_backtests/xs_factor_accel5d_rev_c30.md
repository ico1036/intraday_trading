# Post Analysis: xs_factor_accel5d_rev_c30

- kind: `alpha`
- run_id: `run_2026_05_full531_rerun_backtests`
- id: `xs_factor_accel5d_rev_c30`
- status: `IS_FAIL`
- family: `xs_factor_accel_5d_fwd_c10`
- artifact_dir: `/Users/jj_home/Git/intraday_trading/archive/run_2026_05_full531_rerun_backtests/alphas/xs_factor_accel5d_rev_c30`
- source_notes: `['research/notes/xs_factor_zoo.md']`
- alpha_cell: `{"bar": "TIME", "exit": "signal_flip", "horizon": "multi_day", "idea_family": "xs_factor_accel_5d_fwd_c10", "transform": "rolling_rank", "universe": "basket_full"}`

## Implemented Strategy
xs_factor_accel5d_fwd_c10 — auto-generated XS factor. Signal: accel_5d direction=fwd concentration=0.1 Cross-sectional rank of ``_compute_score`` over the eligible universe each emit bar, top/bottom concentration_pct legs.

This section was auto-backfilled from archived source metadata and should be tightened manually before using it as high-confidence research memory.

## IS Performance State
- IS Sharpe: `-0.8694217265679356`
- IS Return: `-0.330123809145584` (-33.01%)
- IS Max Drawdown: `-0.37076243143839105` (-37.08%)
- IS Trades: `50409`
- IS Win Rate: `0.48169969648277094`
- PnL bps simple: `-404.62904451318155`
- PnL bps notional weighted: `-4.4182251507629005`
- Artifact counts: `{"equity_rows": 373816, "trades_rows": 348635, "weights_rows": 294889}`

The current state is recorded as an IS-only artifact summary. This report does not use OS/full-period results for generation guidance.

## Goal Fit
No run-specific goal fit was inferred during automatic backfill. A future loop should compare this strategy against `research/wiki/goals/<run_id>.md` before reuse.

## Current Interpretation
alpha `xs_factor_accel5d_rev_c30` is indexed as family `xs_factor_accel_5d_fwd_c10` with status `IS_FAIL`; IS Sharpe -0.8694, return -33.01%, max drawdown -37.08%, trades 50409. Treat this as a retrieval description, not a recommendation to clone the strategy.

## Reuse Notes
- Auto-backfilled entry. Prefer mechanism-level reuse only.
- Do not infer best parameters from this report.
- Inspect source, weights, and IS PnL before using this as context for a new attempt.
