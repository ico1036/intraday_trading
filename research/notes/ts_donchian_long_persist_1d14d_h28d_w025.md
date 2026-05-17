---
topic: ts_donchian_long_persist_1d14d_h28d_w025
status: open
hypothesis: "Long-only persist Donchian: fast=1d, slow=14d, hold=28d, w=0.025. Round-17 sweep extension."
data_required: "1m high / low / close"
applicability: "Liquid majors; long-only with extended hold"
date_created: 2026-05-10
last_updated: 2026-05-10
linked_alphas: ["is_168_ts_donchian_long_persist_3d14d_h28d_w035"]
---

## Mechanism

Round-17 variant: tightens the parameter sweep with new fast (1d/9d/12d) and weight (0.025/0.032/0.040/0.042) values within the proven (slow, hold) bands.
