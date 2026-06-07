# Post Analysis: xs_factor_calmarproxy20d_rev_c50

- kind: `alpha`
- run_id: `run_2026_05_full531_rerun_backtests`
- id: `xs_factor_calmarproxy20d_rev_c50`
- status: `IS_FAIL`
- family: `xs_factor_calmar_proxy_20d_fwd_c10`
- artifact_dir: `/Users/jj_home/Git/intraday_trading/archive/run_2026_05_full531_rerun_backtests/alphas/xs_factor_calmarproxy20d_rev_c50`
- source_notes: `['research/notes/xs_factor_zoo.md']`
- alpha_cell: `{"bar": "TIME", "exit": "signal_flip", "horizon": "multi_day", "idea_family": "xs_factor_calmar_proxy_20d_fwd_c10", "transform": "rolling_rank", "universe": "basket_full"}`

## Implemented Strategy
xs_factor_calmarproxy20d_fwd_c10 — auto-generated XS factor. Signal: calmar_proxy_20d direction=fwd concentration=0.1 Cross-sectional rank of ``_compute_score`` over the eligible universe each emit bar, top/bottom concentration_pct legs.

This section was auto-backfilled from archived source metadata and should be tightened manually before using it as high-confidence research memory.

## IS Performance State
- IS Sharpe: `-0.040310422564949724`
- IS Return: `-0.02181444245049133` (-2.18%)
- IS Max Drawdown: `-0.1762513590768807` (-17.63%)
- IS Trades: `60175`
- IS Win Rate: `0.4084586622351475`
- PnL bps simple: `227.39741435764662`
- PnL bps notional weighted: `6.4245215686440975`
- Artifact counts: `{"equity_rows": 373816, "trades_rows": 411688, "weights_rows": 362729}`

The current state is recorded as an IS-only artifact summary. This report does not use OS/full-period results for generation guidance.

## Goal Fit
No run-specific goal fit was inferred during automatic backfill. A future loop should compare this strategy against `research/wiki/goals/<run_id>.md` before reuse.

## Current Interpretation
alpha `xs_factor_calmarproxy20d_rev_c50` is indexed as family `xs_factor_calmar_proxy_20d_fwd_c10` with status `IS_FAIL`; IS Sharpe -0.04031, return -2.18%, max drawdown -17.63%, trades 60175. Treat this as a retrieval description, not a recommendation to clone the strategy.

## Reuse Notes
- Auto-backfilled entry. Prefer mechanism-level reuse only.
- Do not infer best parameters from this report.
- Inspect source, weights, and IS PnL before using this as context for a new attempt.
