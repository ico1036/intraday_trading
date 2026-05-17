---
topic: ts_low_vol_long_h28d
status: open
hypothesis: "Per-symbol long-only entry when 5-day realized vol falls below trailing 30-day median, hold 28d. Low-vol regime in crypto historically precedes trend-up periods; signal source (vol) is orthogonal to Donchian breakout (price)."
data_required: "1m close"
applicability: "Liquid majors; long-only; same hold/sizing as the working Donchian ensemble"
date_created: 2026-05-11
last_updated: 2026-05-11
linked_alphas: ["is_170_ts_donchian_long_persist_3d14d_h28d_w038"]
---

## Mechanism

Different entry signal from price-Donchian: trigger when vol percentile drops below 50% (calm). The 28d hold and 0.035 max_weight match the proven Donchian-persist parameters that survive OS. Goal is to produce a return stream that is uncorrelated with breakout-based alphas, suitable as an ensemble component.
