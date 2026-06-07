# Post Analysis: xs_volume_rank

- kind: `alpha`
- run_id: `run_2026_05_xs500`
- id: `xs_volume_rank`
- status: `IS_PASS`
- family: `xs_volume_rank`
- artifact_dir: `/Users/jj_home/Git/intraday_trading/archive/run_2026_05_xs500/alphas/xs_volume_rank`
- source_notes: `['research/notes/xs_volume_rank.md']`
- alpha_cell: `{"bar": "TIME", "exit": "signal_flip", "horizon": "multi_day", "idea_family": "xs_volume_rank", "transform": "rolling_rank", "universe": "basket_full"}`

## Implemented Strategy
xs_volume_rank — cross-section daily: long top-50% by prev-day quote_volume, short bottom-50%. Hypothesis: high quote-volume days are followed by mean-reverting flow into the lower-attention names — or, alternatively, continued momentum in the high-flow names. We trade the directional version (long high, short low), equal-weight basket, daily rebalance. Treat the result as a breadth test on the existing pipeline using a 500-coin universe at daily frequency.

This section was auto-backfilled from archived source metadata and should be tightened manually before using it as high-confidence research memory.

## IS Performance State
- IS Sharpe: `0.9216342396818002`
- IS Return: `0.291514973755633` (29.15%)
- IS Max Drawdown: `-0.09972192320978814` (-9.97%)
- IS Trades: `32955`
- IS Win Rate: `0.46809285389167044`
- PnL bps simple: `-328.4748478267429`
- PnL bps notional weighted: `34.05148727893413`
- Artifact counts: `{"equity_rows": 199227, "trades_rows": 215552, "weights_rows": 198919}`

The current state is recorded as an IS-only artifact summary. This report does not use OS/full-period results for generation guidance.

## Goal Fit
No run-specific goal fit was inferred during automatic backfill. A future loop should compare this strategy against `research/wiki/goals/<run_id>.md` before reuse.

## Current Interpretation
alpha `xs_volume_rank` is indexed as family `xs_volume_rank` with status `IS_PASS`; IS Sharpe 0.9216, return 29.15%, max drawdown -9.97%, trades 32955. Treat this as a retrieval description, not a recommendation to clone the strategy.

## Reuse Notes
- Auto-backfilled entry. Prefer mechanism-level reuse only.
- Do not infer best parameters from this report.
- Inspect source, weights, and IS PnL before using this as context for a new attempt.
