# Post Analysis: xs_factor_atrproxy21d_rev_c20

- kind: `alpha`
- run_id: `run_2026_05_full531_rerun_backtests`
- id: `xs_factor_atrproxy21d_rev_c20`
- status: `IS_PASS`
- family: `xs_factor_atr_proxy_21d_fwd_c10`
- artifact_dir: `/Users/jj_home/Git/intraday_trading/archive/run_2026_05_full531_rerun_backtests/alphas/xs_factor_atrproxy21d_rev_c20`
- source_notes: `['research/notes/xs_factor_zoo.md']`
- alpha_cell: `{"bar": "TIME", "exit": "signal_flip", "horizon": "multi_day", "idea_family": "xs_factor_atr_proxy_21d_fwd_c10", "transform": "rolling_rank", "universe": "basket_full"}`

## Implemented Strategy
xs_factor_atrproxy21d_fwd_c10 — auto-generated XS factor. Signal: atr_proxy_21d direction=fwd concentration=0.1 Cross-sectional rank of ``_compute_score`` over the eligible universe each emit bar, top/bottom concentration_pct legs.

This section was auto-backfilled from archived source metadata and should be tightened manually before using it as high-confidence research memory.

## IS Performance State
- IS Sharpe: `0.6612589170679922`
- IS Return: `0.24733728409859088` (24.73%)
- IS Max Drawdown: `-0.19745915506194062` (-19.75%)
- IS Trades: `21211`
- IS Win Rate: `0.464051671302626`
- PnL bps simple: `461.89185722098813`
- PnL bps notional weighted: `32.888076737921025`
- Artifact counts: `{"equity_rows": 373816, "trades_rows": 144890, "weights_rows": 145115}`

The current state is recorded as an IS-only artifact summary. This report does not use OS/full-period results for generation guidance.

## Goal Fit
No run-specific goal fit was inferred during automatic backfill. A future loop should compare this strategy against `research/wiki/goals/<run_id>.md` before reuse.

## Current Interpretation
alpha `xs_factor_atrproxy21d_rev_c20` is indexed as family `xs_factor_atr_proxy_21d_fwd_c10` with status `IS_PASS`; IS Sharpe 0.6613, return 24.73%, max drawdown -19.75%, trades 21211. Treat this as a retrieval description, not a recommendation to clone the strategy.

## Reuse Notes
- Auto-backfilled entry. Prefer mechanism-level reuse only.
- Do not infer best parameters from this report.
- Inspect source, weights, and IS PnL before using this as context for a new attempt.
