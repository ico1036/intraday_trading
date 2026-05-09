---
topic: ts_voltarget_long
status: open
hypothesis: "Long-only basket sized inversely to realized vol: position weight = target_vol / realized_vol per symbol."
data_required: "1m close"
applicability: "Liquid majors; per-symbol; weekly rebalance, vol-stop"
date_created: 2026-05-09
last_updated: 2026-05-09
linked_alphas: []
---

## Mechanism

Long-only crypto exposure with realized-vol-targeted sizing. Smaller positions when vol spikes (e.g. Aug 5 2024), larger when calm. Vol-stop exits if realized vol blows past 2x the target. Different cell from is_008 (vol_stop exit, idea_family).

## Verdict

Crypto's structural drift is upward over multi-year horizons; vol targeting tames the drawdown profile. Should pass on the IS that includes 2022 bear if vol filter cuts exposure during the worst stretches.
