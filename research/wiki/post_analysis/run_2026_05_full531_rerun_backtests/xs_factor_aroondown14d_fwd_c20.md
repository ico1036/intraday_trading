# Post Analysis: xs_factor_aroondown14d_fwd_c20

- kind: `alpha`
- run_id: `run_2026_05_full531_rerun_backtests`
- id: `xs_factor_aroondown14d_fwd_c20`
- status: `IS_FAIL`
- family: `xs_factor_aroon_down_14d_fwd_c10`
- artifact_dir: `/Users/jj_home/Git/intraday_trading/archive/run_2026_05_full531_rerun_backtests/alphas/xs_factor_aroondown14d_fwd_c20`
- source_notes: `['research/notes/xs_factor_zoo.md']`
- alpha_cell: `{"bar": "TIME", "exit": "signal_flip", "horizon": "multi_day", "idea_family": "xs_factor_aroon_down_14d_fwd_c10", "transform": "rolling_rank", "universe": "basket_full"}`

## Implemented Strategy
xs_factor_aroondown14d_fwd_c10 — auto-generated XS factor. Signal: aroon_down_14d direction=fwd concentration=0.1 Cross-sectional rank of ``_compute_score`` over the eligible universe each emit bar, top/bottom concentration_pct legs.

This section was auto-backfilled from archived source metadata and should be tightened manually before using it as high-confidence research memory.

## IS Performance State
- IS Sharpe: `0.11083675111171529`
- IS Return: `-0.0010449380491365445` (-0.10%)
- IS Max Drawdown: `-0.31279187826688226` (-31.28%)
- IS Trades: `26892`
- IS Win Rate: `0.4999256284396847`
- PnL bps simple: `-958.60029292722`
- PnL bps notional weighted: `0.11446699076333591`
- Artifact counts: `{"equity_rows": 373816, "trades_rows": 179676, "weights_rows": 175839}`

The current state is recorded as an IS-only artifact summary. This report does not use OS/full-period results for generation guidance.

## Goal Fit
No run-specific goal fit was inferred during automatic backfill. A future loop should compare this strategy against `research/wiki/goals/<run_id>.md` before reuse.

## Current Interpretation
alpha `xs_factor_aroondown14d_fwd_c20` is indexed as family `xs_factor_aroon_down_14d_fwd_c10` with status `IS_FAIL`; IS Sharpe 0.1108, return -0.10%, max drawdown -31.28%, trades 26892. Treat this as a retrieval description, not a recommendation to clone the strategy.

## Reuse Notes
- Auto-backfilled entry. Prefer mechanism-level reuse only.
- Do not infer best parameters from this report.
- Inspect source, weights, and IS PnL before using this as context for a new attempt.
