# Post Analysis: xs_factor_cci20d_fwd_c05

- kind: `alpha`
- run_id: `run_2026_05_full531_rerun_backtests`
- id: `xs_factor_cci20d_fwd_c05`
- status: `IS_FAIL`
- family: `xs_factor_cci_20d_fwd_c10`
- artifact_dir: `/Users/jj_home/Git/intraday_trading/archive/run_2026_05_full531_rerun_backtests/alphas/xs_factor_cci20d_fwd_c05`
- source_notes: `['research/notes/xs_factor_zoo.md']`
- alpha_cell: `{"bar": "TIME", "exit": "signal_flip", "horizon": "multi_day", "idea_family": "xs_factor_cci_20d_fwd_c10", "transform": "rolling_rank", "universe": "basket_full"}`

## Implemented Strategy
xs_factor_cci20d_fwd_c10 — auto-generated XS factor. Signal: cci_20d direction=fwd concentration=0.1 Cross-sectional rank of ``_compute_score`` over the eligible universe each emit bar, top/bottom concentration_pct legs.

This section was auto-backfilled from archived source metadata and should be tightened manually before using it as high-confidence research memory.

## IS Performance State
- IS Sharpe: `0.20338352076691985`
- IS Return: `-0.29093235983392035` (-29.09%)
- IS Max Drawdown: `-0.8433902004116854` (-84.34%)
- IS Trades: `7103`
- IS Win Rate: `0.5179501619034211`
- PnL bps simple: `-946.1710386668541`
- PnL bps notional weighted: `-24.502445282720718`
- Artifact counts: `{"equity_rows": 373816, "trades_rows": 49873, "weights_rows": 49806}`

The current state is recorded as an IS-only artifact summary. This report does not use OS/full-period results for generation guidance.

## Goal Fit
No run-specific goal fit was inferred during automatic backfill. A future loop should compare this strategy against `research/wiki/goals/<run_id>.md` before reuse.

## Current Interpretation
alpha `xs_factor_cci20d_fwd_c05` is indexed as family `xs_factor_cci_20d_fwd_c10` with status `IS_FAIL`; IS Sharpe 0.2034, return -29.09%, max drawdown -84.34%, trades 7103. Treat this as a retrieval description, not a recommendation to clone the strategy.

## Reuse Notes
- Auto-backfilled entry. Prefer mechanism-level reuse only.
- Do not infer best parameters from this report.
- Inspect source, weights, and IS PnL before using this as context for a new attempt.
