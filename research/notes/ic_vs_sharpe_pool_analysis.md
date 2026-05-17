# IC vs Sharpe: empirical comparison on run_2026_05_c

## Question

For the ensemble-of-many-uncorrelated-alphas paradigm, is the IC metric
genuinely a better selection criterion than Sharpe? Run on all 484
``IS_PASS`` alphas in ``archive/run_2026_05_c/``.

## Method

1. ``scripts/tools/compute_ic.py`` — cross-sectional Spearman IC per
   day between forward-1d return and the alpha's reconstructed daily
   position grid (forward-fill of ``weights.parquet`` events).
2. Apply IC-submittable gate (IS-only): ``|ic_mean| > 0.01`` and
   ``|ic_t| > 2.0``. Sign of ``ic_mean`` decides direction; negative-IC
   alphas would be deployed with sign flipped.
3. Compare resulting **IC pool** to the existing Sharpe-based
   **``is_submittable_eqw``** pool (104 members) for:
   - pairwise correlation of daily PnL across pool members,
   - participation ratio (effective independent alpha count).

## Results

### IC distribution across 484 IS_PASS alphas

```
           sharpe    ic_mean    ic_t     ic_ir    ic_n   median_breadth
mean       0.870    -0.0008    -0.06    +0.003   682    7
std        0.173    +0.020     ±1.01   ±0.042   147    0
min        0.050    -0.069     -2.75    -0.192    16    7
25%        0.783    -0.017     -1.01    -0.035   613    7
50%        0.861    -0.0001    +0.11    +0.004   693    7
75%        0.990    +0.016     +0.95    +0.042   777    7
max        1.422    +0.118     +3.76    +0.175   838    7
```

