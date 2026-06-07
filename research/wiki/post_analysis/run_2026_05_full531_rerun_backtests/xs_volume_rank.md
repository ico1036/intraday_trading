# Post Analysis: xs_volume_rank

- kind: `alpha`
- run_id: `run_2026_05_full531_rerun_backtests`
- id: `xs_volume_rank`
- status: `IS_FAIL`
- family: `xs_volume_rank`
- artifact_dir: `/Users/jj_home/Git/intraday_trading/archive/run_2026_05_full531_rerun_backtests/alphas/xs_volume_rank`
- source_notes: `['research/notes/xs_volume_rank.md']`
- alpha_cell: `{"bar": "TIME", "exit": "signal_flip", "horizon": "multi_day", "idea_family": "xs_volume_rank", "transform": "rolling_rank", "universe": "basket_full"}`

## Implemented Strategy
xs_volume_rank — cross-section daily: long top-50% by prev-day quote_volume, short bottom-50%. Hypothesis: high quote-volume days are followed by mean-reverting flow into the lower-attention names — or, alternatively, continued momentum in the high-flow names. We trade the directional version (long high, short low), equal-weight basket, daily rebalance. Treat the result as a breadth test on the existing pipeline using a 500-coin universe at daily frequency.

This section was auto-backfilled from archived source metadata and should be tightened manually before using it as high-confidence research memory.

## IS Performance State
- IS Sharpe: `-1.4559699177845613`
- IS Return: `-0.4534853524640046` (-45.35%)
- IS Max Drawdown: `-0.4797602930101966` (-47.98%)
- IS Trades: `59407`
- IS Win Rate: `0.5406601915599172`
- PnL bps simple: `-558.3692702143985`
- PnL bps notional weighted: `-48.72520113491985`
- Artifact counts: `{"equity_rows": 373816, "trades_rows": 407157, "weights_rows": 373267}`

The current state is recorded as an IS-only artifact summary. This report does not use OS/full-period results for generation guidance.

## Goal Fit
No run-specific goal fit was inferred during automatic backfill. A future loop should compare this strategy against `research/wiki/goals/<run_id>.md` before reuse.

## Current Interpretation
alpha `xs_volume_rank` is indexed as family `xs_volume_rank` with status `IS_FAIL`; IS Sharpe -1.456, return -45.35%, max drawdown -47.98%, trades 59407. Treat this as a retrieval description, not a recommendation to clone the strategy.

## Reuse Notes
- Auto-backfilled entry. Prefer mechanism-level reuse only.
- Do not infer best parameters from this report.
- Inspect source, weights, and IS PnL before using this as context for a new attempt.
