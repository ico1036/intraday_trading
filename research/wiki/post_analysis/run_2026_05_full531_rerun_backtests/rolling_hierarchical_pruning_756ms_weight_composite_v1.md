# Post Analysis: rolling_hierarchical_pruning_756ms_weight_composite_v1

- kind: `composite`
- run_id: `run_2026_05_full531_rerun_backtests`
- id: `rolling_hierarchical_pruning_756ms_weight_composite_v1`
- status: `IS_PASS`
- family: `recomputed_hierarchical_pruning_rolling_equal_weight_sign_aligned`
- artifact_dir: `/Users/jj_home/Git/intraday_trading/archive/run_2026_05_full531_rerun_backtests/composites/rolling_hierarchical_pruning_756ms_weight_composite_v1`
- source_notes: `[]`
- alpha_cell: `{"idea_family": "recomputed_hierarchical_pruning_rolling_equal_weight_sign_aligned", "kind": "composite"}`

## Implemented Strategy
Composite `rolling_hierarchical_pruning_756ms_weight_composite_v1` built with method `recomputed_hierarchical_pruning_rolling_equal_weight_sign_aligned` from `184` members. Gross stats mean/max: 0.2501687243439958 / 0.4167552115946224.

This section was auto-backfilled from archived source metadata and should be tightened manually before using it as high-confidence research memory.

## IS Performance State
- IS Sharpe: `-0.13097265971202143`
- IS Return: `-0.004332657351102534` (-0.43%)
- IS Max Drawdown: `-0.023248574445387304` (-2.32%)
- IS Trades: `10035`
- IS Win Rate: `0.5144992526158445`
- PnL bps simple: `-1556.1268429125569`
- PnL bps notional weighted: `-15.142521819194931`
- Artifact counts: `{"equity_rows": 373816, "trades_rows": 339928, "weights_rows": 279254}`

The current state is recorded as an IS-only artifact summary. This report does not use OS/full-period results for generation guidance.

## Goal Fit
No run-specific goal fit was inferred during automatic backfill. A future loop should compare this strategy against `research/wiki/goals/<run_id>.md` before reuse.

## Current Interpretation
composite `rolling_hierarchical_pruning_756ms_weight_composite_v1` is indexed as family `recomputed_hierarchical_pruning_rolling_equal_weight_sign_aligned` with status `IS_PASS`; IS Sharpe -0.131, return -0.43%, max drawdown -2.32%, trades 10035. Treat this as a retrieval description, not a recommendation to clone the strategy.

## Reuse Notes
- Auto-backfilled entry. Prefer mechanism-level reuse only.
- Do not infer best parameters from this report.
- Inspect source, weights, and IS PnL before using this as context for a new attempt.
