# Post Analysis: static_hierarchical_pruning_is05_family_dedup_weight_composite_v1

- kind: `composite`
- run_id: `run_2026_05_full531_rerun_backtests`
- id: `static_hierarchical_pruning_is05_family_dedup_weight_composite_v1`
- status: `IS_PASS`
- family: `recomputed_hierarchical_pruning_equal_weight_sign_aligned`
- artifact_dir: `/Users/jj_home/Git/intraday_trading/archive/run_2026_05_full531_rerun_backtests/composites/static_hierarchical_pruning_is05_family_dedup_weight_composite_v1`
- source_notes: `[]`
- alpha_cell: `{"idea_family": "recomputed_hierarchical_pruning_equal_weight_sign_aligned", "kind": "composite"}`

## Implemented Strategy
Composite `static_hierarchical_pruning_is05_family_dedup_weight_composite_v1` built with method `recomputed_hierarchical_pruning_equal_weight_sign_aligned` from `3` members. Gross stats mean/max: 0.8760911527372881 / 0.9999999999999999.

This section was auto-backfilled from archived source metadata and should be tightened manually before using it as high-confidence research memory.

## IS Performance State
- IS Sharpe: `1.462751890341239`
- IS Return: `0.6899522962626794` (69.00%)
- IS Max Drawdown: `-0.1141637315336935` (-11.42%)
- IS Trades: `31335`
- IS Win Rate: `0.5168980373384394`
- PnL bps simple: `-3381.633885592553`
- PnL bps notional weighted: `44.38156274851824`
- Artifact counts: `{"equity_rows": 373816, "trades_rows": 220786, "weights_rows": 210245}`

The current state is recorded as an IS-only artifact summary. This report does not use OS/full-period results for generation guidance.

## Goal Fit
No run-specific goal fit was inferred during automatic backfill. A future loop should compare this strategy against `research/wiki/goals/<run_id>.md` before reuse.

## Current Interpretation
composite `static_hierarchical_pruning_is05_family_dedup_weight_composite_v1` is indexed as family `recomputed_hierarchical_pruning_equal_weight_sign_aligned` with status `IS_PASS`; IS Sharpe 1.463, return 69.00%, max drawdown -11.42%, trades 31335. Treat this as a retrieval description, not a recommendation to clone the strategy.

## Reuse Notes
- Auto-backfilled entry. Prefer mechanism-level reuse only.
- Do not infer best parameters from this report.
- Inspect source, weights, and IS PnL before using this as context for a new attempt.
