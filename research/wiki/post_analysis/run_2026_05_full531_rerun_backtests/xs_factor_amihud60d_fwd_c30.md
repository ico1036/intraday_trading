# Post Analysis: xs_factor_amihud60d_fwd_c30

- kind: `alpha`
- run_id: `run_2026_05_full531_rerun_backtests`
- id: `xs_factor_amihud60d_fwd_c30`
- status: `IS_PASS`
- family: `xs_factor_amihud_60d_fwd_c10`
- artifact_dir: `/Users/jj_home/Git/intraday_trading/archive/run_2026_05_full531_rerun_backtests/alphas/xs_factor_amihud60d_fwd_c30`
- source_notes: `['research/notes/xs_factor_zoo.md']`
- alpha_cell: `{"bar": "TIME", "exit": "signal_flip", "horizon": "multi_day", "idea_family": "xs_factor_amihud_60d_fwd_c10", "transform": "rolling_rank", "universe": "basket_full"}`

## Implemented Strategy
xs_factor_amihud60d_fwd_c10 — auto-generated XS factor. Signal: amihud_60d direction=fwd concentration=0.1 Cross-sectional rank of ``_compute_score`` over the eligible universe each emit bar, top/bottom concentration_pct legs.

This section was auto-backfilled from archived source metadata and should be tightened manually before using it as high-confidence research memory.

## IS Performance State
- IS Sharpe: `1.897153727510854`
- IS Return: `0.6563315195004001` (65.63%)
- IS Max Drawdown: `-0.08177887409453355` (-8.18%)
- IS Trades: `29893`
- IS Win Rate: `0.5028602013849396`
- PnL bps simple: `21.95449339186001`
- PnL bps notional weighted: `99.46705053541248`
- Artifact counts: `{"equity_rows": 373816, "trades_rows": 205256, "weights_rows": 205576}`

The current state is recorded as an IS-only artifact summary. This report does not use OS/full-period results for generation guidance.

## Goal Fit
No run-specific goal fit was inferred during automatic backfill. A future loop should compare this strategy against `research/wiki/goals/<run_id>.md` before reuse.

## Current Interpretation
alpha `xs_factor_amihud60d_fwd_c30` is indexed as family `xs_factor_amihud_60d_fwd_c10` with status `IS_PASS`; IS Sharpe 1.897, return 65.63%, max drawdown -8.18%, trades 29893. Treat this as a retrieval description, not a recommendation to clone the strategy.

## Reuse Notes
- Auto-backfilled entry. Prefer mechanism-level reuse only.
- Do not infer best parameters from this report.
- Inspect source, weights, and IS PnL before using this as context for a new attempt.
