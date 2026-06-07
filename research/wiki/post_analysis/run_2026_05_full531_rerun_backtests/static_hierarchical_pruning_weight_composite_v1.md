# Post Analysis: static_hierarchical_pruning_weight_composite_v1

- kind: `composite`
- run_id: `run_2026_05_full531_rerun_backtests`
- id: `static_hierarchical_pruning_weight_composite_v1`
- status: `IS_PASS`
- family: `recomputed_hierarchical_pruning_equal_weight_sign_aligned`
- artifact_dir: `/Users/jj_home/Git/intraday_trading/archive/run_2026_05_full531_rerun_backtests/composites/static_hierarchical_pruning_weight_composite_v1`
- source_notes: `[]`
- alpha_cell: `{"idea_family": "recomputed_hierarchical_pruning_equal_weight_sign_aligned", "kind": "composite"}`

## Implemented Strategy
Composite `static_hierarchical_pruning_weight_composite_v1` built with method `recomputed_hierarchical_pruning_equal_weight_sign_aligned` from `47` members. Gross stats mean/max: 0.24327956006409412 / 0.3069594016472516.

This section was auto-backfilled from archived source metadata and should be tightened manually before using it as high-confidence research memory.

## IS Performance State
- IS Sharpe: `1.3134820865418968`
- IS Return: `0.15380582155046105` (15.38%)
- IS Max Drawdown: `-0.038260912988568346` (-3.83%)
- IS Trades: `66248`
- IS Win Rate: `0.4949885279555609`
- PnL bps simple: `-560.0067051184441`
- PnL bps notional weighted: `22.259995160000102`
- Artifact counts: `{"equity_rows": 373816, "trades_rows": 453448, "weights_rows": 373282}`

The current state is recorded as an IS-only artifact summary. This report does not use OS/full-period results for generation guidance.

## Goal Fit
No run-specific goal fit was inferred during automatic backfill. A future loop should compare this strategy against `research/wiki/goals/<run_id>.md` before reuse.

## Current Interpretation
composite `static_hierarchical_pruning_weight_composite_v1` is indexed as family `recomputed_hierarchical_pruning_equal_weight_sign_aligned` with status `IS_PASS`; IS Sharpe 1.313, return 15.38%, max drawdown -3.83%, trades 66248. Treat this as a retrieval description, not a recommendation to clone the strategy.

## Reuse Notes
- Auto-backfilled entry. Prefer mechanism-level reuse only.
- Do not infer best parameters from this report.
- Inspect source, weights, and IS PnL before using this as context for a new attempt.
