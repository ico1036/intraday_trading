# Post Analysis: static_baseline_eqw_all_weight_composite_v1

- kind: `composite`
- run_id: `run_2026_05_full531_rerun_backtests`
- id: `static_baseline_eqw_all_weight_composite_v1`
- status: `IS_PASS`
- family: `recomputed_baseline_eqw_all_equal_weight_sign_aligned`
- artifact_dir: `/Users/jj_home/Git/intraday_trading/archive/run_2026_05_full531_rerun_backtests/composites/static_baseline_eqw_all_weight_composite_v1`
- source_notes: `[]`
- alpha_cell: `{"idea_family": "recomputed_baseline_eqw_all_equal_weight_sign_aligned", "kind": "composite"}`

## Implemented Strategy
Composite `static_baseline_eqw_all_weight_composite_v1` built with method `recomputed_baseline_eqw_all_equal_weight_sign_aligned` from `268` members. Gross stats mean/max: 0.21594889769218475 / 0.2814635124860488.

This section was auto-backfilled from archived source metadata and should be tightened manually before using it as high-confidence research memory.

## IS Performance State
- IS Sharpe: `1.113768634540294`
- IS Return: `0.12533191072626396` (12.53%)
- IS Max Drawdown: `-0.04390031914217269` (-4.39%)
- IS Trades: `60496`
- IS Win Rate: `0.4969088865379529`
- PnL bps simple: `1386.954503818682`
- PnL bps notional weighted: `37.74273978928746`
- Artifact counts: `{"equity_rows": 373816, "trades_rows": 418278, "weights_rows": 371229}`

The current state is recorded as an IS-only artifact summary. This report does not use OS/full-period results for generation guidance.

## Goal Fit
No run-specific goal fit was inferred during automatic backfill. A future loop should compare this strategy against `research/wiki/goals/<run_id>.md` before reuse.

## Current Interpretation
composite `static_baseline_eqw_all_weight_composite_v1` is indexed as family `recomputed_baseline_eqw_all_equal_weight_sign_aligned` with status `IS_PASS`; IS Sharpe 1.114, return 12.53%, max drawdown -4.39%, trades 60496. Treat this as a retrieval description, not a recommendation to clone the strategy.

## Reuse Notes
- Auto-backfilled entry. Prefer mechanism-level reuse only.
- Do not infer best parameters from this report.
- Inspect source, weights, and IS PnL before using this as context for a new attempt.
