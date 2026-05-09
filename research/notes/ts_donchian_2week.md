---
topic: ts_donchian_2week
status: open
hypothesis: "Per-symbol 14-day Donchian breakout: longer-horizon variant of is_014; rarer signals, longer holds."
data_required: "1m high / low / close"
applicability: "Slower than weekly Donchian"
date_created: 2026-05-09
last_updated: 2026-05-09
linked_alphas: ["is_014_ts_donchian_weekly"]
---

## Mechanism

Two-week Donchian channel; signals only fire on genuinely new 14-day extremes, so noise is filtered further. Distinct idea_family.
