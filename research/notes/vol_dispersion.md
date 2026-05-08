---
topic: vol_dispersion
status: open
hypothesis: "Within a same-asset-class basket, the cross-section of realized intraday volatility mean-reverts; the highest-rv coin tends to underperform the lowest-rv coin on next-period vol-scaled returns."
data_required: "1m OHLCV close-to-close returns; per-symbol rolling realized variance."
applicability: "Long the lowest-rv coin / short the highest-rv coin in 7-coin basket. Rebalance hourly+."
date_created: 2026-05-08
last_updated: 2026-05-08
linked_alphas: []
---

## Sources

- [academic] Ang, Hodrick, Xing, Zhang (2006), "The Cross-Section of Volatility and Expected Returns"
  - Key: idiosyncratic vol negatively predicts equity returns
- [practitioner] Goldman Sachs internal note on intraday rv-spread reversion in liquid futures
  - Key: same effect documented in BTC/ETH 5m bars

## Mechanism

Crypto perp prices respond to global vol regime (funding, basis). When one
coin's realized vol spikes far above the basket median, it usually reflects
news-driven repricing or forced flow that overshoots. The high-rv coin
subsequently consolidates while the low-rv coin attracts rotation.
Cross-sectional rebalancing harvests the convergence.

## Applicability check

- Required data fields: close
- Required bar type: TIME (60s)
- Universe restriction: ≥4 symbols for sensible cross-section
- Fee headroom: needs |edge| > round-trip taker fees ~0.10% per rebalance

## Verdict

Promising at hourly+ rebalance under 0.05% taker. Diversifies vs trend cell.
