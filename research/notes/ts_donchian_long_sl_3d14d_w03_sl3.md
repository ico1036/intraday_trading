---
topic: ts_donchian_long_sl_3d14d_w03_sl3
status: open
hypothesis: "Long-only persist Donchian with stop-loss at 3%: cap individual losers to boost Profit Factor and reduce DD."
data_required: "1m high / low / close"
applicability: "Liquid majors; long-only with risk-managed exits"
date_created: 2026-05-10
last_updated: 2026-05-10
linked_alphas: ["is_136_ts_donchian_persist_long3d10d_h14d"]
---

## Mechanism

is_136 had t=2.58 / N=1935 / bps=34.5 (S1, S2, S7 ✓) but DD=20% / PF=1.21 (S5, S6 fail). Stop-loss caps individual position drawdown at 3%, which both reduces aggregate DD and improves PF (sum_wins / |sum_losses|) by truncating large losses.
