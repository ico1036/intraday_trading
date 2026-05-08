---
topic: range_position
status: open
hypothesis: "Position of close within recent (high, low) range is a bounded mean-reversion signal — extreme highs revert short-term, extreme lows bounce."
data_required: "high, low, close on 1m bars."
applicability: "Cross-sectional rank of normalized close-position; long bottom-rank, short top-rank."
date_created: 2026-05-08
last_updated: 2026-05-08
linked_alphas: []
---

## Sources

- [academic] Williams %R indicator (Larry Williams, 1973) — bounded oscillator
- [academic] Lo & MacKinlay (1990), "When Are Contrarian Profits Due to Stock Market Overreaction?"
  - Key: short-horizon overreaction in cross-section

## Mechanism

Within a fixed window of N bars, the position p = (close - low_N) / (high_N - low_N)
∈ [0, 1] measures where price sits in its recent range. Extreme values
(p ≈ 0 or 1) indicate exhaustion. Cross-sectionally, the basket member with
the highest p is most overextended; ranking and pair-trading the extremes
captures the mean-reverting drift.

## Applicability check

- Required data fields: high, low, close
- Required bar type: TIME
- Universe restriction: ≥4 symbols
- Fee headroom: depends on rebalance freq; hourly+ keeps turnover sane

## Verdict

Cheap, no fitted parameters beyond window N. Good baseline reversion cell.
