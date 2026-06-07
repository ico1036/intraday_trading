# Post Analysis: hierarchical_amihud_quality_corr095_gross5_weight_composite_v1

- kind: `composite`
- run_id: `run_2026_05_full531_rerun_backtests`
- id: `hierarchical_amihud_quality_corr095_gross5_weight_composite_v1`
- status: `IS_PASS`
- family: `recomputed_explicit_selection_gross50_equal_weight_sign_aligned`
- artifact_dir: `/Users/jj_home/Git/intraday_trading/archive/run_2026_05_full531_rerun_backtests/composites/hierarchical_amihud_quality_corr095_gross5_weight_composite_v1`
- source_notes: `[]`
- alpha_cell: `{"idea_family": "recomputed_explicit_selection_gross50_equal_weight_sign_aligned", "kind": "composite"}`

## Implemented Strategy
Composite `hierarchical_amihud_quality_corr095_gross5_weight_composite_v1` built with method `recomputed_explicit_selection_gross50_equal_weight_sign_aligned` from `5` members. Gross stats mean/max: 5.0 / 5.000000000000002.

This section was auto-backfilled from archived source metadata and should be tightened manually before using it as high-confidence research memory.

## IS Performance State
- IS Sharpe: `1.9966258732087059`
- IS Return: `3.6698407257336605` (366.98%)
- IS Max Drawdown: `-0.24152497775725215` (-24.15%)
- IS Trades: `50118`
- IS Win Rate: `0.514765154236003`
- PnL bps simple: `23679944366485.027`
- PnL bps notional weighted: `233.85175363586265`
- Artifact counts: `{"equity_rows": 373816, "trades_rows": 342822, "weights_rows": 341637}`

The current state is recorded as an IS-only artifact summary. This report does not use OS/full-period results for generation guidance.

## Goal Fit
No run-specific goal fit was inferred during automatic backfill. A future loop should compare this strategy against `research/wiki/goals/<run_id>.md` before reuse.

## Current Interpretation
composite `hierarchical_amihud_quality_corr095_gross5_weight_composite_v1` is indexed as family `recomputed_explicit_selection_gross50_equal_weight_sign_aligned` with status `IS_PASS`; IS Sharpe 1.997, return 366.98%, max drawdown -24.15%, trades 50118. Treat this as a retrieval description, not a recommendation to clone the strategy.

## Reuse Notes
- Auto-backfilled entry. Prefer mechanism-level reuse only.
- Do not infer best parameters from this report.
- Inspect source, weights, and IS PnL before using this as context for a new attempt.
