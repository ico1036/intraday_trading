---
topic: ts_donchian_persist_3d2week_h5d
status: open
hypothesis: "Trend-filter Donchian with regime-persistent re-entry: fast=4320m, slow=20160m, hold=7200m. After time-stop within active regime, auto re-enter — boosts trade count without losing per-trade quality."
data_required: "1m high / low / close"
applicability: "Liquid majors; per-symbol breakout w/ regime filter & re-entry"
date_created: 2026-05-09
last_updated: 2026-05-09
linked_alphas: ["is_075_ts_donchian_trend_5d10d_h7d", "is_068_ts_donchian_trend_5d2week"]
---

## Mechanism

Round-4 trend-filter winners had per_trade_sharpe up to 0.26 but only 120-180 trades. Adding regime-persistent re-entry (auto re-enter after time-stop while regime unchanged) multiplies trade count by ~regime_duration / hold without requiring new breakouts. Same per-trade quality expected if regime quality holds.
