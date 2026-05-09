---
topic: xs_weekly_reversal
status: open
hypothesis: "On weekly rebalance, the worst-performing symbol of the past 7 days outperforms the best over the following week — cross-sectional reversal applied at a slower clock than the failed xs_daily_reversal."
data_required: "1m close (only end-of-window prices used)"
applicability: "Liquid majors; long/short cross-section; weekly rebalance"
date_created: 2026-05-09
last_updated: 2026-05-09
linked_alphas: []
---

## Sources

- [academic] Da, Liu, Schaumburg (2014) "A closer look at the short-term return reversal", Management Science.
  - Key: cross-section reversal is strongest at 1-week horizon in high-volatility markets.
- [practitioner] Bianchi et al (2021) "On the persistence of cryptocurrency returns".

## Mechanism

The xs_daily_reversal cell already failed (sharpe -3.0, win_rate 56.5%): the signal direction was consistent with reversal but per-trade edge was eaten by fees over ~1600 trades. At weekly cadence, only ~12 cross-section reranks happen → ~170 trades total → roughly 10x less fee drag, exposing whatever post-fee edge the cross-section reversal carries.

## Applicability check

- Required data fields: close
- Required bar type: TIME 1m (10080 bars = 7 days)
- Universe restriction: 5+ symbols for stable cross-section
- Fee headroom: ~12 rebalances × 4 active legs × 2 trades = ~96–170 trades

## Verdict

Direct lower-frequency variant of xs_daily_reversal. If the daily edge is real and just buried by fees, the weekly version should surface it.
