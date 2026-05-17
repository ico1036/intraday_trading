---
topic: ts_donchian_persist_long5d2week_h14d
status: open
hypothesis: "Long-only persist Donchian: no SHORT side, hold cycles within LONG regimes only. Halves directional exposure → smaller DD; per-trade quality similar to long-side of two-sided variant."
data_required: "1m high / low / close"
applicability: "Liquid majors; long-only"
date_created: 2026-05-09
last_updated: 2026-05-09
linked_alphas: ["is_099_ts_donchian_persist_5d14d_h14d"]
---

## Mechanism

Long-only halves DD because we are flat during SHORT regimes, and the basket has structural upward drift. Trade count drops about half but per_trade_sharpe should be similar to the long-side of the bidirectional version. May tilt overall t-stat depending on which side dominated quality.
