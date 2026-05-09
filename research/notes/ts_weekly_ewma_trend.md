---
topic: ts_weekly_ewma_trend
status: open
hypothesis: "Per-symbol EWMA-residual trend signal at weekly horizon: when fast EWMA (1-day) deviates upward from slow EWMA (1-week) by more than entry threshold, enter LONG; deviating downward, SHORT. Rebalance weekly."
data_required: "1m close"
applicability: "Liquid majors; per-symbol; weekly rebalance"
date_created: 2026-05-09
last_updated: 2026-05-09
linked_alphas: []
---

## Sources

- [practitioner] Hurst, Ooi, Pedersen (2017) "A century of evidence on trend-following investing", AQR.
  - Key: EWMA-crossover trend signals are among the most robust and lowest-turnover trend implementations.
- [academic] Baz et al (2015) "Dissecting investment strategies in the cross section and time series".

## Mechanism

EWMA-residual signals smooth out noise relative to point-to-point return calculations and naturally deliver a slowly-varying signal — fewer flips per period than the discrete-return formulation in is_005. Same weekly cadence keeps the fee profile identical; the *transform* (ewma_residual vs z_score) is the cell-distinguishing axis.

## Applicability check

- Required data fields: close
- Required bar type: TIME 1m (one update per minute drives the EWMA)
- Universe restriction: per-symbol; basket_full
- Fee headroom: similar or lower than is_005

## Verdict

Companion test to is_005 — same direction (momentum) but smoother signal generation. If both pass, an ensemble of price-z and price-ewma signals could provide additional diversification.
