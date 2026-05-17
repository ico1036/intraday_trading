---
topic: ts_donchian_long_persist_5d3week_h28d_w035
status: open
hypothesis: "Long-only persist h21d/h28d with reduced max_weight=0.035 — DD scales linearly so DD<12% achievable while preserving t-stat/PF."
data_required: "1m high / low / close"
applicability: "Liquid majors; long-only with reduced sizing"
date_created: 2026-05-10
last_updated: 2026-05-10
linked_alphas: ["is_161_ts_donchian_long_persist_3d14d_h28d_w04"]
---

## Mechanism

Round 13 winners reached t=2.79, PF=1.31, N=994, DD=12.2% — only DD slightly over the 12% threshold. Position size invariance: scaling max_weight from 0.04 to 0.035 reduces DD to ~10.7% while leaving t-stat / PF unchanged. Should pass all 5 IS-only S conditions.
