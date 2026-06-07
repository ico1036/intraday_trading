# Post Analysis: xs_factor_bbwidth20d_fwd_c10

- kind: `alpha`
- run_id: `run_2026_05_full531_rerun_backtests`
- id: `xs_factor_bbwidth20d_fwd_c10`
- status: `IS_PASS`
- family: `xs_factor_bb_width_20d_fwd_c10`
- artifact_dir: `/Users/jj_home/Git/intraday_trading/archive/run_2026_05_full531_rerun_backtests/alphas/xs_factor_bbwidth20d_fwd_c10`
- source_notes: `['research/notes/xs_factor_zoo.md']`
- alpha_cell: `{"bar": "TIME", "exit": "signal_flip", "horizon": "multi_day", "idea_family": "xs_factor_bb_width_20d_fwd_c10", "transform": "rolling_rank", "universe": "basket_full"}`

## Implemented Strategy
xs_factor_bbwidth20d_fwd_c10 — auto-generated XS factor. Signal: bb_width_20d direction=fwd concentration=0.1 Cross-sectional rank of ``_compute_score`` over the eligible universe each emit bar, top/bottom concentration_pct legs.

This section was auto-backfilled from archived source metadata and should be tightened manually before using it as high-confidence research memory.

## IS Performance State
- IS Sharpe: `0.7805511101123126`
- IS Return: `0.5968168830888684` (59.68%)
- IS Max Drawdown: `-0.2520028477121808` (-25.20%)
- IS Trades: `11057`
- IS Win Rate: `0.48539386813783125`
- PnL bps simple: `-1884.5064469007789`
- PnL bps notional weighted: `63.58191296941751`
- Artifact counts: `{"equity_rows": 373816, "trades_rows": 78076, "weights_rows": 78163}`

The current state is recorded as an IS-only artifact summary. This report does not use OS/full-period results for generation guidance.

## Goal Fit
No run-specific goal fit was inferred during automatic backfill. A future loop should compare this strategy against `research/wiki/goals/<run_id>.md` before reuse.

## Current Interpretation
alpha `xs_factor_bbwidth20d_fwd_c10` is indexed as family `xs_factor_bb_width_20d_fwd_c10` with status `IS_PASS`; IS Sharpe 0.7806, return 59.68%, max drawdown -25.20%, trades 11057. Treat this as a retrieval description, not a recommendation to clone the strategy.

## Reuse Notes
- Auto-backfilled entry. Prefer mechanism-level reuse only.
- Do not infer best parameters from this report.
- Inspect source, weights, and IS PnL before using this as context for a new attempt.
