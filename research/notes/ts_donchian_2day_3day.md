---
topic: ts_donchian_2day_3day
status: open
hypothesis: "Asymmetric Donchian: channel=2880m, hold=4320m, rebalance=240m. Targets IS trades > 500 with edge preservation."
data_required: "1m high / low / close"
applicability: "Liquid majors; per-symbol breakout"
date_created: 2026-05-09
last_updated: 2026-05-09
linked_alphas: ["is_014_ts_donchian_weekly"]
---

## Mechanism

Asymmetric channel-vs-hold combination of the Donchian breakout. Distinct idea_family.
