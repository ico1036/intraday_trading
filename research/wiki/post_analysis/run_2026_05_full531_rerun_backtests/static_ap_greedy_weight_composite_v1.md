# Post Analysis: static_ap_greedy_weight_composite_v1

- kind: `composite`
- run_id: `run_2026_05_full531_rerun_backtests`
- id: `static_ap_greedy_weight_composite_v1`
- status: `IS_PASS`
- family: `recomputed_ap_greedy_equal_weight_sign_aligned`
- artifact_dir: `/Users/jj_home/Git/intraday_trading/archive/run_2026_05_full531_rerun_backtests/composites/static_ap_greedy_weight_composite_v1`
- source_notes: `[]`
- alpha_cell: `{"idea_family": "recomputed_ap_greedy_equal_weight_sign_aligned", "kind": "composite"}`

## Implemented Strategy
Composite `static_ap_greedy_weight_composite_v1` built with method `recomputed_ap_greedy_equal_weight_sign_aligned` from `16` members. Gross stats mean/max: 0.28860303992847514 / 0.3595351528854436.

This section was auto-backfilled from archived source metadata and should be tightened manually before using it as high-confidence research memory.

## IS Performance State
- IS Sharpe: `0.3778912109135269`
- IS Return: `0.04037117908900309` (4.04%)
- IS Max Drawdown: `-0.03854031742249773` (-3.85%)
- IS Trades: `63941`
- IS Win Rate: `0.5010713001047841`
- PnL bps simple: `4337.438287361556`
- PnL bps notional weighted: `2.920801700608413`
- Artifact counts: `{"equity_rows": 373816, "trades_rows": 452401, "weights_rows": 352260}`

The current state is recorded as an IS-only artifact summary. This report does not use OS/full-period results for generation guidance.

## Goal Fit
No run-specific goal fit was inferred during automatic backfill. A future loop should compare this strategy against `research/wiki/goals/<run_id>.md` before reuse.

## Current Interpretation
composite `static_ap_greedy_weight_composite_v1` is indexed as family `recomputed_ap_greedy_equal_weight_sign_aligned` with status `IS_PASS`; IS Sharpe 0.3779, return 4.04%, max drawdown -3.85%, trades 63941. Treat this as a retrieval description, not a recommendation to clone the strategy.

## Reuse Notes
- Auto-backfilled entry. Prefer mechanism-level reuse only.
- Do not infer best parameters from this report.
- Inspect source, weights, and IS PnL before using this as context for a new attempt.
