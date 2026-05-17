---
topic: ts_orderflow_intraday_momentum
status: open
hypothesis: "Intraday cumulative signed-volume momentum: when 4h flow z-score exceeds ±1.5σ vs 2-day window, take the same direction. Shorter horizon than the weekly orderflow alpha; signal source is orthogonal to price-Donchian."
data_required: "1m volume + volume_imbalance"
applicability: "Liquid majors; per-symbol; intraday"
date_created: 2026-05-11
last_updated: 2026-05-11
linked_alphas: []
---

## Mechanism

Crypto round 8 fade experiments all failed — short-horizon does not mean-revert. Reversing direction: persistent taker-buy flow over 4h precedes continued price strength for at least the next 8h on liquid majors. Follow the flow.

Source is signed-volume, not log return; correlation with price-Donchian alphas expected to be low.

## Verdict

If signal works at all, contributes a low-correlation component to the trend-Donchian-dominated ensemble.
