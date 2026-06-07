# Post Analysis: composite_amihud60d_fwd_c20_c50_equal_weight_v1

- kind: `composite`
- run_id: `run_2026_05_full531_rerun_backtests`
- id: `composite_amihud60d_fwd_c20_c50_equal_weight_v1`
- status: `IS_PASS`
- family: `recomputed_explicit_selection_equal_weight_sign_aligned`
- artifact_dir: `/Users/jj_home/Git/intraday_trading/archive/run_2026_05_full531_rerun_backtests/composites/composite_amihud60d_fwd_c20_c50_equal_weight_v1`
- source_notes: `[]`
- alpha_cell: `{"idea_family": "recomputed_explicit_selection_equal_weight_sign_aligned", "kind": "composite"}`

## Implemented Strategy
Composite `composite_amihud60d_fwd_c20_c50_equal_weight_v1` built with method `recomputed_explicit_selection_equal_weight_sign_aligned` from `4` members. Gross stats mean/max: 1.0 / 1.0.

This section was auto-backfilled from archived source metadata and should be tightened manually before using it as high-confidence research memory.

## IS Performance State
- IS Sharpe: `2.0223316882121405`
- IS Return: `0.6339336686051869` (63.39%)
- IS Max Drawdown: `-0.06478623887209294` (-6.48%)
- IS Trades: `50172`
- IS Win Rate: `0.5136928964362593`
- PnL bps simple: `797.5979547153338`
- PnL bps notional weighted: `199.3754257744141`
- Artifact counts: `{"equity_rows": 373816, "trades_rows": 342796, "weights_rows": 341637}`

The current state is recorded as an IS-only artifact summary. This report does not use OS/full-period results for generation guidance.

## Goal Fit
No run-specific goal fit was inferred during automatic backfill. A future loop should compare this strategy against `research/wiki/goals/<run_id>.md` before reuse.

## Current Interpretation
composite `composite_amihud60d_fwd_c20_c50_equal_weight_v1` is indexed as family `recomputed_explicit_selection_equal_weight_sign_aligned` with status `IS_PASS`; IS Sharpe 2.022, return 63.39%, max drawdown -6.48%, trades 50172. Treat this as a retrieval description, not a recommendation to clone the strategy.

## Reuse Notes
- Auto-backfilled entry. Prefer mechanism-level reuse only.
- Do not infer best parameters from this report.
- Inspect source, weights, and IS PnL before using this as context for a new attempt.
