# Post Analysis: xs_factor_cci20d_rev_c30

- kind: `alpha`
- run_id: `run_2026_05_full531_rerun_backtests`
- id: `xs_factor_cci20d_rev_c30`
- status: `IS_FAIL`
- family: `xs_factor_cci_20d_fwd_c10`
- artifact_dir: `/Users/jj_home/Git/intraday_trading/archive/run_2026_05_full531_rerun_backtests/alphas/xs_factor_cci20d_rev_c30`
- source_notes: `['research/notes/xs_factor_zoo.md']`
- alpha_cell: `{"bar": "TIME", "exit": "signal_flip", "horizon": "multi_day", "idea_family": "xs_factor_cci_20d_fwd_c10", "transform": "rolling_rank", "universe": "basket_full"}`

## Implemented Strategy
xs_factor_cci20d_fwd_c10 — auto-generated XS factor. Signal: cci_20d direction=fwd concentration=0.1 Cross-sectional rank of ``_compute_score`` over the eligible universe each emit bar, top/bottom concentration_pct legs.

This section was auto-backfilled from archived source metadata and should be tightened manually before using it as high-confidence research memory.

## IS Performance State
- IS Sharpe: `-1.1790164673676211`
- IS Return: `-0.43916152676576337` (-43.92%)
- IS Max Drawdown: `-0.47238790768130257` (-47.24%)
- IS Trades: `38846`
- IS Win Rate: `0.4198115636101529`
- PnL bps simple: `963.829339772867`
- PnL bps notional weighted: `-11.766192406563489`
- Artifact counts: `{"equity_rows": 373816, "trades_rows": 268345, "weights_rows": 263410}`

The current state is recorded as an IS-only artifact summary. This report does not use OS/full-period results for generation guidance.

## Goal Fit
No run-specific goal fit was inferred during automatic backfill. A future loop should compare this strategy against `research/wiki/goals/<run_id>.md` before reuse.

## Current Interpretation
alpha `xs_factor_cci20d_rev_c30` is indexed as family `xs_factor_cci_20d_fwd_c10` with status `IS_FAIL`; IS Sharpe -1.179, return -43.92%, max drawdown -47.24%, trades 38846. Treat this as a retrieval description, not a recommendation to clone the strategy.

## Reuse Notes
- Auto-backfilled entry. Prefer mechanism-level reuse only.
- Do not infer best parameters from this report.
- Inspect source, weights, and IS PnL before using this as context for a new attempt.
