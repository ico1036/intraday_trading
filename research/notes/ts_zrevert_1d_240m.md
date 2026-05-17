---
topic: ts_zrevert_1d_240m
status: open
hypothesis: "Short-window extreme z-score mean reversion: window=1440m, hold=240m, rebalance=60m, entry_z=2.5. Many small-edge trades; targets N >> 500 with tight per-trade variance."
data_required: "1m close"
applicability: "Liquid majors; per-symbol mean reversion"
date_created: 2026-05-09
last_updated: 2026-05-09
linked_alphas: []
---

## Mechanism

Short-horizon extreme z-score reversal: when a symbol's recent log return is more than entry_z standard deviations from its own historical mean, fade it. Each trade is a small targeted move with low variance per trade. High frequency naturally produces N>>500 across the IS window.
