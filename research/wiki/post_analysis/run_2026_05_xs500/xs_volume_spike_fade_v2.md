# Post Analysis: xs_volume_spike_fade_v2

- kind: `alpha`
- run_id: `run_2026_05_xs500`
- id: `xs_volume_spike_fade_v2`
- status: `IS_FAIL`
- family: `xs_volume_spike_fade_v2`
- artifact_dir: `/Users/jj_home/Git/intraday_trading/archive/run_2026_05_xs500/alphas/xs_volume_spike_fade_v2`
- source_notes: `['research/notes/xs_volume_spike_fade_v2.md']`
- alpha_cell: `{"bar": "TIME", "exit": "signal_flip", "horizon": "multi_day", "idea_family": "xs_volume_spike_fade_v2", "transform": "rolling_rank", "universe": "basket_full"}`

## Implemented Strategy
xs_volume_spike_fade_v2 — fade suspicious crypto volume spikes. This is a filtered version of the live reverse volume-rank idea. It shorts liquid symbols whose prior-day quote volume spikes versus their own recent baseline, but avoids shorting names with strong positive price confirmation. The long book is built from liquid, positively trending names with non-extreme volume so the portfolio stays dollar neutral.

This section was auto-backfilled from archived source metadata and should be tightened manually before using it as high-confidence research memory.

## IS Performance State
- IS Sharpe: `-0.2717843554957906`
- IS Return: `-0.10192912177531252` (-10.19%)
- IS Max Drawdown: `-0.14041148631853476` (-14.04%)
- IS Trades: `1705`
- IS Win Rate: `0.5208211143695015`
- PnL bps simple: `-238.88080191635476`
- PnL bps notional weighted: `-25.25291166513803`
- Artifact counts: `{"equity_rows": 199227, "trades_rows": 14129, "weights_rows": 13982}`

The current state is recorded as an IS-only artifact summary. This report does not use OS/full-period results for generation guidance.

## Goal Fit
No run-specific goal fit was inferred during automatic backfill. A future loop should compare this strategy against `research/wiki/goals/<run_id>.md` before reuse.

## Current Interpretation
alpha `xs_volume_spike_fade_v2` is indexed as family `xs_volume_spike_fade_v2` with status `IS_FAIL`; IS Sharpe -0.2718, return -10.19%, max drawdown -14.04%, trades 1705. Treat this as a retrieval description, not a recommendation to clone the strategy.

## Reuse Notes
- Auto-backfilled entry. Prefer mechanism-level reuse only.
- Do not infer best parameters from this report.
- Inspect source, weights, and IS PnL before using this as context for a new attempt.
