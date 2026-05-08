---
topic: vol_adjusted_momentum
status: open
hypothesis: "Cross-sectional momentum ranked by return / realized vol outperforms raw return ranking; vol-scaling stabilizes signal across regime shifts."
data_required: "close prices for trailing returns and rv."
applicability: "Basket top-k long/short on momentum/sigma ranks."
date_created: 2026-05-08
last_updated: 2026-05-08
linked_alphas: []
---

## Sources

- [academic] Moskowitz, Ooi, Pedersen (2012), "Time Series Momentum" — JFE
  - Key: vol-scaling raises Sharpe of TS-momentum across asset classes
- [academic] Asness, Moskowitz, Pedersen (2013), "Value and Momentum Everywhere" — JF

## Mechanism

Raw returns are dominated by high-vol names; their momentum signal is noisy.
Dividing by realized sigma normalizes the signal, so cross-sectional ranks
reflect risk-adjusted persistence rather than vol exposure. Empirically this
removes the negative skew of raw momentum and keeps drift.

## Applicability check

- Required data fields: close
- Required bar type: TIME
- Universe restriction: ≥4 symbols
- Fee headroom: depends on rebalance — daily+ is fee-friendly

## Verdict

Robust momentum variant. Use as one of several momentum cells.
