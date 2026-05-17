---
topic: ts_donchian_persist_5d14d_h14d
status: open
hypothesis: "Persist Donchian with longer hold (10-14d): fast=7200m, slow=20160m, hold=20160m. Targets moderate N (1000-3000) while preserving per-trade quality."
data_required: "1m high / low / close"
applicability: "Liquid majors; per-symbol breakout w/ regime filter & re-entry"
date_created: 2026-05-09
last_updated: 2026-05-09
linked_alphas: ["is_087_ts_donchian_persist_3d10d_h7d", "is_075_ts_donchian_trend_5d10d_h7d"]
---

## Mechanism

Round 5 h5d had too much trading drag (pts ~0.012). Round 6 extends hold to 10-14 days to reduce cycling within regime → expected pts ~0.05-0.10 at N ~1000-3000.
