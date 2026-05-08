---
topic: pair_spread_meanrev
status: open
hypothesis: "Log price spread between two correlated crypto perps (BTC/ETH) is stationary around a slow-moving mean; deviations >|z|>1 mean-revert within hours."
data_required: "synchronous closes for both legs"
applicability: "Two-asset pair trade; LONG short-leg / SHORT long-leg when |z| extreme"
date_created: 2026-05-08
last_updated: 2026-05-08
linked_alphas: []
---

## Sources

- [academic] Gatev, Goetzmann, Rouwenhorst (2006), "Pairs Trading: Performance of a Relative-Value Arbitrage Rule" — RFS
  - Key: distance-method pair trading historically generated risk-adjusted abnormal returns
- [academic] Vidyamurthy (2004), "Pairs Trading: Quantitative Methods and Analysis"
  - Key: cointegration-based mean-reversion of log price ratios

## Mechanism

BTC and ETH share nearly all macro/funding factors. Their log-price ratio
drifts only slowly relative to short-horizon noise. When one leg deviates
materially from the recent ratio mean, market makers and arbitrageurs
rebalance toward the level, producing reversion.

## Applicability check

- Required data fields: close (both legs)
- Required bar type: TIME
- Universe restriction: pair (BTC + ETH)
- Fee headroom: depends on rebalance — hourly+ keeps round-trip cost manageable

## Verdict

Classic stat-arb baseline. Adds pair-universe diversification to the cell mix.
