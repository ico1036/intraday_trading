# Post Analysis: xs_factor_amihud60d_fwd_c20

- kind: `alpha`
- run_id: `run_2026_05_full531_rerun_backtests`
- id: `xs_factor_amihud60d_fwd_c20`
- status: `IS_PASS`
- family: `xs_factor_amihud_60d_fwd_c10`
- artifact_dir: `/Users/jj_home/Git/intraday_trading/archive/run_2026_05_full531_rerun_backtests/alphas/xs_factor_amihud60d_fwd_c20`
- source_notes: `['research/notes/xs_factor_zoo.md']`
- alpha_cell: `{"bar": "TIME", "exit": "signal_flip", "horizon": "multi_day", "idea_family": "xs_factor_amihud_60d_fwd_c10", "transform": "rolling_rank", "universe": "basket_full"}`

## Implemented Strategy
xs_factor_amihud60d_fwd_c10 — auto-generated XS factor. Signal: amihud_60d direction=fwd concentration=0.1 Cross-sectional rank of ``_compute_score`` over the eligible universe each emit bar, top/bottom concentration_pct legs.

This section was auto-backfilled from archived source metadata and should be tightened manually before using it as high-confidence research memory.

## IS Performance State
- IS Sharpe: `1.9803039389612542`
- IS Return: `0.8377411529485613` (83.77%)
- IS Max Drawdown: `-0.08817128187115753` (-8.82%)
- IS Trades: `20013`
- IS Win Rate: `0.5056213461250187`
- PnL bps simple: `1190.2479495771672`
- PnL bps notional weighted: `168.33056099349216`
- Artifact counts: `{"equity_rows": 373816, "trades_rows": 136933, "weights_rows": 137121}`

The current state is recorded as an IS-only artifact summary. This report does not use OS/full-period results for generation guidance.

## Goal Fit
No run-specific goal fit was inferred during automatic backfill. A future loop should compare this strategy against `research/wiki/goals/<run_id>.md` before reuse.

## Current Interpretation
alpha `xs_factor_amihud60d_fwd_c20` is indexed as family `xs_factor_amihud_60d_fwd_c10` with status `IS_PASS`; IS Sharpe 1.98, return 83.77%, max drawdown -8.82%, trades 20013. Treat this as a retrieval description, not a recommendation to clone the strategy.

## Reuse Notes
- Auto-backfilled entry. Prefer mechanism-level reuse only.
- Do not infer best parameters from this report.
- Inspect source, weights, and IS PnL before using this as context for a new attempt.
