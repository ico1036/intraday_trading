---
topic: ts_compose_donchian_5d10d
status: open
hypothesis: "Composite Donchian: enter only when fast (channel=7200m) AND slow (channel=14400m) channels agree on direction. Filters single-horizon noise."
data_required: "1m high / low / close"
applicability: "Liquid majors; per-symbol breakout with dual-confirmation"
date_created: 2026-05-09
last_updated: 2026-05-09
linked_alphas: ["is_014_ts_donchian_weekly"]
---

## Mechanism

Multi-horizon agreement filters out the noise common to single-channel Donchian breakout. Higher conviction signals → expected tighter per-trade PnL variance → higher per_trade Sharpe and t-stat. Trade count drops vs single-channel since both must agree.
