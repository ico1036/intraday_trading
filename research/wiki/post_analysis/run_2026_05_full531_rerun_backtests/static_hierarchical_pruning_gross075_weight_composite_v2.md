# Post Analysis: static_hierarchical_pruning_gross075_weight_composite_v2

- kind: `composite`
- run_id: `run_2026_05_full531_rerun_backtests`
- id: `static_hierarchical_pruning_gross075_weight_composite_v2`
- status: `IS_PASS`
- family: `recomputed_hierarchical_pruning_gross075_equal_weight_sign_aligned`
- artifact_dir: `/Users/jj_home/Git/intraday_trading/archive/run_2026_05_full531_rerun_backtests/composites/static_hierarchical_pruning_gross075_weight_composite_v2`
- source_notes: `[]`
- alpha_cell: `{"idea_family": "recomputed_hierarchical_pruning_gross075_equal_weight_sign_aligned", "kind": "composite"}`

## Implemented Strategy
Composite `static_hierarchical_pruning_gross075_weight_composite_v2` built with method `recomputed_hierarchical_pruning_gross075_equal_weight_sign_aligned` from `47` members. Gross stats mean/max: 0.75 / 0.7500000000000002.

This section was auto-backfilled from archived source metadata and should be tightened manually before using it as high-confidence research memory.

## IS Performance State
- IS Sharpe: `1.3184221939220853`
- IS Return: `0.4706840171294709` (47.07%)
- IS Max Drawdown: `-0.10066257944794453` (-10.07%)
- IS Trades: `66289`
- IS Win Rate: `0.49439575193471014`
- PnL bps simple: `-992.0249114362152`
- PnL bps notional weighted: `22.161694627685105`
- Artifact counts: `{"equity_rows": 373816, "trades_rows": 453226, "weights_rows": 373050}`

The current state is recorded as an IS-only artifact summary. This report does not use OS/full-period results for generation guidance.

## Goal Fit
No run-specific goal fit was inferred during automatic backfill. A future loop should compare this strategy against `research/wiki/goals/<run_id>.md` before reuse.

## Current Interpretation
composite `static_hierarchical_pruning_gross075_weight_composite_v2` is indexed as family `recomputed_hierarchical_pruning_gross075_equal_weight_sign_aligned` with status `IS_PASS`; IS Sharpe 1.318, return 47.07%, max drawdown -10.07%, trades 66289. Treat this as a retrieval description, not a recommendation to clone the strategy.

## Reuse Notes
- Auto-backfilled entry. Prefer mechanism-level reuse only.
- Do not infer best parameters from this report.
- Inspect source, weights, and IS PnL before using this as context for a new attempt.
