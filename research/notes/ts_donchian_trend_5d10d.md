---
topic: ts_donchian_trend_5d10d
status: open
hypothesis: "Donchian trend-filter: slow channel (14400m) sets regime, fast channel (7200m) provides entry triggers within that regime. Multiple re-entries during a slow trend → boost N while preserving per-trade quality."
data_required: "1m high / low / close"
applicability: "Liquid majors; per-symbol breakout w/ regime filter"
date_created: 2026-05-09
last_updated: 2026-05-09
linked_alphas: ["is_014_ts_donchian_weekly", "is_058_ts_compose_donchian_5d10d"]
---

## Mechanism

The composite Donchian (round 2) suffered low N because both channels needed to fire simultaneously. Trend-filter pattern: slow channel state persists between events (regime stays LONG since last slow new high until a new slow low flips it). Fast channel can trigger many times in same direction during regime → multiple entries per slow trend.
