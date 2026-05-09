---
topic: xs_weekly_momentum
status: open
hypothesis: "Cross-sectional weekly momentum: long the basket's strongest 7-day performer, short the weakest."
data_required: "1m close"
applicability: "Liquid majors; long/short cross-section; weekly rebalance"
date_created: 2026-05-09
last_updated: 2026-05-09
linked_alphas: []
---

## Mechanism

Sign-flip of xs_weekly_reversal. Tests whether the dispersion across the basket follows momentum (winners keep winning) or reversal (losers bounce back) at the weekly horizon. Different idea_family from xs_weekly_reversal so it's a distinct cell.

## Verdict

Whichever direction has positive Sharpe wins the cross-section regime test. Both running side-by-side resolves the ambiguity.
