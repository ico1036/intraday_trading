# Post Analysis: xs_factor_cci20d_fwd_c20

- kind: `alpha`
- run_id: `run_2026_05_full531_rerun_backtests`
- id: `xs_factor_cci20d_fwd_c20`
- status: `IS_FAIL`
- family: `xs_factor_cci_20d_fwd_c10`
- artifact_dir: `/Users/jj_home/Git/intraday_trading/archive/run_2026_05_full531_rerun_backtests/alphas/xs_factor_cci20d_fwd_c20`
- source_notes: `['research/notes/xs_factor_zoo.md']`
- alpha_cell: `{"bar": "TIME", "exit": "signal_flip", "horizon": "multi_day", "idea_family": "xs_factor_cci_20d_fwd_c10", "transform": "rolling_rank", "universe": "basket_full"}`

## Implemented Strategy
xs_factor_cci20d_fwd_c10 — auto-generated XS factor. Signal: cci_20d direction=fwd concentration=0.1 Cross-sectional rank of ``_compute_score`` over the eligible universe each emit bar, top/bottom concentration_pct legs.

This section was auto-backfilled from archived source metadata and should be tightened manually before using it as high-confidence research memory.

## IS Performance State
- IS Sharpe: `0.10181797713331343`
- IS Return: `0.006686586416247337` (0.67%)
- IS Max Drawdown: `-0.3521387900578021` (-35.21%)
- IS Trades: `26810`
- IS Win Rate: `0.5641924654979485`
- PnL bps simple: `720.9541642852213`
- PnL bps notional weighted: `-10.322332193984312`
- Artifact counts: `{"equity_rows": 373816, "trades_rows": 184822, "weights_rows": 183426}`

The current state is recorded as an IS-only artifact summary. This report does not use OS/full-period results for generation guidance.

## Goal Fit
No run-specific goal fit was inferred during automatic backfill. A future loop should compare this strategy against `research/wiki/goals/<run_id>.md` before reuse.

## Current Interpretation
alpha `xs_factor_cci20d_fwd_c20` is indexed as family `xs_factor_cci_20d_fwd_c10` with status `IS_FAIL`; IS Sharpe 0.1018, return 0.67%, max drawdown -35.21%, trades 26810. Treat this as a retrieval description, not a recommendation to clone the strategy.

## Reuse Notes
- Auto-backfilled entry. Prefer mechanism-level reuse only.
- Do not infer best parameters from this report.
- Inspect source, weights, and IS PnL before using this as context for a new attempt.
