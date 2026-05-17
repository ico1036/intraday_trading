---
topic: ts_donchian_persist_3d2week_h10d_w03
status: open
hypothesis: "Persist Donchian with reduced max_weight=0.03: same t-stat / per_trade_sharpe as larger-weight version, but DD scales linearly with position size."
data_required: "1m high / low / close"
applicability: "Liquid majors; per-symbol breakout w/ regime filter & re-entry"
date_created: 2026-05-09
last_updated: 2026-05-09
linked_alphas: ["is_099_ts_donchian_persist_5d14d_h14d"]
---

## Mechanism

DD scaling: persist h14d had t=2.45 DD=33%. Reducing max_weight to 0.05 should give t=2.45 (invariant) DD=11.8% — within S5 (<12%). Still need t > 2.5 for S1; combined with smaller-weight tightening, may slip through.
