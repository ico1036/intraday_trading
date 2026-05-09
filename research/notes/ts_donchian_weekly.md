---
topic: ts_donchian_weekly
status: open
hypothesis: "Breaking the rolling 7-day high / low signals continuation; enter LONG on new highs and SHORT on new lows, time-stop after 1 week."
data_required: "1m high / low / close"
applicability: "Liquid majors; per-symbol; checks every 4 hours, holds 7 days"
date_created: 2026-05-09
last_updated: 2026-05-09
linked_alphas: []
---

## Mechanism

Classic Donchian breakout. Different *transform* (rolling_rank — position within range) and *exit* (time_stop) than every prior alpha in this run, so cell-distinct. Only fires when price actually breaks through, so signal frequency is naturally regime-aware.

## Verdict

Trend-following with built-in regime filter. Should perform well in directional regimes (2024 bull) and stay flat in choppy ones (some of 2023). Net depends on regime mix.
