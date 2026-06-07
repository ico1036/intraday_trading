# Post Analysis: static_hierarchical_pruning_netted_greedy_weight_composite_v2

- kind: `composite`
- run_id: `run_2026_05_full531_rerun_backtests`
- id: `static_hierarchical_pruning_netted_greedy_weight_composite_v2`
- status: `IS_PASS`
- family: `recomputed_hierarchical_pruning_netted_greedy_equal_weight_sign_aligned`
- artifact_dir: `/Users/jj_home/Git/intraday_trading/archive/run_2026_05_full531_rerun_backtests/composites/static_hierarchical_pruning_netted_greedy_weight_composite_v2`
- source_notes: `[]`
- alpha_cell: `{"idea_family": "recomputed_hierarchical_pruning_netted_greedy_equal_weight_sign_aligned", "kind": "composite"}`

## Implemented Strategy
Composite `static_hierarchical_pruning_netted_greedy_weight_composite_v2` built with method `recomputed_hierarchical_pruning_netted_greedy_equal_weight_sign_aligned` from `8` members. Gross stats mean/max: 0.7201071438118352 / 0.9154461279461279.

This section was auto-backfilled from archived source metadata and should be tightened manually before using it as high-confidence research memory.

## IS Performance State
- IS Sharpe: `0.975692952464606`
- IS Return: `0.37822770329095784` (37.82%)
- IS Max Drawdown: `-0.12900613746437145` (-12.90%)
- IS Trades: `27781`
- IS Win Rate: `0.48597962636334185`
- PnL bps simple: `-6373.012627655863`
- PnL bps notional weighted: `20.49034466866882`
- Artifact counts: `{"equity_rows": 373816, "trades_rows": 215961, "weights_rows": 172971}`

The current state is recorded as an IS-only artifact summary. This report does not use OS/full-period results for generation guidance.

## Goal Fit
No run-specific goal fit was inferred during automatic backfill. A future loop should compare this strategy against `research/wiki/goals/<run_id>.md` before reuse.

## Current Interpretation
composite `static_hierarchical_pruning_netted_greedy_weight_composite_v2` is indexed as family `recomputed_hierarchical_pruning_netted_greedy_equal_weight_sign_aligned` with status `IS_PASS`; IS Sharpe 0.9757, return 37.82%, max drawdown -12.90%, trades 27781. Treat this as a retrieval description, not a recommendation to clone the strategy.

## Reuse Notes
- Auto-backfilled entry. Prefer mechanism-level reuse only.
- Do not infer best parameters from this report.
- Inspect source, weights, and IS PnL before using this as context for a new attempt.
