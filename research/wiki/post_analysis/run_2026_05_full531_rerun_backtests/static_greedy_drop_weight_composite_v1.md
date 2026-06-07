# Post Analysis: static_greedy_drop_weight_composite_v1

- kind: `composite`
- run_id: `run_2026_05_full531_rerun_backtests`
- id: `static_greedy_drop_weight_composite_v1`
- status: `IS_PASS`
- family: `recomputed_greedy_drop_equal_weight_sign_aligned`
- artifact_dir: `/Users/jj_home/Git/intraday_trading/archive/run_2026_05_full531_rerun_backtests/composites/static_greedy_drop_weight_composite_v1`
- source_notes: `[]`
- alpha_cell: `{"idea_family": "recomputed_greedy_drop_equal_weight_sign_aligned", "kind": "composite"}`

## Implemented Strategy
Composite `static_greedy_drop_weight_composite_v1` built with method `recomputed_greedy_drop_equal_weight_sign_aligned` from `17` members. Gross stats mean/max: 0.285054860924067 / 0.37253888635557586.

This section was auto-backfilled from archived source metadata and should be tightened manually before using it as high-confidence research memory.

## IS Performance State
- IS Sharpe: `0.9824168383646753`
- IS Return: `0.11690016354593208` (11.69%)
- IS Max Drawdown: `-0.04509311997879979` (-4.51%)
- IS Trades: `63181`
- IS Win Rate: `0.5124325350975768`
- PnL bps simple: `3841.4520700549524`
- PnL bps notional weighted: `12.707165355708149`
- Artifact counts: `{"equity_rows": 373816, "trades_rows": 447054, "weights_rows": 348229}`

The current state is recorded as an IS-only artifact summary. This report does not use OS/full-period results for generation guidance.

## Goal Fit
No run-specific goal fit was inferred during automatic backfill. A future loop should compare this strategy against `research/wiki/goals/<run_id>.md` before reuse.

## Current Interpretation
composite `static_greedy_drop_weight_composite_v1` is indexed as family `recomputed_greedy_drop_equal_weight_sign_aligned` with status `IS_PASS`; IS Sharpe 0.9824, return 11.69%, max drawdown -4.51%, trades 63181. Treat this as a retrieval description, not a recommendation to clone the strategy.

## Reuse Notes
- Auto-backfilled entry. Prefer mechanism-level reuse only.
- Do not infer best parameters from this report.
- Inspect source, weights, and IS PnL before using this as context for a new attempt.
