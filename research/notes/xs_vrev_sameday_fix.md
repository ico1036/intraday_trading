# xs_vrev — same-day universe fix

## Problem

The original xs_volume_rank reverse strategies (base, vol-target,
concentration, conc+vol) carry quote_volume state across days using
`_commit_yesterday` with an *update*: every symbol that ever reported
`qv > 0` stays in the ranking universe forever. EDA never had this
state — it reranked the cross-section using `panels[s]['quote_volume']`
on each `t`, so symbols missing today's bar simply dropped out.

The mismatch roughly doubled the active universe inside the
backtester. Concentration variants pick `k = int(n * q)` per leg, so a
2x larger `n` gives a 2x larger `k`, which halves `per_leg = 0.5/k`,
which halves the realised gross exposure. EDA fee-free cum +67.8%
became backtest cum +26.2% — a 60% leakage explained entirely by the
weight halving.

## Fix

`_commit_yesterday` becomes a *replace*:

```python
self._prev_qv = {s: q for s, q in self._today_qv.items()
                 if q is not None and q > 0}
```

Closes for the rolling vol estimator stay updated incrementally because
they are a history; only `qv` (the ranking signal) is point-in-time.

## Variants

| variant         | original cell          | sameday cell                  |
|-----------------|------------------------|-------------------------------|
| Concentration   | xs_vrev_conc           | xs_vrev_conc_sameday          |
| Vol-target      | xs_vrev_vol_target     | xs_vrev_vol_target_sameday    |
| Concentration+V | xs_vrev_conc_vol       | xs_vrev_conc_vol_sameday      |

## Validation (xs_vrev_conc_sameday on IS 2022-2024)

- EDA fee-free cum:          **+67.8%** (sharpe 0.96)
- Old backtest IS cum:        +26.2% (sharpe 0.61)
- Sameday backtest IS cum:    **+43.9%** (sharpe 0.61–0.69)

The remaining EDA→backtest gap is fees (≈ +5 bps × ~7k trade legs) and
next-bar-open fill timing. Same-day fix closes the systematic chunk.

## Auditing future EDA-driven alphas

The root cause was a *cumulative state field* (`_prev_qv`) being treated
as a *point-in-time signal* in the strategy. Any alpha that ranks on a
state dict that grows by `update` instead of being reset on each day
flip is suspect. When EDA→IS gap is unreasonable, audit `_commit_*`
methods first.
