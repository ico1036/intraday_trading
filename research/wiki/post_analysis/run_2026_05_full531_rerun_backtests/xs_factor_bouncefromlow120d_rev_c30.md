# Post Analysis: xs_factor_bouncefromlow120d_rev_c30

- kind: `alpha`
- run_id: `run_2026_05_full531_rerun_backtests`
- id: `xs_factor_bouncefromlow120d_rev_c30`
- status: `IS_FAIL`
- family: `xs_factor_bounce_from_low_120d_fwd_c10`
- artifact_dir: `/Users/jj_home/Git/intraday_trading/archive/run_2026_05_full531_rerun_backtests/alphas/xs_factor_bouncefromlow120d_rev_c30`
- source_notes: `['research/notes/xs_factor_zoo.md']`
- alpha_cell: `{"bar": "TIME", "exit": "signal_flip", "horizon": "multi_day", "idea_family": "xs_factor_bounce_from_low_120d_fwd_c10", "transform": "rolling_rank", "universe": "basket_full"}`

## Implemented Strategy
xs_factor_bouncefromlow120d_fwd_c10 — auto-generated XS factor. Signal: bounce_from_low_120d direction=fwd concentration=0.1 Cross-sectional rank of ``_compute_score`` over the eligible universe each emit bar, top/bottom concentration_pct legs.

This section was auto-backfilled from archived source metadata and should be tightened manually before using it as high-confidence research memory.

## IS Performance State
- IS Sharpe: `0.05502388192523636`
- IS Return: `-0.004476327333826521` (-0.45%)
- IS Max Drawdown: `-0.1581193433223822` (-15.81%)
- IS Trades: `28114`
- IS Win Rate: `0.4278651205804937`
- PnL bps simple: `-156.58899800423188`
- PnL bps notional weighted: `-12.368779911505458`
- Artifact counts: `{"equity_rows": 373816, "trades_rows": 206829, "weights_rows": 205969}`

The current state is recorded as an IS-only artifact summary. This report does not use OS/full-period results for generation guidance.

## Goal Fit
No run-specific goal fit was inferred during automatic backfill. A future loop should compare this strategy against `research/wiki/goals/<run_id>.md` before reuse.

## Current Interpretation
alpha `xs_factor_bouncefromlow120d_rev_c30` is indexed as family `xs_factor_bounce_from_low_120d_fwd_c10` with status `IS_FAIL`; IS Sharpe 0.05502, return -0.45%, max drawdown -15.81%, trades 28114. Treat this as a retrieval description, not a recommendation to clone the strategy.

## Reuse Notes
- Auto-backfilled entry. Prefer mechanism-level reuse only.
- Do not infer best parameters from this report.
- Inspect source, weights, and IS PnL before using this as context for a new attempt.
