---
topic: ts_donchian_long_momo_5d14d_h14d_m3d_w04
status: open
hypothesis: "Long-only persist with momentum-confirmation re-entry: re-enter only when 4320m return is positive — filters pullback re-entries → boost PF (>1.3) and reduce DD."
data_required: "1m close + high/low for channel"
applicability: "Liquid majors; long-only with momentum filter"
date_created: 2026-05-10
last_updated: 2026-05-10
linked_alphas: ["is_136_ts_donchian_persist_long3d10d_h14d"]
---

## Mechanism

is_136 had t=2.58 / N=1935 / bps=34.5 (S1, S2, S7 ✓), but DD=20% / PF=1.21 (S5, S6 fail). Filter re-entries: only re-enter while regime LONG AND recent 4320m return > 0. Should drop DD (avoid catching pullbacks) and improve PF (sum_wins/|sum_losses|).
