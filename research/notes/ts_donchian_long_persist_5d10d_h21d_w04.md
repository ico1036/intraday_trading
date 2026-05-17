---
topic: ts_donchian_long_persist_5d10d_h21d_w04
status: open
hypothesis: "Long-only persist with very long hold (h21.0d): fewer cycles per regime → expected higher PF and tighter DD per-trade variance."
data_required: "1m high / low / close"
applicability: "Liquid majors; long-only with extended hold"
date_created: 2026-05-10
last_updated: 2026-05-10
linked_alphas: ["is_136_ts_donchian_persist_long3d10d_h14d"]
---

## Mechanism

Round 6 persist h14d had PF 1.13-1.18. Extending hold to 21-28 days reduces re-entry frequency within a regime — each trade captures larger move on average. Should lift per-trade quality and PF.
