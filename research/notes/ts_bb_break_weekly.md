---
topic: ts_bb_break_weekly
status: open
hypothesis: "Bollinger band breakout (close > upper band → LONG, close < lower band → SHORT). 7-day window, k=2 sigma, 1-week hold."
data_required: "1m close"
applicability: "Volatility-normalized breakout"
date_created: 2026-05-09
last_updated: 2026-05-09
linked_alphas: []
---

## Mechanism

Different signal construction from is_014: BB is volatility-normalized whereas Donchian uses raw extreme. Different transform candidate (z_score) and idea_family. Should fire across volatility regimes more uniformly.
