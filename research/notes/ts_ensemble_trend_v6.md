---
topic: ts_ensemble_trend_v6
status: open
hypothesis: "Ensemble of 3 trend-filter slots, each with independent (fast, slow, hold). Slots aggregate into single per-symbol position; each slot adds entries → N multiplied without per-slot quality loss."
data_required: "1m high / low / close"
applicability: "Liquid majors; per-symbol breakout ensemble"
date_created: 2026-05-09
last_updated: 2026-05-09
linked_alphas: ["is_075_ts_donchian_trend_5d10d_h7d"]
---

## Mechanism

Round 4 trend-h7d had pts=0.26 at N=120 but failed S7 (N>500). Round 6 persist scaled N (2000+) but pts collapsed to 0.04. Ensemble: run multiple INDEPENDENT trend-filter slots (different fast/slow/hold params) within one alpha. Each slot contributes its own ~120 entries → 3-slot ensemble ≈ 360 trades, 4-slot ≈ 480, with per-slot quality preserved (independent signals). Position weight per slot is reduced (0.07) so aggregate exposure stays ≤ 1.0.
