# Post Analysis: hierarchical_amihud_quality_corr09_weight_composite_v1

- kind: `composite`
- run_id: `run_2026_05_full531_rerun_backtests`
- id: `hierarchical_amihud_quality_corr09_weight_composite_v1`
- status: `IS_PASS`
- family: `recomputed_hierarchical_pruning_equal_weight_sign_aligned`
- artifact_dir: `/Users/jj_home/Git/intraday_trading/archive/run_2026_05_full531_rerun_backtests/composites/hierarchical_amihud_quality_corr09_weight_composite_v1`
- source_notes: `[]`
- alpha_cell: `{"idea_family": "recomputed_hierarchical_pruning_equal_weight_sign_aligned", "kind": "composite"}`

## Implemented Strategy
Composite `hierarchical_amihud_quality_corr09_weight_composite_v1` built with method `recomputed_hierarchical_pruning_equal_weight_sign_aligned` from `4` members. Gross stats mean/max: 1.0 / 1.0.

This section was auto-backfilled from archived source metadata and should be tightened manually before using it as high-confidence research memory.

## IS Performance State
- IS Sharpe: `2.103010675793987`
- IS Return: `0.7799683598945412` (78.00%)
- IS Max Drawdown: `-0.07366558262784757` (-7.37%)
- IS Trades: `50034`
- IS Win Rate: `0.5164088419874485`
- PnL bps simple: `-124613582435.40623`
- PnL bps notional weighted: `245.607758333542`
- Artifact counts: `{"equity_rows": 373816, "trades_rows": 342765, "weights_rows": 341637}`

The current state is recorded as an IS-only artifact summary. This report does not use OS/full-period results for generation guidance.

## Goal Fit
No run-specific goal fit was inferred during automatic backfill. A future loop should compare this strategy against `research/wiki/goals/<run_id>.md` before reuse.

## Current Interpretation
composite `hierarchical_amihud_quality_corr09_weight_composite_v1` is indexed as family `recomputed_hierarchical_pruning_equal_weight_sign_aligned` with status `IS_PASS`; IS Sharpe 2.103, return 78.00%, max drawdown -7.37%, trades 50034. Treat this as a retrieval description, not a recommendation to clone the strategy.

## Reuse Notes
- Auto-backfilled entry. Prefer mechanism-level reuse only.
- Do not infer best parameters from this report.
- Inspect source, weights, and IS PnL before using this as context for a new attempt.
