---
topic: ts_donchian_long_persist_3d14d_h42d_w038
status: open
hypothesis: "Long-only persist Donchian: fast=3d, slow=14d, hold=42d, w=0.038. Sweep variant of round 14-15 SUBMITTABLE family."
data_required: "1m high / low / close"
applicability: "Liquid majors; long-only with extended hold"
date_created: 2026-05-10
last_updated: 2026-05-10
linked_alphas: ["is_168_ts_donchian_long_persist_3d14d_h28d_w035"]
---

## Mechanism

Param-sweep variant. Working family: long-only persist Donchian with 10-14d slow regime + 28-42d hold + small position sizing. Each combo is a distinct idea_family / cell signature.
