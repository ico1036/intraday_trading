# Post Analysis: xs_factor_atrproxy7d_rev_c10

- kind: `alpha`
- run_id: `run_2026_05_full531_rerun_backtests`
- id: `xs_factor_atrproxy7d_rev_c10`
- status: `IS_PASS`
- family: `xs_factor_atr_proxy_7d_fwd_c10`
- artifact_dir: `/Users/jj_home/Git/intraday_trading/archive/run_2026_05_full531_rerun_backtests/alphas/xs_factor_atrproxy7d_rev_c10`
- source_notes: `['research/notes/xs_factor_zoo.md']`
- alpha_cell: `{"bar": "TIME", "exit": "signal_flip", "horizon": "multi_day", "idea_family": "xs_factor_atr_proxy_7d_fwd_c10", "transform": "rolling_rank", "universe": "basket_full"}`

## Implemented Strategy
xs_factor_atrproxy7d_fwd_c10 — auto-generated XS factor. Signal: atr_proxy_7d direction=fwd concentration=0.1 Cross-sectional rank of ``_compute_score`` over the eligible universe each emit bar, top/bottom concentration_pct legs.

This section was auto-backfilled from archived source metadata and should be tightened manually before using it as high-confidence research memory.

## IS Performance State
- IS Sharpe: `0.676419398857669`
- IS Return: `0.3403047681952396` (34.03%)
- IS Max Drawdown: `-0.2233861657522854` (-22.34%)
- IS Trades: `10974`
- IS Win Rate: `0.43293238563878256`
- PnL bps simple: `2569.1258931507014`
- PnL bps notional weighted: `39.65053576296937`
- Artifact counts: `{"equity_rows": 373816, "trades_rows": 75290, "weights_rows": 75413}`

The current state is recorded as an IS-only artifact summary. This report does not use OS/full-period results for generation guidance.

## Goal Fit
No run-specific goal fit was inferred during automatic backfill. A future loop should compare this strategy against `research/wiki/goals/<run_id>.md` before reuse.

## Current Interpretation
alpha `xs_factor_atrproxy7d_rev_c10` is indexed as family `xs_factor_atr_proxy_7d_fwd_c10` with status `IS_PASS`; IS Sharpe 0.6764, return 34.03%, max drawdown -22.34%, trades 10974. Treat this as a retrieval description, not a recommendation to clone the strategy.

## Reuse Notes
- Auto-backfilled entry. Prefer mechanism-level reuse only.
- Do not infer best parameters from this report.
- Inspect source, weights, and IS PnL before using this as context for a new attempt.
