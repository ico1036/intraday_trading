---
topic: ts_donchian_trend_5d2week_rb60
status: open
hypothesis: "Trend-filter Donchian variant: fast=7200m, slow=20160m, hold=7200m, rebalance=60m. Targets IS trades > 500 with per_trade_sharpe > 0.11."
data_required: "1m high / low / close"
applicability: "Liquid majors; per-symbol breakout w/ slow regime filter"
date_created: 2026-05-09
last_updated: 2026-05-09
linked_alphas: ["is_064_ts_donchian_trend_5d10d", "is_068_ts_donchian_trend_5d2week"]
---

## Mechanism

Round-4 sweep: hold and rebalance variations of the round-3 trend-filter winners. Goal is to push trade count above the IS S7 threshold (500) while preserving the per-trade quality (~0.18-0.24) seen in round 3.
