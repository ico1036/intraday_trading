---
topic: orb_fade
status: open
hypothesis: "In crypto perp markets at 1m bar resolution, breakouts of the session opening range FADE rather than continue — closing back inside the range within hours."
data_required: "OHLC on minute bars; UTC timestamps."
applicability: "Per-symbol or basket; trigger SHORT on break above OR-high, LONG below OR-low; flat at session end."
date_created: 2026-05-08
last_updated: 2026-05-08
linked_alphas: []
---

## Sources

- [academic] Lo & MacKinlay (1990), "When Are Contrarian Profits Due to Stock Market Overreaction?" — RFS
  - Key: short-horizon overreaction in cross-section is the dominant pattern in liquid markets without persistent informational drift
- [practitioner] is_013 internal result (this run): ORB-continuation produced 24% win rate over 919 trades — strong evidence the inverse signal carries the edge
  - Key: empirical complement of breakout fail = breakout fade

## Mechanism

Without a strong news shock anchoring the breakout, the move outside the
opening range typically reflects liquidity-driven exhaustion: stops triggered,
short-term traders chasing. Inventory holders absorb and revert. In a
mean-reverting regime (which the IS window for this run appears to be),
fading the break captures the snap-back.

## Applicability check

- Required data fields: high, low, close, timestamp
- Required bar type: TIME
- Universe restriction: any
- Fee headroom: same low-turnover profile as ORB-cont (~2 trades/symbol/day)

## Verdict

Direct empirical complement to the failed ORB-cont. Worth one cell.
