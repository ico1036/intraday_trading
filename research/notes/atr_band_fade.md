---
topic: atr_band_fade
status: open
hypothesis: "When the absolute one-bar return exceeds k×ATR, the move is liquidity-driven and fades over the next several bars."
data_required: "high, low, close (for true range computation)."
applicability: "Per-symbol; SHORT after upward burst > k·ATR, LONG after downward burst < -k·ATR; hold until opposite burst."
date_created: 2026-05-08
last_updated: 2026-05-08
linked_alphas: []
---

## Sources

- [practitioner] Wilder (1978), original ATR concept
  - Key: ATR captures true range incorporating gaps; widely used for volatility-normalized signals
- [practitioner] LeBeau & Lucas (1992), "Computer Analysis of the Futures Market"
  - Key: ATR-based stops and signals are robust across asset classes

## Mechanism

Returns scaled by ATR are a robust volatility normalization (vs price-based
sigma). When a single bar's TR vastly exceeds the rolling-average TR, it
signals a liquidity event rather than steady directional flow. The fade
captures the inventory-rebalance reversion.

## Applicability check

- Required data fields: high, low, close
- Required bar type: TIME
- Universe restriction: any
- Fee headroom: k=3 produces sparse triggers (~1-2/day per symbol)

## Verdict

Cousin of bb_band_fade but with TR-based normalization. New cell family.
