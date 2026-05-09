---
topic: ts_donchian_fade_weekly
status: open
hypothesis: "Fade weekly Donchian breakouts: SHORT on 7-day high, LONG on 7-day low, time-stop 1 week."
data_required: "1m high / low / close"
applicability: "Direction-opposite of is_014"
date_created: 2026-05-09
last_updated: 2026-05-09
linked_alphas: ["is_014_ts_donchian_weekly"]
---

## Mechanism

Mean-reversion at the breakout level. If breakouts are mostly head-fakes in this regime, fading them is profitable. Distinct cell from is_014 by idea_family.
