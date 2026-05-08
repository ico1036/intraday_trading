---
topic: dispersion_meanrev
status: open
hypothesis: "When a single coin's return diverges far from the equally-weighted basket mean, the gap mean-reverts within hours."
data_required: "synchronous closes across the basket."
applicability: "Cross-sectional residual reversal: trade -(r_i - r_basket)."
date_created: 2026-05-08
last_updated: 2026-05-08
linked_alphas: []
---

## Sources

- [academic] Avellaneda & Lee (2010), "Statistical Arbitrage in the U.S. Equities Market"
  - Key: cross-sectional residual mean-reversion is the textbook stat-arb signal
- [academic] Khandani & Lo (2007), "What Happened to the Quants in August 2007?"
  - Key: same residual-reversal alpha that crashed in August 2007

## Mechanism

Coins in the same asset class share a common factor (BTC dominance, crypto
beta). Idiosyncratic divergence — one coin spiking while the basket sleeps
— is typically liquidity-driven and reverts as market-makers re-anchor.
Trade the residual: long undershooters, short overshooters.

## Applicability check

- Required data fields: close
- Required bar type: TIME
- Universe restriction: ≥4 symbols
- Fee headroom: needs hourly rebalance to clear fees

## Verdict

The single most-tested cross-sectional alpha. Strong baseline reversion cell.
