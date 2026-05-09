---
topic: ts_donchian_3day
status: open
hypothesis: "Per-symbol 3-day Donchian breakout: enter on 3-day high LONG / 3-day low SHORT, time-stop after 3 days."
data_required: "1m high / low / close"
applicability: "Faster horizon than is_014_ts_donchian_weekly"
date_created: 2026-05-09
last_updated: 2026-05-09
linked_alphas: ["is_014_ts_donchian_weekly"]
---

## Mechanism

Faster Donchian channel. More signals, shorter holds. Tests whether breakout continuation persists at sub-weekly horizon. Distinct idea_family from the weekly variant.