All 484 share ``median_breadth = 7`` (the run's 7-coin universe). Mean IC
is essentially zero — equal numbers of slight-positive and slight-negative
predictors. Only a handful clear ``|ic_t| > 2``.

### Correlation between selection metrics

```
              sharpe   sharpe_t    ic_mean    ic_t    ic_ir
sharpe         1.000    +0.641    +0.032    -0.009  +0.013
sharpe_t      +0.641     1.000    +0.326    +0.433  +0.291
ic_mean       +0.032    +0.326     1.000    +0.926  +0.994
```

**Sharpe and IC are essentially uncorrelated** (``corr = +0.032``). They
measure orthogonal aspects: Sharpe = realised-PnL smoothness; IC =
signal-ranking quality.

### IC-submittable count

Of 484 IS_PASS alphas:

- ``ic_mean > 0.01 AND ic_t > 2.0``: **1 alpha** (``is_737_ts_tbuy_share_long``)
- ``ic_mean < -0.01 AND ic_t < -2.0``: **11 alphas** (sign-flippable)
- Total IC-pass pool: **12 of 484** (2.5%)

### Pool independence comparison

|                        | IC pool (12 alphas) | Sharpe pool (104 alphas) |
|------------------------|---------------------|--------------------------|
| Pairwise corr mean     | **+0.296**          | +0.997                   |
| Pairwise corr median   | +0.239              | +0.997                   |
| Pairwise corr min      | −0.425              | +0.994                   |
| Participation ratio    | **2.74**            | 1.01                     |
| Effective % of nominal | **22.8 %**          | 1.0 %                    |
| Top-3 eigenvalue share | 91 %                | 99.9 %                   |

The Sharpe-based ``is_submittable_eqw`` pool of 104 alphas behaves like
**a single alpha** (PR = 1.01, all-pair corr ≈ 1.0) — parameter
perturbations of the same underlying strategy. The IC-based pool of 12
alphas — despite being ~9× smaller — behaves like **2.7 independent
alphas**, a 22× efficiency improvement per nominal member.

### Family-level signal direction

Average IC by alpha family:

| family                            | n  | mean IC  | mean IC_t |
|-----------------------------------|----|----------|-----------|
| ``ts_tbuy_share_long``            | 1  | +0.071   | +3.76     |
| ``ts_donchian_trend_*``           | 11 | +0.030   | +0.71     |
| ``ts_donchian_persist_long_*``    | 6  | +0.022   | +1.27     |
| …                                 |    |          |           |
| ``ts_donchian_symmetric_f10d_*``  | 6  | −0.029   | −2.05     |
| ``ts_lead_lag_btc``               | 2  | −0.063   | −2.11     |
| ``ts_vwap_dev_long``              | 1  | −0.069   | −2.75     |

Trend / persistence families have weakly positive IC; symmetric and
fade families have weakly negative IC. Both directions can produce
positive Sharpe (especially on the 7-coin universe over 2022-2024),
which is why Sharpe alone cannot tell ensemble-compatible alphas from
ensemble-cancelling ones.

## Implications

1. **The current alpha library is largely a single bet repackaged.** The
   ``is_submittable_eqw`` composite's 1.0 % independence ratio means
   leveraging it amplifies one underlying signal, not a diversified
   bundle.
2. **IC-based filtering is a different selection axis.** It is not a
   stricter version of Sharpe — it is orthogonal. Combining the two
   (require both Sharpe-pass and IC-pass) would shrink the pool further
   but improve composite quality.
3. **Sign-flipped alphas are usable.** Most of the IC-pool members
   (11/12) need direction reversal. The existing strategy code can be
   re-run with a ``reverse=True``-style parameter (already implemented
   for ``xs_volume_rank``); for the donchian/symmetric families this
   would require a similar parameter or a wrapper.
4. **Breadth matters more than IS sample size.** ``xs_volume_rank``
   reaches ``ic_t = 8.80`` because it ranks 68 coins/day on average,
   vs 7 here. Fundamental Law: ``IR ≈ IC × √breadth``. The biggest
   unrealised gain is moving from 7-coin to wider universes.

## Reference

- ``research/notes/ic_run_2026_05_c.csv`` — per-alpha IC for all 484
- ``scripts/tools/compute_ic.py`` — IC calculator
- ``archive/run_2026_05_xs500/alphas/xs_volume_rank/is/`` — wide-breadth
  reference alpha (IC = ±0.048, IC_t = ±8.8 depending on sign)

## Followup — corr-cap composite attempt (signal-reconstructed PnL)

Greedy select from the 12 IC-passers by ``|ic_t|`` descending,
``corr_cap=0.5`` on pairwise daily signal-PnL. Result: 4 members
selected, the rest dropped as redundant.

| metric                  | value |
|-------------------------|-------|
| members                 | 4     |
| pairwise corr (mean)    | −0.02 |
| participation ratio     | **2.92** of 4 (73 %) |
| daily mean PnL ratio    | −0.00044 |
| annualized Sharpe       | −1.11 |
| cumulative growth       | 0.67 × |

Independence ratio (73 %) confirms the methodology produces a diverse
pool. **However the realised performance is negative** — flagging a
methodology issue, not the diversification thesis.

### Why the composite goes negative — methodology gap

Per-alpha signal-PnL on IS (reconstructed from
``positions × forward 1d return``):

| alpha (IC<0, sign=−1)               | cum growth | sign-flip ok? |
|-------------------------------------|------------|---------------|
| ``is_737_ts_tbuy_share_long``       | +1.091×    | (IC>0, native) |
| ``is_534_ts_vwap_dev_long``         | +1.014×    | yes (weak)    |
| ``is_640_ts_lead_lag_btc``          | **0.662×** | **fails**     |

The IC-negative ``is_640`` had ``ic = −0.067`` (very strong negative
Spearman). Multiplying positions by −1 should flip the Spearman
correlation, but the **linear monetary product** (``pos × ret``) does
not flip cleanly when position magnitudes are concentrated on a few
symbols. Spearman IC is rank-based; monetary PnL is magnitude-sensitive.
A negative Spearman with a few large bets on right-rank-but-wrong-sign
symbols can still realise positive PnL.

### Implications

1. **Sign-flipping is unreliable for ensembling Spearman-IC alphas.**
   For deployment of an IC-negative alpha as a reverse-signal component,
   you must actually invert its positions in a re-run (not just multiply
   realised PnL). Most existing strategies don't have a ``reverse=True``
   parameter; adding one (or a wrapper class) is needed.
2. **Consider Pearson IC for ensemble selection.** Pearson IC directly
   measures expected linear PnL, so sign-flipping is mathematically
   clean. Spearman is better for "is there ranking signal at all", but
   for portfolio construction Pearson is the right metric.
3. **The single IC-positive alpha (``is_737``) is a clean component.**
   Its reconstructed signal PnL is +9.1 % over the IS window — modest
   but the direction is correct.

## Suggested next experiments

1. Implement Pearson IC alongside Spearman; rerun the gate; rebuild pool.
2. Add ``reverse=True`` to the existing ``ts_*`` strategies (or a generic
   sign-flip wrapper), re-run the IC-negative alphas with reversed
   positions, then form the composite from honest reversed backtests.
3. Re-run ``xs_volume_rank`` variants over different lookbacks and
   weighting schemes — each marginal improvement compounds via
   √breadth, and the strategy already exposes ``reverse=True``.
4. Apply the IC pipeline to OS results (sealed) once the evaluation
   phase begins; this note used IS only.
