# Post Analysis: xs_factor_accel5d_fwd_c05

- kind: `alpha`
- run_id: `run_2026_05_full531_rerun_backtests`
- id: `xs_factor_accel5d_fwd_c05`
- status: `IS_FAIL`
- family: `xs_factor_accel_5d_fwd_c10`
- artifact_dir: `/Users/jj_home/Git/intraday_trading/archive/run_2026_05_full531_rerun_backtests/alphas/xs_factor_accel5d_fwd_c05`
- source_notes: `['research/notes/xs_factor_zoo.md']`
- alpha_cell: `{"bar": "TIME", "exit": "signal_flip", "horizon": "multi_day", "idea_family": "xs_factor_accel_5d_fwd_c10", "transform": "rolling_rank", "universe": "basket_full"}`

## Implemented Strategy
xs_factor_accel5d_fwd_c10 — auto-generated XS factor. Signal: accel_5d direction=fwd concentration=0.1 Cross-sectional rank of ``_compute_score`` over the eligible universe each emit bar, top/bottom concentration_pct legs.

This section was auto-backfilled from archived source metadata and should be tightened manually before using it as high-confidence research memory.

## IS Performance State
- IS Sharpe: `-0.5836276611212701`
- IS Return: `-1.535220670044992` (-153.52%)
- IS Max Drawdown: `-1.6208054679800303` (-162.08%)
- IS Trades: `8677`
- IS Win Rate: `0.5005186124236487`
- PnL bps simple: `459.82192230197353`
- PnL bps notional weighted: `-27.50981301392175`
- Artifact counts: `{"equity_rows": 373816, "trades_rows": 61571, "weights_rows": 57545}`

The current state is recorded as an IS-only artifact summary. This report does not use OS/full-period results for generation guidance.

## Goal Fit
No run-specific goal fit was inferred during automatic backfill. A future loop should compare this strategy against `research/wiki/goals/<run_id>.md` before reuse.

## Current Interpretation
alpha `xs_factor_accel5d_fwd_c05` is indexed as family `xs_factor_accel_5d_fwd_c10` with status `IS_FAIL`; IS Sharpe -0.5836, return -153.52%, max drawdown -162.08%, trades 8677. Treat this as a retrieval description, not a recommendation to clone the strategy.

## Reuse Notes
- Auto-backfilled entry. Prefer mechanism-level reuse only.
- Do not infer best parameters from this report.
- Inspect source, weights, and IS PnL before using this as context for a new attempt.
