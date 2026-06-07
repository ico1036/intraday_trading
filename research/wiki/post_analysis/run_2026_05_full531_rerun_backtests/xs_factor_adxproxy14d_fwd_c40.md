# Post Analysis: xs_factor_adxproxy14d_fwd_c40

- kind: `alpha`
- run_id: `run_2026_05_full531_rerun_backtests`
- id: `xs_factor_adxproxy14d_fwd_c40`
- status: `IS_FAIL`
- family: `xs_factor_adx_proxy_14d_fwd_c10`
- artifact_dir: `/Users/jj_home/Git/intraday_trading/archive/run_2026_05_full531_rerun_backtests/alphas/xs_factor_adxproxy14d_fwd_c40`
- source_notes: `['research/notes/xs_factor_zoo.md']`
- alpha_cell: `{"bar": "TIME", "exit": "signal_flip", "horizon": "multi_day", "idea_family": "xs_factor_adx_proxy_14d_fwd_c10", "transform": "rolling_rank", "universe": "basket_full"}`

## Implemented Strategy
xs_factor_adxproxy14d_fwd_c10 — auto-generated XS factor. Signal: adx_proxy_14d direction=fwd concentration=0.1 Cross-sectional rank of ``_compute_score`` over the eligible universe each emit bar, top/bottom concentration_pct legs.

This section was auto-backfilled from archived source metadata and should be tightened manually before using it as high-confidence research memory.

## IS Performance State
- IS Sharpe: `-1.1737211015189677`
- IS Return: `-0.4185829732114024` (-41.86%)
- IS Max Drawdown: `-0.5255990889943194` (-52.56%)
- IS Trades: `53851`
- IS Win Rate: `0.497168112012776`
- PnL bps simple: `-1579.5049135773454`
- PnL bps notional weighted: `-20.422903434233124`
- Artifact counts: `{"equity_rows": 373816, "trades_rows": 364820, "weights_rows": 336068}`

The current state is recorded as an IS-only artifact summary. This report does not use OS/full-period results for generation guidance.

## Goal Fit
No run-specific goal fit was inferred during automatic backfill. A future loop should compare this strategy against `research/wiki/goals/<run_id>.md` before reuse.

## Current Interpretation
alpha `xs_factor_adxproxy14d_fwd_c40` is indexed as family `xs_factor_adx_proxy_14d_fwd_c10` with status `IS_FAIL`; IS Sharpe -1.174, return -41.86%, max drawdown -52.56%, trades 53851. Treat this as a retrieval description, not a recommendation to clone the strategy.

## Reuse Notes
- Auto-backfilled entry. Prefer mechanism-level reuse only.
- Do not infer best parameters from this report.
- Inspect source, weights, and IS PnL before using this as context for a new attempt.
