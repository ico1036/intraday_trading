# Post Analysis: xs_factor_bouncefromlow60d_rev_c40

- kind: `alpha`
- run_id: `run_2026_05_full531_rerun_backtests`
- id: `xs_factor_bouncefromlow60d_rev_c40`
- status: `IS_FAIL`
- family: `xs_factor_bounce_from_low_60d_fwd_c10`
- artifact_dir: `/Users/jj_home/Git/intraday_trading/archive/run_2026_05_full531_rerun_backtests/alphas/xs_factor_bouncefromlow60d_rev_c40`
- source_notes: `['research/notes/xs_factor_zoo.md']`
- alpha_cell: `{"bar": "TIME", "exit": "signal_flip", "horizon": "multi_day", "idea_family": "xs_factor_bounce_from_low_60d_fwd_c10", "transform": "rolling_rank", "universe": "basket_full"}`

## Implemented Strategy
xs_factor_bouncefromlow60d_fwd_c10 — auto-generated XS factor. Signal: bounce_from_low_60d direction=fwd concentration=0.1 Cross-sectional rank of ``_compute_score`` over the eligible universe each emit bar, top/bottom concentration_pct legs.

This section was auto-backfilled from archived source metadata and should be tightened manually before using it as high-confidence research memory.

## IS Performance State
- IS Sharpe: `0.13818340952018834`
- IS Return: `0.03026627919133134` (3.03%)
- IS Max Drawdown: `-0.16430193021566242` (-16.43%)
- IS Trades: `43053`
- IS Win Rate: `0.4262420737230855`
- PnL bps simple: `-1694.0304376917566`
- PnL bps notional weighted: `-3.9108015555700715`
- Artifact counts: `{"equity_rows": 373816, "trades_rows": 305188, "weights_rows": 298578}`

The current state is recorded as an IS-only artifact summary. This report does not use OS/full-period results for generation guidance.

## Goal Fit
No run-specific goal fit was inferred during automatic backfill. A future loop should compare this strategy against `research/wiki/goals/<run_id>.md` before reuse.

## Current Interpretation
alpha `xs_factor_bouncefromlow60d_rev_c40` is indexed as family `xs_factor_bounce_from_low_60d_fwd_c10` with status `IS_FAIL`; IS Sharpe 0.1382, return 3.03%, max drawdown -16.43%, trades 43053. Treat this as a retrieval description, not a recommendation to clone the strategy.

## Reuse Notes
- Auto-backfilled entry. Prefer mechanism-level reuse only.
- Do not infer best parameters from this report.
- Inspect source, weights, and IS PnL before using this as context for a new attempt.
