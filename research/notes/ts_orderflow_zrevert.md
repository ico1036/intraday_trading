---
topic: ts_orderflow_zrevert
status: open
hypothesis: "Per-symbol cumulative signed-volume z-score reversal. When recent taker-buy or taker-sell flow is extreme (|z| > entry_z), price tends to revert as informed flow exhausts. Distinct from price-based z-revert (which failed) because the input is flow, not price."
data_required: "1m volume + volume_imbalance"
applicability: "Liquid majors; per-symbol; intraday"
date_created: 2026-05-11
last_updated: 2026-05-11
linked_alphas: []
---

## Mechanism

Extreme cumulative net taker-buy (or sell) flow is often the late tail of a position build-up that exhausts itself — price tends to revert. Inputs come from `volume_imbalance × volume` which is orthogonal to log-return-based signals. Expected correlation with the Donchian trend family is low.

## Applicability check

- Required fields: volume, volume_imbalance
- Bar type: TIME 1m
- Fee headroom: short holds (~4h), needs decent per-trade edge — entry_z=2.5 controls trade frequency.

## Verdict

Even if Sharpe is modest, the lack of correlation to price-based trend alphas adds genuine diversification to an ensemble.
