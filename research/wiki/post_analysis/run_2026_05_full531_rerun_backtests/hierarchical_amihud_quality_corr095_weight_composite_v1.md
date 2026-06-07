# Post Analysis: hierarchical_amihud_quality_corr095_weight_composite_v1

- kind: `composite`
- run_id: `run_2026_05_full531_rerun_backtests`
- id: `hierarchical_amihud_quality_corr095_weight_composite_v1`
- status: `IS_PASS`
- family: `recomputed_hierarchical_pruning_equal_weight_sign_aligned`
- artifact_dir: `/Users/jj_home/Git/intraday_trading/archive/run_2026_05_full531_rerun_backtests/composites/hierarchical_amihud_quality_corr095_weight_composite_v1`
- source_notes: `[]`
- alpha_cell: `{"idea_family": "recomputed_hierarchical_pruning_equal_weight_sign_aligned", "kind": "composite"}`

## Implemented Strategy
Composite `hierarchical_amihud_quality_corr095_weight_composite_v1` built with method `recomputed_hierarchical_pruning_equal_weight_sign_aligned` from `5` members. Gross stats mean/max: 1.0 / 1.0.

This section was auto-backfilled from archived source metadata and should be tightened manually before using it as high-confidence research memory.

## IS Performance State
- IS Sharpe: `2.1035896292664082`
- IS Return: `0.7339681451467012` (73.40%)
- IS Max Drawdown: `-0.06966686999155837` (-6.97%)
- IS Trades: `50115`
- IS Win Rate: `0.514756061059563`
- PnL bps simple: `1993.1277140505288`
- PnL bps notional weighted: `233.84791863689844`
- Artifact counts: `{"equity_rows": 373816, "trades_rows": 342806, "weights_rows": 341637}`

The current state is recorded as an IS-only artifact summary. This report does not use OS/full-period results for generation guidance.

## Goal Fit
No run-specific goal fit was inferred during automatic backfill. A future loop should compare this strategy against `research/wiki/goals/<run_id>.md` before reuse.

## Current Interpretation
composite `hierarchical_amihud_quality_corr095_weight_composite_v1` is indexed as family `recomputed_hierarchical_pruning_equal_weight_sign_aligned` with status `IS_PASS`; IS Sharpe 2.104, return 73.40%, max drawdown -6.97%, trades 50115. Treat this as a retrieval description, not a recommendation to clone the strategy.

## Reuse Notes
- Auto-backfilled entry. Prefer mechanism-level reuse only.
- Do not infer best parameters from this report.
- Inspect source, weights, and IS PnL before using this as context for a new attempt.
